"""Safe deletion of original audiobook files after organization."""

import os

from sqlalchemy.orm import Session

from app.models.book import Book, BookFile
from app.schemas.organize import PurgeResultItem, PurgeVerifyItem


def verify_book(book: Book) -> PurgeVerifyItem:
    """Verify that all destination files exist and match original sizes."""
    missing_files: list[str] = []
    total_size = 0

    for bf in book.files:
        total_size += bf.file_size
        if bf.copy_status != "copied":
            missing_files.append(f"{bf.filename}: not copied (status={bf.copy_status})")
            continue
        if not bf.destination_path:
            missing_files.append(f"{bf.filename}: no destination path")
            continue
        if not os.path.exists(bf.destination_path):
            missing_files.append(f"{bf.filename}: destination file missing")
            continue
        dest_size = os.path.getsize(bf.destination_path)
        if dest_size != bf.file_size:
            missing_files.append(
                f"{bf.filename}: size mismatch (original={bf.file_size}, dest={dest_size})"
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
            pass

    return PurgeResultItem(
        book_id=book.id,
        success=True,
        files_deleted=files_deleted,
        error=None,
    )
