"""Safe deletion of original audiobook files after organization."""

import logging
import os

from sqlalchemy.orm import Session

from app.models.book import Book
from app.schemas.organize import PurgeResultItem, PurgeVerifyItem

logger = logging.getLogger(__name__)


def verify_book(book: Book) -> PurgeVerifyItem:
    """Verify that all destination files exist and match original sizes.

    If the original path still exists, cross-check dest size against a
    fresh read of the original's on-disk size rather than trusting the
    stored BookFile.file_size (which can be stale or None).
    """
    missing_files: list[str] = []
    total_size = 0

    for bf in book.files:
        # Guard: file_size can legitimately be None on older DB rows.
        original_size = bf.file_size or 0
        if os.path.exists(bf.original_path):
            try:
                fresh_original_size = os.path.getsize(bf.original_path)
                original_size = fresh_original_size
            except OSError:
                pass
        total_size += original_size

        if bf.copy_status != "copied":
            missing_files.append(f"{bf.filename}: not copied (status={bf.copy_status})")
            continue
        if not bf.destination_path:
            missing_files.append(f"{bf.filename}: no destination path")
            continue
        if not os.path.exists(bf.destination_path):
            missing_files.append(f"{bf.filename}: destination file missing")
            continue
        try:
            dest_size = os.path.getsize(bf.destination_path)
        except OSError as e:
            missing_files.append(f"{bf.filename}: cannot stat destination: {e}")
            continue
        if original_size and dest_size != original_size:
            missing_files.append(
                f"{bf.filename}: size mismatch (original={original_size}, dest={dest_size})"
            )

    return PurgeVerifyItem(
        book_id=book.id,
        title=book.title,
        author=book.author,
        verified=len(missing_files) == 0,
        missing_files=missing_files,
        total_size=total_size,
    )


def purge_book(book: Book, db: Session) -> PurgeResultItem:
    """Delete original files for a book after verification passes."""
    # Verify first
    verification = verify_book(book)
    if not verification.verified:
        return PurgeResultItem(
            book_id=book.id,
            success=False,
            files_deleted=0,
            error=f"Verification failed: {'; '.join(verification.missing_files)}",
        )

    files_deleted = 0
    for bf in book.files:
        try:
            if os.path.exists(bf.original_path):
                os.remove(bf.original_path)
                files_deleted += 1
            bf.copy_status = "purged"
        except Exception as e:
            db.commit()
            return PurgeResultItem(
                book_id=book.id,
                success=False,
                files_deleted=files_deleted,
                error=f"Failed to delete {bf.original_path}: {e}",
            )

    book.purge_status = "purged"
    db.commit()

    # Try to remove empty parent folder
    if book.scanned_folder:
        folder_path = book.scanned_folder.folder_path
        try:
            if os.path.isdir(folder_path) and not os.listdir(folder_path):
                os.rmdir(folder_path)
        except Exception:
            logger.warning("Could not remove empty folder: %s", folder_path, exc_info=True)

    return PurgeResultItem(
        book_id=book.id,
        success=True,
        files_deleted=files_deleted,
        error=None,
    )
