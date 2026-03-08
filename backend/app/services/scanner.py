"""Directory scanner for audiobook discovery.

Walks a source directory, finds folders containing audio files,
reads tags, parses names, and creates database records.
Performs auto-lookup for low-confidence books.
"""

import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile
from app.models.scan import Scan, ScannedFolder
from app.models.settings import UserSetting
from app.services.metadata import AUDIO_EXTENSIONS, is_audio_file, read_folder_tags, read_tags
from app.services.parser import ParsedMetadata, auto_match_score, detect_edition, merge_with_tags, parse_folder_path

MAX_DEPTH = 6
AUTO_LOOKUP_CONFIDENCE_THRESHOLD = 0.70
AUTO_APPLY_MATCH_THRESHOLD = 0.85


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

        books_for_lookup: list[Book] = []

        for folder_path in audiobook_folders:
            try:
                book = _process_folder(folder_path, scan, db)
                scan.processed_folders += 1
                db.commit()
                if book and book.confidence < AUTO_LOOKUP_CONFIDENCE_THRESHOLD:
                    books_for_lookup.append(book)
            except Exception as e:
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

        # Auto-lookup for low-confidence books
        if books_for_lookup:
            try:
                asyncio.run(_auto_lookup_books(books_for_lookup, db))
            except RuntimeError:
                # Already in an event loop (e.g. during tests)
                pass

        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        scan.status = "failed"
        scan.error_message = str(e)
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    return scan


async def _auto_lookup_books(books: list[Book], db: Session) -> None:
    """Auto-lookup metadata for low-confidence books and apply best matches."""
    from app.services.lookup import lookup_book
    from app.services.parser import clean_query

    api_key_setting = db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    api_key = api_key_setting.value if api_key_setting else None

    for book in books:
        try:
            query = clean_query(book.title, book.author)
            if not query or len(query) < 3:
                continue

            results = await lookup_book(query, book.author, api_key, db)
            if not results:
                continue

            # Score each result against parsed data
            parsed = ParsedMetadata(
                title=book.title,
                author=book.author,
                series=book.series,
                series_position=book.series_position,
                year=book.year,
            )

            best_score = 0.0
            best_result = None
            for result in results:
                score = auto_match_score(parsed, result.title, result.author)
                if score > best_score:
                    best_score = score
                    best_result = result

            # Auto-apply if match is strong enough
            if best_result and best_score >= AUTO_APPLY_MATCH_THRESHOLD:
                if best_result.title:
                    book.title = best_result.title
                if best_result.author:
                    book.author = best_result.author
                if best_result.series and not book.series:
                    book.series = best_result.series
                if best_result.series_position and not book.series_position:
                    book.series_position = best_result.series_position
                if best_result.year and not book.year:
                    book.year = best_result.year
                book.source = f"auto:{best_result.provider}"
                book.confidence = min(book.confidence + 0.20, 0.95)
                db.commit()

        except Exception:
            continue


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


def _process_folder(folder_path: str, scan: Scan, db: Session) -> Book | None:
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
        return None

    # Parse folder name
    parsed = parse_folder_path(folder_path)

    # Read consensus tags from multiple files
    consensus_tags = read_folder_tags(folder_path)

    # Detect edition (Graphic Audio, etc.) before merging tags
    edition = detect_edition(folder_path, folder_name, consensus_tags)

    # Merge parsed + consensus tag data
    parsed = merge_with_tags(parsed, consensus_tags)

    # Apply detected edition
    if edition:
        parsed.edition = edition

    # Normalize long GA narrator lists to "Full Cast"
    if edition == "Graphic Audio" and parsed.narrator:
        names = [n.strip() for n in parsed.narrator.split(",") if n.strip()]
        if len(names) >= 4 or "Full Cast" in names:
            parsed.narrator = "Full Cast"

    # Create Book record
    book = Book(
        scanned_folder_id=scanned_folder.id,
        title=parsed.title,
        author=parsed.author,
        series=parsed.series,
        series_position=parsed.series_position,
        year=parsed.year,
        narrator=parsed.narrator,
        edition=parsed.edition,
        source=parsed.source,
        confidence=parsed.confidence,
    )
    db.add(book)
    db.flush()

    # Create BookFile records (read individual tags for per-file data)
    first_tags = read_tags(audio_files[0][0])
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

    scanned_folder.status = "parsed"
    return book
