"""Directory scanner for audiobook discovery.

Walks a source directory, finds folders containing audio files,
reads tags, parses names, and creates database records.
"""

import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile
from app.models.scan import Scan, ScannedFolder
from app.services.metadata import AUDIO_EXTENSIONS, is_audio_file, read_tags
from app.services.parser import ParsedMetadata, merge_with_tags, parse_folder_path

MAX_DEPTH = 6


def scan_directory(source_dir: str, db: Session) -> Scan:
    """Scan a directory for audiobooks. Creates Scan, ScannedFolder, Book, and BookFile records.

    Returns the Scan record (status will be 'completed' or 'failed').
    """
    scan = Scan(source_dir=source_dir, status="running")
    db.add(scan)
    db.commit()
    db.refresh(scan)

    try:
        if not os.path.isdir(source_dir):
            scan.status = "failed"
            scan.error_message = f"Directory not found: {source_dir}"
            db.commit()
            return scan

        audiobook_folders = _find_audiobook_folders(source_dir)
        scan.total_folders = len(audiobook_folders)
        db.commit()

        for folder_path in audiobook_folders:
            try:
                _process_folder(folder_path, scan, db)
                scan.processed_folders += 1
                db.commit()
            except Exception as e:
                # Record error but continue scanning other folders
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
        scan.status = "failed"
        scan.error_message = str(e)
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    return scan


def _find_audiobook_folders(source_dir: str) -> list[str]:
    """Walk source_dir and find all folders containing audio files.

    The deepest folder containing audio files is considered the audiobook folder.
    """
    audiobook_folders: list[str] = []
    source_depth = source_dir.rstrip(os.sep).count(os.sep)

    for dirpath, dirnames, filenames in os.walk(source_dir):
        # Enforce depth limit
        current_depth = dirpath.count(os.sep) - source_depth
        if current_depth >= MAX_DEPTH:
            dirnames.clear()
            continue

        # Check if this folder contains audio files
        audio_files = [f for f in filenames if is_audio_file(f)]
        if audio_files:
            audiobook_folders.append(dirpath)

    # Remove parent folders if a child folder also has audio files
    # (prefer the deepest folder)
    filtered = []
    sorted_folders = sorted(audiobook_folders)
    for folder in sorted_folders:
        # Check if any already-added folder is a parent of this one
        is_child_of_existing = False
        parents_to_remove = []
        for existing in filtered:
            normalized_existing = existing.rstrip(os.sep) + os.sep
            if folder.startswith(normalized_existing):
                is_child_of_existing = True
                # This folder is deeper - remove parent and add this one
                parents_to_remove.append(existing)

        for parent in parents_to_remove:
            filtered.remove(parent)
        filtered.append(folder)

    return filtered


def _process_folder(folder_path: str, scan: Scan, db: Session) -> None:
    """Process a single audiobook folder: parse name, read tags, create records."""
    folder_name = os.path.basename(folder_path)

    # Create ScannedFolder record
    scanned_folder = ScannedFolder(
        scan_id=scan.id,
        folder_path=folder_path,
        folder_name=folder_name,
        status="pending",
    )
    db.add(scanned_folder)
    db.flush()

    # Find all audio files
    audio_files = []
    for filename in sorted(os.listdir(folder_path)):
        filepath = os.path.join(folder_path, filename)
        if os.path.isfile(filepath) and is_audio_file(filepath):
            audio_files.append((filepath, filename))

    if not audio_files:
        scanned_folder.status = "skipped"
        scanned_folder.error_message = "No audio files found"
        return

    # Parse folder name
    parsed = parse_folder_path(folder_path)

    # Read tags from first audio file to get representative metadata
    first_tags: dict[str, str | None] = {}
    if audio_files:
        first_tags = read_tags(audio_files[0][0])

    # Merge parsed + tag data
    parsed = merge_with_tags(parsed, first_tags)

    # Create Book record
    book = Book(
        scanned_folder_id=scanned_folder.id,
        title=parsed.title,
        author=parsed.author,
        series=parsed.series,
        series_position=parsed.series_position,
        year=parsed.year,
        source=parsed.source,
        confidence=parsed.confidence,
    )
    db.add(book)
    db.flush()

    # Create BookFile records
    for filepath, filename in audio_files:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        file_size = os.path.getsize(filepath)
        tags = read_tags(filepath) if filepath != audio_files[0][0] else first_tags

        book_file = BookFile(
            book_id=book.id,
            original_path=filepath,
            filename=filename,
            file_size=file_size,
            file_format=ext,
            tag_title=tags.get("title"),
            tag_author=tags.get("author"),
            tag_album=tags.get("album"),
            tag_year=tags.get("year"),
            tag_track=tags.get("track"),
            tag_narrator=tags.get("narrator"),
        )
        db.add(book_file)

    # Update narrator from tags if available
    if first_tags.get("narrator") and not book.narrator:
        book.narrator = first_tags["narrator"]

    scanned_folder.status = "parsed"
