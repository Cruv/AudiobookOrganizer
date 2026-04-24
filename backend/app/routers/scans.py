import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.scan import Scan
from app.schemas.scan import ScanCreate, ScanDetailResponse, ScanResponse

router = APIRouter(prefix="/api/scans", tags=["scans"])

browse_router = APIRouter(prefix="/api", tags=["browse"])


BROWSE_BLOCKED_PATHS = {
    "/proc", "/sys", "/dev", "/run", "/boot", "/root",
    "/etc/shadow", "/etc/passwd", "/etc/ssh",
}


@browse_router.get("/browse")
def browse_directory(path: str = Query(default="/")):
    """List subdirectories at a given path for the directory browser."""
    import pathlib

    # Resolve to absolute path and prevent directory traversal
    resolved = str(pathlib.Path(path).resolve())

    # Block access to sensitive system directories and app data (contains auth tokens, DB)
    for blocked in BROWSE_BLOCKED_PATHS:
        if resolved == blocked or resolved.startswith(blocked + "/"):
            raise HTTPException(status_code=403, detail="Access denied")

    if resolved == "/app/data" or resolved.startswith("/app/data/"):
        raise HTTPException(status_code=403, detail="Access denied")

    path = resolved

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Not a valid directory")

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    directories = []
    for name in entries:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
            try:
                has_children = any(
                    os.path.isdir(os.path.join(full, c))
                    for c in os.listdir(full)
                    if not c.startswith(".")
                )
            except PermissionError:
                has_children = False
            directories.append({"name": name, "path": full, "has_children": has_children})

    parent = os.path.dirname(path.rstrip("/")) or "/"

    return {
        "current_path": path,
        "parent_path": parent if parent != path else None,
        "directories": directories,
    }


@router.post("", response_model=ScanResponse)
def create_scan(
    body: ScanCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a new directory scan."""
    # Input validation: reject null bytes, require absolute path
    source_dir = body.source_dir.strip()
    if "\x00" in source_dir:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not source_dir.startswith("/"):
        raise HTTPException(status_code=400, detail="Source directory must be an absolute path")
    if len(source_dir) > 4096:
        raise HTTPException(status_code=400, detail="Path too long")

    # Create the scan record first so we can return the ID
    scan = Scan(source_dir=source_dir, status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)

    # Run the actual scan in the background
    background_tasks.add_task(_run_scan_with_id, scan.id, source_dir)

    return scan


def _run_scan_with_id(scan_id: int, source_dir: str) -> None:
    """Run the scan using the already-created Scan record."""
    import logging
    import traceback

    logger = logging.getLogger("audiobook_organizer.scan")
    db = None

    try:
        import os
        from datetime import datetime, timezone

        from app.database import SessionLocal
        from app.services.scanner import _find_audiobook_folders, _process_folder

        db = SessionLocal()

        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            logger.error("Scan %d not found in database", scan_id)
            return

        if not os.path.isdir(source_dir):
            scan.status = "failed"
            scan.error_message = f"Directory not found: {source_dir}"
            scan.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.error("Scan %d: directory not found: %s", scan_id, source_dir)
            return

        logger.info("Scan %d: searching for audiobook folders in %s", scan_id, source_dir)

        audiobook_folders = _find_audiobook_folders(source_dir)
        scan.total_folders = len(audiobook_folders)
        db.commit()

        logger.info("Scan %d: found %d audiobook folders", scan_id, len(audiobook_folders))

        for folder_path in audiobook_folders:
            try:
                _process_folder(folder_path, scan, db)
                scan.processed_folders += 1
                db.commit()
                logger.info(
                    "Scan %d: processed %d/%d - %s",
                    scan_id, scan.processed_folders, scan.total_folders,
                    os.path.basename(folder_path),
                )
            except Exception as e:
                from app.models.scan import ScannedFolder

                # Roll back any half-written state from _process_folder
                # before trying to record a skip marker. Otherwise the
                # new ScannedFolder write could collide with dirty rows
                # still in the session.
                try:
                    db.rollback()
                except Exception:
                    logger.warning("Scan %d: rollback after per-folder error failed", scan_id)

                logger.warning("Scan %d: skipped %s: %s", scan_id, folder_path, e)
                folder_name = os.path.basename(folder_path)
                sf = ScannedFolder(
                    scan_id=scan.id,
                    folder_path=folder_path,
                    folder_name=folder_name,
                    status="skipped",
                    error_message=str(e)[:500],
                )
                db.add(sf)
                # scan.processed_folders += 1 needs the Scan row live in
                # this session — refresh in case rollback detached it.
                db.refresh(scan)
                scan.processed_folders += 1
                db.commit()

        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Scan %d: completed. %d folders processed.", scan_id, scan.processed_folders)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Scan %d FAILED: %s\n%s", scan_id, error_msg, traceback.format_exc())

        if db:
            # Discard any half-written state so the status update below
            # isn't stuck behind a dirty transaction.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                from datetime import datetime, timezone

                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan:
                    scan.status = "failed"
                    scan.error_message = error_msg[:500]
                    scan.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                logger.error("Could not update scan %d status in DB", scan_id)
    finally:
        if db:
            db.close()


@router.post("/reimport", response_model=ScanResponse)
def reimport_library(
    body: ScanCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Rebuild the DB from .audiobook-organizer.json sidecars under source_dir.

    For disaster recovery (DB lost) or adopting a previously-organized
    library. The scan that results contains one Book per sidecar found,
    already in the 'copied' state — the user can immediately review,
    re-organize under a different pattern, or purge originals.
    """
    source_dir = body.source_dir.strip()
    if "\x00" in source_dir:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not source_dir.startswith("/"):
        raise HTTPException(status_code=400, detail="Source directory must be an absolute path")
    if len(source_dir) > 4096:
        raise HTTPException(status_code=400, detail="Path too long")
    if not os.path.isdir(source_dir):
        raise HTTPException(status_code=400, detail="Directory not found")

    scan = Scan(
        source_dir=source_dir,
        status="running",
        status_detail="Queued for re-import...",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    background_tasks.add_task(_run_reimport_with_id, scan.id, source_dir)
    return scan


def _run_reimport_with_id(scan_id: int, source_dir: str) -> None:
    """Background task wrapper for the re-import flow."""
    import logging

    from app.database import SessionLocal
    from app.services.reimport import reimport_from_sidecars

    logger = logging.getLogger("audiobook_organizer.reimport")
    db = None
    try:
        db = SessionLocal()
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            logger.error("Re-import: scan %d not found", scan_id)
            return
        reimport_from_sidecars(source_dir, db, scan=scan)
    except Exception:
        logger.error("Re-import %d failed", scan_id, exc_info=True)
    finally:
        if db:
            db.close()


@router.get("", response_model=list[ScanResponse])
def list_scans(db: Session = Depends(get_db)):
    """List all scans."""
    return db.query(Scan).order_by(Scan.created_at.desc()).all()


@router.get("/{scan_id}", response_model=ScanDetailResponse)
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    """Get scan details including scanned folders."""
    scan = (
        db.query(Scan)
        .options(joinedload(Scan.folders))
        .filter(Scan.id == scan_id)
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.delete("/{scan_id}")
def delete_scan(scan_id: int, db: Session = Depends(get_db)):
    """Delete a scan and its scanned folders."""
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.delete(scan)
    db.commit()
    return {"detail": "Scan deleted"}
