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


# Characters that filesystems reject and MUST be replaced.
ILLEGAL_CHARS = re.compile(r'[\\/*?"<>|]')
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


def cleanup_orphan_staging_files(output_root: str) -> int:
    """Remove any leftover `*.audiobook-organizer-staging` files under
    output_root. Called at app startup — if a prior organize was
    interrupted mid-copy (process killed, container restarted), the
    partial staging artifacts would otherwise sit forever.

    Returns the number of files removed. Failures are logged but never
    raised: startup must not be blocked by stray files.
    """
    if not os.path.isdir(output_root):
        return 0

    removed = 0
    for dirpath, _, filenames in os.walk(output_root):
        for name in filenames:
            if name.endswith(STAGING_SUFFIX):
                path = os.path.join(dirpath, name)
                try:
                    os.remove(path)
                    removed += 1
                    logger.info("Cleaned up orphaned staging file: %s", path)
                except OSError as e:
                    logger.warning(
                        "Could not remove orphaned staging file %s: %s", path, e
                    )
    return removed


def sanitize_path_component(name: str) -> str:
    r"""Normalize a string for safe, readable use as a path component.

    Transformations, in order:
      1. Colons → " - "   (e.g. "Black Legion: Warhammer 40,000"
                             → "Black Legion - Warhammer 40,000")
         Filesystems on Windows reject `:`, and even where it's legal
         (Linux), media servers often handle it poorly. A spaced dash
         reads naturally in both folder and file names.
      2. Commas stripped. Cosmetic preference — "40,000" becomes
         "40000", which matches how Audiobookshelf / Plex name things.
      3. Remaining filesystem-illegal chars (`\ / * ? " < > |`) → `_`.
      4. Collapse whitespace runs and trim trailing spaces / dots
         (Windows refuses names ending in "." or " ").
      5. Truncate to MAX_COMPONENT_LENGTH.
    """
    s = name.replace(":", " - ")
    s = s.replace(",", "")
    s = ILLEGAL_CHARS.sub("_", s)
    # Collapse runs of whitespace and adjacent dashes introduced by the
    # substitutions above.
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?:\s*-\s*){2,}", " - ", s)
    s = s.strip(". ")
    if len(s) > MAX_COMPONENT_LENGTH:
        s = s[:MAX_COMPONENT_LENGTH].rstrip(". ")
    return s


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

    # Download cover.jpg if any candidate has a cover URL. Audiobookshelf,
    # Plex, and Jellyfin all auto-detect cover.jpg/folder.jpg next to
    # audio — without this, users have to add covers manually post-
    # organize. Best-effort: failure is logged, not fatal.
    if any(bf.copy_status == "copied" for bf in book.files):
        try:
            _download_cover_art(book, output_dir)
        except Exception:
            logger.warning("Could not download cover for book %s", book.id, exc_info=True)

    # Optionally write corrected tags into the destination files. Off
    # by default — toggled via the `write_tags_on_organize` user
    # setting. We patch only the COPIES we made; the source files are
    # always left untouched as a rollback point.
    if _tag_write_enabled(db) and any(bf.copy_status == "copied" for bf in book.files):
        try:
            _write_tags_to_destinations(book)
        except Exception:
            logger.warning("Tag write-back failed for book %s", book.id, exc_info=True)


COVER_FILENAME = "cover.jpg"


def _tag_write_enabled(db: Session) -> bool:
    """True iff the user has flipped on the `write_tags_on_organize`
    setting. Off by default — tag writes mutate the destination file
    (irreversible without re-organizing) so it must be explicit."""
    from app.models.settings import UserSetting

    row = (
        db.query(UserSetting)
        .filter(UserSetting.key == "write_tags_on_organize")
        .first()
    )
    if row is None or row.value is None:
        return False
    return row.value.strip().lower() in ("1", "true", "yes", "on")


def _write_tags_to_destinations(book) -> None:
    """Apply the book's current metadata to each copied destination."""
    from app.services.tagwriter import write_book_tags

    for bf in book.files:
        if bf.copy_status != "copied" or not bf.destination_path:
            continue
        if not os.path.isfile(bf.destination_path):
            continue
        ok, err = write_book_tags(
            bf.destination_path,
            title=book.title,
            author=book.author,
            album=book.title,  # audiobook convention: album = book title
            year=book.year,
            narrator=book.narrator,
            series=book.series,
            series_position=book.series_position,
        )
        if not ok:
            logger.warning(
                "Tag write failed for %s: %s", bf.destination_path, err,
            )
# Cap cover downloads at 10 MB to defend against a misbehaving provider
# pointing us at a huge image (or a redirect to something else entirely).
_COVER_MAX_BYTES = 10 * 1024 * 1024
_COVER_TIMEOUT = 15.0


def _pick_cover_url(book: Book) -> str | None:
    """Return the best cover URL for a book, or None if none available.

    Preference order:
      1. Applied candidate's cover_url (the metadata the user / auto-
         apply chose).
      2. Highest-ranked non-rejected candidate that has a cover_url.
    """
    applied = None
    fallback = None
    for c in book.candidates:
        if c.rejected:
            continue
        if not c.cover_url:
            continue
        if c.applied and applied is None:
            applied = c.cover_url
        if fallback is None or (c.ranking_score or 0) > 0:
            # We want the highest-ranked fallback. We don't have a
            # sorted list here, but since auto-apply favors highest
            # ranking and applied wins anyway, an applied candidate is
            # the cover we'd pick. For fallback, just take any one.
            fallback = c.cover_url
    return applied or fallback


def _download_cover_art(book: Book, output_dir: str) -> None:
    """Synchronously download the chosen cover URL to <output_dir>/cover.jpg."""
    import httpx

    cover_url = _pick_cover_url(book)
    if not cover_url:
        return

    dest_path = os.path.join(output_dir, COVER_FILENAME)
    # Don't overwrite an existing cover.jpg — the user (or another tool)
    # may have placed one there deliberately.
    if os.path.exists(dest_path):
        return

    staging_path = dest_path + STAGING_SUFFIX
    try:
        with httpx.Client(timeout=_COVER_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(cover_url)
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            if "image" not in content_type and not cover_url.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                logger.warning(
                    "Cover URL %s returned non-image content-type %s; skipping",
                    cover_url, content_type,
                )
                return
            data = resp.content
            if len(data) > _COVER_MAX_BYTES:
                logger.warning(
                    "Cover URL %s is %d bytes (>%d cap); skipping",
                    cover_url, len(data), _COVER_MAX_BYTES,
                )
                return
            with open(staging_path, "wb") as f:
                f.write(data)
        os.replace(staging_path, dest_path)
        logger.info("Wrote cover.jpg for book %s (%d bytes)", book.id, len(data))
    except Exception:
        logger.warning(
            "Failed to download cover for book %s from %s",
            book.id, cover_url, exc_info=True,
        )
        if os.path.exists(staging_path):
            try:
                os.remove(staging_path)
            except OSError:
                pass


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
