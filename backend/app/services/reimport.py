"""Rebuild the DB from `.audiobook-organizer.json` sidecars.

Walks an organized library directory, finds sidecar files written by
the organizer, and reconstructs Scan / ScannedFolder / Book / BookFile
records so the user can resume management without re-scanning and
re-looking-up everything.

Intended uses:
 - Disaster recovery: DB volume lost but organized output survived.
 - Migration: move the organized tree to a new instance.
 - Library adoption: bring an already-organized library under
   Audiobook Organizer control.

A sidecar file is trusted as provenance — we do not re-parse folder
names or re-read tags. Files that are listed in the sidecar but no
longer exist on disk are recorded with copy_status="missing" so the
user can see the divergence.
"""

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile
from app.models.scan import Scan, ScannedFolder
from app.services.organizer import SIDECAR_FILENAME, SIDECAR_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def reimport_from_sidecars(
    output_dir: str,
    db: Session,
    scan: Scan | None = None,
) -> Scan:
    """Walk output_dir, rebuild DB records from sidecars. Returns the
    Scan record (status "completed" or "failed").

    If `scan` is provided, that record is populated. Otherwise a new
    one is created with source_dir=output_dir. status_detail tracks
    progress so the existing UI picks it up like a normal scan.
    """
    if scan is None:
        scan = Scan(
            source_dir=output_dir,
            status="running",
            status_detail="Discovering sidecars...",
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
    else:
        scan.status = "running"
        scan.status_detail = "Discovering sidecars..."
        db.commit()

    try:
        if not os.path.isdir(output_dir):
            scan.status = "failed"
            scan.error_message = f"Directory not found: {output_dir}"
            scan.completed_at = datetime.now(timezone.utc)
            db.commit()
            return scan

        sidecar_paths = _find_sidecars(output_dir)
        scan.total_folders = len(sidecar_paths)
        scan.status_detail = f"Re-importing {len(sidecar_paths)} books..."
        db.commit()

        for idx, sidecar_path in enumerate(sidecar_paths):
            try:
                _reimport_one(sidecar_path, scan, db)
                scan.processed_folders += 1
                scan.status_detail = f"Re-imported {idx + 1}/{len(sidecar_paths)}"
                db.commit()
            except Exception as e:
                logger.warning(
                    "Failed to reimport sidecar %s: %s",
                    sidecar_path,
                    type(e).__name__,
                    exc_info=True,
                )
                folder_path = os.path.dirname(sidecar_path)
                sf = ScannedFolder(
                    scan_id=scan.id,
                    folder_path=folder_path,
                    folder_name=os.path.basename(folder_path),
                    status="skipped",
                    error_message=f"{type(e).__name__}: {str(e)[:300]}",
                )
                db.add(sf)
                scan.processed_folders += 1
                db.commit()

        scan.status = "completed"
        scan.status_detail = None
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        scan.status = "failed"
        scan.error_message = f"{type(e).__name__}: {str(e)[:500]}"
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    return scan


def _find_sidecars(root: str) -> list[str]:
    """Walk root, return all sidecar file paths found."""
    results: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        if SIDECAR_FILENAME in filenames:
            results.append(os.path.join(dirpath, SIDECAR_FILENAME))
    return sorted(results)


def _reimport_one(sidecar_path: str, scan: Scan, db: Session) -> None:
    """Reconstruct records for a single book from one sidecar."""
    with open(sidecar_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("schema_version")
    if version != SIDECAR_SCHEMA_VERSION:
        raise ValueError(f"Unsupported sidecar schema version: {version}")

    book_data = data.get("book") or {}
    files_data = data.get("files") or []
    source_folder = data.get("source_folder")

    output_dir = os.path.dirname(sidecar_path)

    # Use the original source folder if recorded, else fall back to the
    # sidecar's directory (the organized location).
    folder_path = source_folder or output_dir
    folder_name = os.path.basename(folder_path) or os.path.basename(output_dir)

    scanned_folder = ScannedFolder(
        scan_id=scan.id,
        folder_path=folder_path,
        folder_name=folder_name,
        status="reimported",
    )
    db.add(scanned_folder)
    db.flush()

    book = Book(
        scanned_folder_id=scanned_folder.id,
        title=book_data.get("title"),
        author=book_data.get("author"),
        series=book_data.get("series"),
        series_position=book_data.get("series_position"),
        year=book_data.get("year"),
        narrator=book_data.get("narrator"),
        edition=book_data.get("edition"),
        source=book_data.get("source") or "reimport",
        confidence=book_data.get("confidence") or 0.0,
        is_confirmed=bool(book_data.get("is_confirmed")),
        organize_status="copied",
        output_path=output_dir,
    )
    db.add(book)
    db.flush()

    for file_entry in files_data:
        filename = file_entry.get("filename")
        if not filename:
            continue

        dest_path = os.path.join(output_dir, filename)
        dest_exists = os.path.exists(dest_path)

        bf = BookFile(
            book_id=book.id,
            original_path=file_entry.get("original_path") or dest_path,
            filename=filename,
            file_size=file_entry.get("size") or 0,
            file_format=os.path.splitext(filename)[1].lower().lstrip("."),
            destination_path=dest_path if dest_exists else None,
            copy_status="copied" if dest_exists else "missing",
            tag_title=file_entry.get("tag_title"),
            tag_author=file_entry.get("tag_author"),
            tag_album=file_entry.get("tag_album"),
            tag_year=file_entry.get("tag_year"),
            tag_narrator=file_entry.get("tag_narrator"),
        )
        db.add(bf)

    db.flush()
