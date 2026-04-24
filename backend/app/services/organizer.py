"""File organizer: builds output paths and copies files.

Copies use a two-phase staging flow: each file is first written to
<dest>.staging, verified for size, then atomically renamed into place.
This means other tools (Audiobookshelf, etc.) watching the library
never see a half-written file. If the process dies mid-copy, the only
artifacts left are .staging files, which are easy to identify and
clean up on next run.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.book import Book

logger = logging.getLogger(__name__)


# Characters illegal in file/folder names
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
MAX_COMPONENT_LENGTH = 200

# Suffix applied to in-progress copies before atomic rename.
STAGING_SUFFIX = ".audiobook-organizer-staging"

# Sidecar file written into each organized book folder. Contains enough
# metadata to rebuild the DB from the output tree if needed (disaster
# recovery, library migration).
SIDECAR_FILENAME = ".audiobook-organizer.json"
SIDECAR_SCHEMA_VERSION = 1

# Minimum free space required on the target filesystem before a batch
# organize starts: max(10% of batch size, 1 GiB). Headroom for FS metadata
# and to avoid filling up the disk entirely.
_DISK_HEADROOM_RATIO = 0.10
_DISK_HEADROOM_MIN = 1 * 1024 * 1024 * 1024  # 1 GiB


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when the output filesystem doesn't have enough free space."""

    def __init__(self, required: int, available: int, path: str):
        self.required = required
        self.available = available
        self.path = path
        super().__init__(
            f"Need {required:,} bytes free on {path}, only {available:,} available"
        )


def preflight_disk_space(output_root: str, required_bytes: int) -> None:
    """Check that output_root has enough free space for required_bytes
    plus a safety headroom. Raises InsufficientDiskSpaceError if not.
    """
    os.makedirs(output_root, exist_ok=True)
    usage = shutil.disk_usage(output_root)
    headroom = max(int(required_bytes * _DISK_HEADROOM_RATIO), _DISK_HEADROOM_MIN)
    needed = required_bytes + headroom
    if usage.free < needed:
        raise InsufficientDiskSpaceError(needed, usage.free, output_root)


def sanitize_path_component(name: str) -> str:
    """Remove illegal characters and limit length for a path component."""
    sanitized = ILLEGAL_CHARS.sub("_", name)
    sanitized = sanitized.strip(". ")
    if len(sanitized) > MAX_COMPONENT_LENGTH:
        sanitized = sanitized[:MAX_COMPONENT_LENGTH].rstrip(". ")
    return sanitized


def build_output_path(book: Book, pattern: str, output_root: str) -> str:
    """Build the output directory path for a book using the token pattern.

    Tokens: {Author}, {Series}, {SeriesPosition}, {Title}, {Year},
            {Narrator}, {NarratorBraced}, {Edition}, {EditionBracketed}

    Segments whose only tokens are optional (Series, Year, Narrator, Edition)
    collapse when empty. But "primary" segments — ones anchored on {Author}
    or {Title} — fall back to "Unknown Author" / "Unknown Title" rather than
    being dropped, so missing-metadata books still land in a predictable
    bucket instead of being dumped at the output root.
    """
    narrator_braced = "{" + book.narrator + "}" if book.narrator else None
    edition_bracketed = "[" + book.edition + "]" if book.edition else None

    token_map = {
        "{Author}": book.author,
        "{Series}": book.series,
        "{SeriesPosition}": book.series_position,
        "{Title}": book.title,
        "{Year}": book.year,
        "{Narrator}": book.narrator,
        "{NarratorBraced}": narrator_braced,
        "{Edition}": book.edition,
        "{EditionBracketed}": edition_bracketed,
    }
    # Required-token fallbacks: if the segment is anchored on one of these
    # and the value is missing, substitute the placeholder instead of
    # collapsing the segment.
    required_fallbacks = {
        "{Author}": "Unknown Author",
        "{Title}": "Unknown Title",
    }

    segments = pattern.split("/")
    resolved_segments: list[str] = []

    for segment in segments:
        resolved = segment
        has_value = False
        used_fallback = False

        for token, value in token_map.items():
            if token in resolved:
                if value:
                    resolved = resolved.replace(token, sanitize_path_component(value))
                    has_value = True
                elif token in required_fallbacks:
                    resolved = resolved.replace(token, required_fallbacks[token])
                    used_fallback = True
                else:
                    resolved = resolved.replace(token, "")

        # Clean up the segment: remove dangling separators, empty parens/braces/brackets.
        resolved = re.sub(r"\(\s*\)", "", resolved)
        resolved = re.sub(r"\{\s*\}", "", resolved)
        resolved = re.sub(r"\[\s*\]", "", resolved)
        resolved = re.sub(r"(?:\s*[-–—]\s*){2,}", " - ", resolved)
        resolved = re.sub(r"^\s*[-–—]\s*|\s*[-–—]\s*$", "", resolved)
        resolved = re.sub(r"^Book\s*[-–—]\s*", "", resolved)
        resolved = re.sub(r"\s+", " ", resolved).strip()

        if resolved and (has_value or used_fallback):
            resolved_segments.append(resolved)

    if not resolved_segments:
        resolved_segments = [sanitize_path_component(book.title or "Unknown Title")]

    full_path = os.path.join(output_root, *resolved_segments)

    # Security: ensure the resolved path stays within the output_root
    resolved_full = os.path.realpath(full_path)
    resolved_root = os.path.realpath(output_root)
    if not resolved_full.startswith(resolved_root + os.sep) and resolved_full != resolved_root:
        raise ValueError("Output path escapes output root directory")

    return full_path


def preview_output_path(book: Book, pattern: str, output_root: str) -> str:
    """Preview what the output path would be without copying anything."""
    return build_output_path(book, pattern, output_root)


def organize_book(book: Book, pattern: str, output_root: str, db: Session) -> None:
    """Copy all files for a book into the organized output structure.

    Each file is copied in two phases:
      1. `stage`: copy to `<dest>.audiobook-organizer-staging`, verify size
      2. `commit`: atomic rename to final dest path

    On partial failure, staging files are removed so we don't leak garbage
    into the output library. Successfully committed files are kept (they
    are valid and may have been user-visible already once renamed).

    Writes a `.audiobook-organizer.json` sidecar after all files commit
    so the book can later be rebuilt from the output tree alone.
    """
    output_dir = build_output_path(book, pattern, output_root)
    os.makedirs(output_dir, exist_ok=True)

    book.output_path = output_dir
    book.organize_status = "copying"
    db.commit()

    all_success = True
    for book_file in book.files:
        if not os.path.exists(book_file.original_path):
            logger.warning("Source file missing: %s", book_file.original_path)
            book_file.copy_status = "failed"
            all_success = False
            continue

        dest_path = os.path.join(output_dir, book_file.filename)
        dest_path = _ensure_unique_path(dest_path)
        staging_path = dest_path + STAGING_SUFFIX

        try:
            # Clean up any leftover staging file from a prior crashed run.
            if os.path.exists(staging_path):
                try:
                    os.remove(staging_path)
                except OSError:
                    pass

            # Phase 1: copy to staging path.
            shutil.copy2(book_file.original_path, staging_path)

            # Verify size before commit — catches truncated copies from
            # disk-full, interrupted network shares, etc.
            src_size = os.path.getsize(book_file.original_path)
            staged_size = os.path.getsize(staging_path)
            if src_size != staged_size:
                logger.error(
                    "Copy size mismatch for %s: src=%d staged=%d — removing partial copy",
                    book_file.original_path,
                    src_size,
                    staged_size,
                )
                try:
                    os.remove(staging_path)
                except OSError:
                    pass
                book_file.copy_status = "failed"
                all_success = False
                continue

            # Phase 2: atomic rename into place. os.replace is atomic on
            # the same filesystem (which .staging guarantees since it's
            # a sibling path).
            os.replace(staging_path, dest_path)

            book_file.destination_path = dest_path
            book_file.file_size = src_size
            book_file.copy_status = "copied"

        except Exception:
            logger.error("Failed to copy %s", book_file.original_path, exc_info=True)
            # Best-effort cleanup of staging artifact.
            if os.path.exists(staging_path):
                try:
                    os.remove(staging_path)
                except OSError:
                    pass
            book_file.copy_status = "failed"
            all_success = False

    book.organize_status = "copied" if all_success else "failed"
    db.commit()

    # Drop provenance sidecar — always, even on partial failure, so the
    # user can still re-import whatever did land.
    if any(bf.copy_status == "copied" for bf in book.files):
        try:
            _write_sidecar(book, output_dir)
        except Exception:
            logger.warning("Could not write sidecar for book %s", book.id, exc_info=True)


def _write_sidecar(book: Book, output_dir: str) -> None:
    """Write the .audiobook-organizer.json provenance sidecar.

    Kept tolerant of missing fields so it works even if the book was
    never auto-looked-up or manually edited.
    """
    sidecar_path = os.path.join(output_dir, SIDECAR_FILENAME)

    source_folder = None
    if book.scanned_folder:
        source_folder = book.scanned_folder.folder_path

    files_data = []
    for bf in book.files:
        if bf.copy_status != "copied":
            continue
        files_data.append({
            "filename": bf.filename,
            "size": bf.file_size,
            "original_path": bf.original_path,
            "tag_title": bf.tag_title,
            "tag_author": bf.tag_author,
            "tag_album": bf.tag_album,
            "tag_year": bf.tag_year,
            "tag_narrator": bf.tag_narrator,
        })

    data = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "organized_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": source_folder,
        "book": {
            "title": book.title,
            "author": book.author,
            "series": book.series,
            "series_position": book.series_position,
            "year": book.year,
            "narrator": book.narrator,
            "edition": book.edition,
            "source": book.source,
            "confidence": book.confidence,
            "is_confirmed": book.is_confirmed,
        },
        "files": files_data,
    }

    # Write via a sibling .tmp then rename so a crash doesn't leave a
    # truncated/corrupt sidecar.
    tmp = sidecar_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, sidecar_path)


def _ensure_unique_path(path: str) -> str:
    """If path exists, append (1), (2), etc. to make it unique."""
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base} ({counter}){ext}"):
        counter += 1
    return f"{base} ({counter}){ext}"
