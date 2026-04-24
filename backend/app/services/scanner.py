"""Directory scanner for audiobook discovery.

Walks a source directory, finds folders containing audio files,
reads tags, parses names, and creates database records.
Performs auto-lookup for low-confidence books.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile
from app.models.scan import Scan, ScannedFolder
from app.models.settings import UserSetting
from app.services.metadata import is_audio_file, read_folder_tags, read_tags
from app.services.parser import (
    ParsedMetadata,
    auto_match_score,
    clean_narrator,
    detect_edition,
    merge_with_tags,
    parse_folder_path,
)

logger = logging.getLogger(__name__)

MAX_DEPTH = 6

# Regex for leaf folders that indicate multi-part audiobooks
MULTI_PART_LEAF_PATTERN = re.compile(
    r"^(?:Part|Pt|Disc|CD|Disk)\s*\d+", re.IGNORECASE
)
# Local parses with confidence >= this skip the (slow) online lookup phase.
# Online provider confidence is capped at 0.95, so 0.90 is the right bar:
# strong-but-not-perfect local parses still get a chance to be improved upstream.
AUTO_LOOKUP_CONFIDENCE_THRESHOLD = 0.90
# Minimum auto_match_score before a lookup result is automatically applied.
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

        scan.status_detail = "Discovering folders..."
        db.commit()

        audiobook_folders = _find_audiobook_folders(source_dir)
        scan.total_folders = len(audiobook_folders)
        scan.status_detail = f"Processing {len(audiobook_folders)} folders..."
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

        # Group multi-part folders (Part 01, Part 02, etc.) into single books
        scan.status_detail = "Grouping multi-part audiobooks..."
        db.commit()
        _group_multipart_books(scan, db)

        # Carry forward manual edits / confirmations from prior scans
        # of folders at the same path (basic re-scan idempotency).
        scan.status_detail = "Carrying forward manual edits..."
        db.commit()
        _carry_forward_manual_edits(scan, db)

        # Detect duplicate books (same title+author, different paths)
        scan.status_detail = "Checking for duplicates..."
        db.commit()
        _detect_duplicates(scan, db)

        # Refresh lookup list after grouping and carry-forward. Confirmed
        # books (is_confirmed=True) are skipped — user already reviewed them.
        books_for_lookup = (
            db.query(Book)
            .join(ScannedFolder)
            .filter(
                ScannedFolder.scan_id == scan.id,
                Book.confidence < AUTO_LOOKUP_CONFIDENCE_THRESHOLD,
                Book.is_confirmed.is_(False),
            )
            .all()
        )

        # Auto-lookup for low-confidence books
        if books_for_lookup:
            scan.status_detail = f"Looking up {len(books_for_lookup)} books online..."
            db.commit()
            try:
                asyncio.run(_auto_lookup_books(books_for_lookup, scan, db))
            except RuntimeError:
                # Already in an event loop (e.g. during tests)
                pass

        scan.status = "completed"
        scan.status_detail = None
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        scan.status = "failed"
        scan.error_message = str(e)
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()

    return scan


async def _auto_lookup_books(books: list[Book], scan: Scan, db: Session) -> None:
    """Auto-lookup metadata for all books and apply best matches.

    Records any per-book lookup failure as book.lookup_error so the Review
    page can surface it to the user rather than silently losing the book.
    """
    from app.services.lookup import lookup_book
    from app.services.parser import clean_narrator, clean_query

    api_key_setting = db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    api_key = api_key_setting.value if api_key_setting else None

    total = len(books)
    for idx, book in enumerate(books):
        try:
            # Clear any stale error from a previous run
            book.lookup_error = None

            query = clean_query(book.title, book.author)
            if not query or len(query) < 3:
                book.lookup_error = "Query too short to look up"
                db.commit()
                continue

            scan.status_detail = f"Looking up {idx + 1}/{total}: {query[:50]}"
            db.commit()

            logger.info("Auto-lookup %d/%d: %s", idx + 1, total, query)

            results = await lookup_book(query, book.author, api_key, db)
            if not results:
                book.lookup_error = "No matches from any provider"
                db.commit()
                await asyncio.sleep(0.3)
                continue

            # Score each result against parsed data
            parsed = ParsedMetadata(
                title=book.title,
                author=book.author,
                series=book.series,
                series_position=book.series_position,
                year=book.year,
                narrator=book.narrator,
            )

            best_score = 0.0
            best_result = None
            for result in results:
                score = auto_match_score(
                    parsed,
                    result.title,
                    result.author,
                    result_series=result.series,
                    result_year=result.year,
                    result_narrator=result.narrator,
                )
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
                if best_result.narrator and not book.narrator:
                    book.narrator = clean_narrator(best_result.narrator, book.edition)
                book.source = f"auto:{best_result.provider}"
                book.confidence = max(book.confidence, min(best_result.confidence, 0.95))
            else:
                # Don't apply, but record why for user visibility
                book.lookup_error = (
                    f"Best match score {best_score:.2f} below threshold "
                    f"{AUTO_APPLY_MATCH_THRESHOLD:.2f}"
                )
            db.commit()

            await asyncio.sleep(0.3)

        except Exception as e:
            logger.warning(
                "Auto-lookup failed for book %s: %s",
                book.id,
                type(e).__name__,
                exc_info=True,
            )
            try:
                book.lookup_error = f"{type(e).__name__}: {str(e)[:200]}"
                db.commit()
            except Exception:
                db.rollback()
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
        parents_to_remove = []
        for existing in filtered:
            normalized_existing = existing.rstrip(os.sep) + os.sep
            if folder.startswith(normalized_existing):
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

    # Clean and normalize narrator (reject publishers, strip junk, normalize GA casts)
    parsed.narrator = clean_narrator(parsed.narrator, edition)

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


def _group_multipart_books(scan: Scan, db: Session) -> None:
    """Group multi-part audiobook folders into single book records.

    Finds sibling folders like "Part 01", "Part 02" etc. under the same
    parent directory and merges them: moves all BookFiles to the first
    Book, then deletes the duplicate Book records.

    Siblings are only merged if they also share a fuzzy title/author —
    prevents accidentally merging two unrelated multi-part books that
    happen to share a parent directory.
    """
    from collections import defaultdict

    from sqlalchemy.orm import joinedload

    from app.services.parser import similarity

    books = (
        db.query(Book)
        .join(ScannedFolder)
        .options(joinedload(Book.scanned_folder), joinedload(Book.files))
        .filter(ScannedFolder.scan_id == scan.id)
        .all()
    )

    # Group by parent directory
    parent_groups: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        if not book.scanned_folder:
            continue
        folder_path = book.scanned_folder.folder_path
        leaf_name = os.path.basename(folder_path)
        if MULTI_PART_LEAF_PATTERN.match(leaf_name):
            parent_dir = os.path.dirname(folder_path)
            parent_groups[parent_dir].append(book)

    # Merge groups with 2+ parts
    for parent_dir, group_books in parent_groups.items():
        if len(group_books) < 2:
            continue

        group_books.sort(key=lambda b: b.scanned_folder.folder_name)

        # Cluster siblings by content similarity (title + author) so two
        # different multi-part books under the same parent don't get merged.
        clusters: list[list[Book]] = []
        for book in group_books:
            placed = False
            for cluster in clusters:
                head = cluster[0]
                title_sim = similarity(book.title, head.title)
                author_sim = similarity(book.author, head.author) if (book.author and head.author) else 1.0
                # Require strong title match; author match if both have one.
                if title_sim >= 0.80 and author_sim >= 0.70:
                    cluster.append(book)
                    placed = True
                    break
            if not placed:
                clusters.append([book])

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            primary = cluster[0]
            for secondary in cluster[1:]:
                for bf in secondary.files:
                    bf.book_id = primary.id
                db.flush()

                secondary_folder = secondary.scanned_folder
                db.delete(secondary)
                if secondary_folder:
                    secondary_folder.status = "merged"

            logger.info(
                "Grouped %d parts into '%s' by %s (parent: %s)",
                len(cluster),
                primary.title,
                primary.author,
                os.path.basename(parent_dir),
            )

    db.commit()


def _carry_forward_manual_edits(scan: Scan, db: Session) -> None:
    """Carry is_confirmed + manual edits from the newest prior Book at the
    same folder_path forward into this scan.

    Prior scans of the same directory produce their own Book rows. Without
    this pass, a user who manually fixed 50 books would lose those edits
    on the next scan. We look up the most recent Book for each folder_path
    in this scan (excluding books in *this* scan) and, if its source
    indicates user intervention, copy its fields over.
    """
    from sqlalchemy.orm import joinedload

    current = (
        db.query(Book)
        .join(ScannedFolder)
        .options(joinedload(Book.scanned_folder))
        .filter(ScannedFolder.scan_id == scan.id)
        .all()
    )

    carried = 0
    for book in current:
        if not book.scanned_folder:
            continue
        folder_path = book.scanned_folder.folder_path

        prior = (
            db.query(Book)
            .join(ScannedFolder)
            .filter(
                ScannedFolder.folder_path == folder_path,
                ScannedFolder.scan_id != scan.id,
            )
            .order_by(Book.updated_at.desc())
            .first()
        )
        if not prior:
            continue

        # Only carry forward if the user actually touched this book.
        user_touched = prior.is_confirmed or prior.source in ("manual", "user")
        if not user_touched:
            continue

        # Preserve the user's work.
        if prior.title:
            book.title = prior.title
        if prior.author:
            book.author = prior.author
        if prior.series:
            book.series = prior.series
        if prior.series_position:
            book.series_position = prior.series_position
        if prior.year:
            book.year = prior.year
        if prior.narrator:
            book.narrator = prior.narrator
        if prior.edition:
            book.edition = prior.edition
        book.is_confirmed = prior.is_confirmed
        book.source = prior.source
        book.confidence = max(book.confidence, prior.confidence)
        carried += 1

    if carried:
        db.commit()
        logger.info("Carried forward manual edits for %d book(s) from prior scans", carried)


def _detect_duplicates(scan: Scan, db: Session) -> None:
    """Detect books with the same title+author but different editions/paths.

    Logs warnings for potential duplicates so users can review them.
    Does not auto-merge since different editions (GA vs standard) are
    intentionally kept separate.
    """
    from collections import defaultdict

    from sqlalchemy.orm import joinedload

    books = (
        db.query(Book)
        .join(ScannedFolder)
        .options(joinedload(Book.scanned_folder))
        .filter(ScannedFolder.scan_id == scan.id)
        .all()
    )

    # Group by normalized title+author
    title_groups: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        if not book.title:
            continue
        key = re.sub(r"[^a-z0-9]", "", (book.title or "").lower())
        if book.author:
            key += "|" + re.sub(r"[^a-z0-9]", "", book.author.lower())
        title_groups[key].append(book)

    dup_count = 0
    for key, group in title_groups.items():
        if len(group) < 2:
            continue

        # Check if they're actually different editions (GA vs standard)
        editions = {b.edition or "standard" for b in group}
        if len(editions) > 1:
            # Different editions — expected, just log
            logger.info(
                "Multiple editions of '%s': %s",
                group[0].title,
                ", ".join(sorted(editions)),
            )
            continue

        # Same edition, same title — true duplicates
        dup_count += len(group) - 1
        paths = [b.scanned_folder.folder_path if b.scanned_folder else "?" for b in group]
        logger.warning(
            "Duplicate detected: '%s' by %s found in %d locations: %s",
            group[0].title,
            group[0].author,
            len(group),
            "; ".join(paths),
        )

    if dup_count:
        logger.info("Found %d potential duplicate books", dup_count)
