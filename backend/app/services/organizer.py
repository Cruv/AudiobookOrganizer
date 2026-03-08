"""File organizer: builds output paths and copies files."""

import os
import re
import shutil

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile


# Characters illegal in file/folder names
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
MAX_COMPONENT_LENGTH = 200


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
    Segments containing only unresolved tokens are collapsed (removed).
    """
    # {NarratorBraced} wraps narrator in curly braces for Audiobookshelf compatibility
    narrator_braced = "{" + book.narrator + "}" if book.narrator else None
    # {EditionBracketed} wraps edition in brackets: [Graphic Audio]
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

    segments = pattern.split("/")
    resolved_segments: list[str] = []

    for segment in segments:
        resolved = segment
        has_value = False

        for token, value in token_map.items():
            if token in resolved:
                if value:
                    resolved = resolved.replace(token, sanitize_path_component(value))
                    has_value = True
                else:
                    resolved = resolved.replace(token, "")

        # Clean up the segment: remove dangling separators, empty parens/braces/brackets, etc.
        resolved = re.sub(r"\(\s*\)", "", resolved)
        resolved = re.sub(r"\{\s*\}", "", resolved)
        resolved = re.sub(r"\[\s*\]", "", resolved)
        # Collapse consecutive dashes (e.g. "Book - - Title" → "Book - Title")
        resolved = re.sub(r"(?:\s*[-–—]\s*){2,}", " - ", resolved)
        resolved = re.sub(r"^\s*[-–—]\s*|\s*[-–—]\s*$", "", resolved)
        # Remove "Book" prefix when no series position follows it
        resolved = re.sub(r"^Book\s*[-–—]\s*", "", resolved)
        resolved = re.sub(r"\s+", " ", resolved).strip()

        # Only include segment if it has meaningful content
        if resolved and has_value:
            resolved_segments.append(resolved)

    if not resolved_segments:
        # Fallback: use title or "Unknown"
        fallback = sanitize_path_component(book.title or "Unknown")
        resolved_segments = [fallback]

    return os.path.join(output_root, *resolved_segments)


def preview_output_path(book: Book, pattern: str, output_root: str) -> str:
    """Preview what the output path would be without copying anything."""
    return build_output_path(book, pattern, output_root)


def organize_book(book: Book, pattern: str, output_root: str, db: Session) -> None:
    """Copy all files for a book to the organized output structure."""
    output_dir = build_output_path(book, pattern, output_root)
    os.makedirs(output_dir, exist_ok=True)

    book.output_path = output_dir
    book.organize_status = "copying"
    db.commit()

    all_success = True
    for book_file in book.files:
        try:
            dest_path = os.path.join(output_dir, book_file.filename)
            dest_path = _ensure_unique_path(dest_path)

            shutil.copy2(book_file.original_path, dest_path)

            book_file.destination_path = dest_path
            book_file.copy_status = "copied"
            db.commit()
        except Exception:
            book_file.copy_status = "failed"
            all_success = False
            db.commit()

    book.organize_status = "copied" if all_success else "failed"
    db.commit()


def _ensure_unique_path(path: str) -> str:
    """If path exists, append (1), (2), etc. to make it unique."""
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base} ({counter}){ext}"):
        counter += 1
    return f"{base} ({counter}){ext}"
