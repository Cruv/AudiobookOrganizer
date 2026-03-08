import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.scan import Scan
from app.schemas.scan import ScanCreate, ScanDetailResponse, ScanResponse
from app.services.scanner import scan_directory

router = APIRouter(prefix="/api/scans", tags=["scans"])

browse_router = APIRouter(prefix="/api", tags=["browse"])


@browse_router.get("/browse")
def browse_directory(path: str = Query(default="/")):
    """List subdirectories at a given path for the directory browser."""
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a valid directory: {path}")

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


def _run_scan(source_dir: str) -> None:
    """Run scan in a background thread with its own DB session."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        scan_directory(source_dir, db)
    finally:
        db.close()


@router.post("", response_model=ScanResponse)
def create_scan(
    body: ScanCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a new directory scan."""
    # Create the scan record first so we can return the ID
    scan = Scan(source_dir=body.source_dir, status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)

    # Run the actual scan in the background
    background_tasks.add_task(_run_scan_with_id, scan.id, body.source_dir)

    return scan


def _run_scan_with_id(scan_id: int, source_dir: str) -> None:
    """Run the scan using the already-created Scan record."""
    from app.database import SessionLocal
    from app.services.metadata import is_audio_file, read_tags
    from app.services.parser import merge_with_tags, parse_folder_path
    from app.services.scanner import _find_audiobook_folders, _process_folder

    import os
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        scan = db.query(Scan).get(scan_id)
        if not scan:
            return

        if not os.path.isdir(source_dir):
            scan.status = "failed"
            scan.error_message = f"Directory not found: {source_dir}"
            scan.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        audiobook_folders = _find_audiobook_folders(source_dir)
        scan.total_folders = len(audiobook_folders)
        db.commit()

        for folder_path in audiobook_folders:
            try:
                _process_folder(folder_path, scan, db)
                scan.processed_folders += 1
                db.commit()
            except Exception as e:
                from app.models.scan import ScannedFolder

                folder_name = os.path.basename(folder_path)
                sf = ScannedFolder(
                    scan_id=scan.id,
                    folder_path=folder_path,
                    folder_name=folder_name,
                    status="skipped",
                    error_message=str(e),
                )
                db.add(sf)
                scan.processed_folders += 1
                db.commit()

        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        scan = db.query(Scan).get(scan_id)
        if scan:
            scan.status = "failed"
            scan.error_message = str(e)
            scan.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
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
