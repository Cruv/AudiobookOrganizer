import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.book import Book
from app.models.settings import UserSetting
from app.schemas.organize import (
    OrganizePreviewItem,
    OrganizePreviewResponse,
    OrganizeRequest,
    OrganizeStatusResponse,
    PurgeRequest,
    PurgeResponse,
    PurgeVerifyResponse,
)
from app.services.organizer import (
    InsufficientDiskSpaceError,
    organize_book,
    preflight_disk_space,
    preview_output_path,
)
from app.services.purger import purge_book, verify_book

router = APIRouter(prefix="/api/organize", tags=["organize"])


def _get_settings(db: Session) -> tuple[str, str]:
    """Get output pattern and root from settings."""
    from app.config import settings as app_settings

    pattern_setting = (
        db.query(UserSetting).filter(UserSetting.key == "output_pattern").first()
    )
    root_setting = (
        db.query(UserSetting).filter(UserSetting.key == "output_root").first()
    )

    pattern = (
        pattern_setting.value if pattern_setting else app_settings.default_output_pattern
    )
    root = root_setting.value if root_setting else app_settings.default_output_root

    return pattern, root


@router.post("/preview", response_model=OrganizePreviewResponse)
def preview_organize(body: OrganizeRequest, db: Session = Depends(get_db)):
    """Preview output paths for books without copying."""
    pattern, root = _get_settings(db)

    books = (
        db.query(Book)
        .options(joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    items = []
    for book in books:
        dest = preview_output_path(book, pattern, root)
        items.append(
            OrganizePreviewItem(
                book_id=book.id,
                title=book.title,
                author=book.author,
                source_path=book.scanned_folder.folder_path if book.scanned_folder else "",
                destination_path=dest,
            )
        )

    return OrganizePreviewResponse(items=items)


@router.post("/execute")
def execute_organize(
    body: OrganizeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start organizing books (copying files).

    Performs a disk-space preflight check before scheduling the copy so
    users get an immediate, actionable error instead of discovering
    mid-batch that the output filesystem is full.
    """
    pattern, root = _get_settings(db)

    books = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    if not books:
        raise HTTPException(status_code=404, detail="No books found")

    # Sum bytes required across all not-yet-copied files. Already-copied
    # files don't need to be re-copied so exclude them from the estimate.
    required = 0
    for book in books:
        for bf in book.files:
            if bf.copy_status != "copied":
                required += bf.file_size or 0

    if required > 0:
        try:
            preflight_disk_space(root, required)
        except InsufficientDiskSpaceError as e:
            raise HTTPException(
                status_code=507,  # Insufficient Storage
                detail={
                    "message": "Not enough free space on output volume",
                    "output_root": e.path,
                    "required_bytes": e.required,
                    "available_bytes": e.available,
                },
            ) from e

    # Mark as copying
    for book in books:
        book.organize_status = "copying"
    db.commit()

    book_ids = [b.id for b in books]
    background_tasks.add_task(_organize_books, book_ids, pattern, root)

    return {"detail": f"Organizing {len(books)} books", "book_ids": book_ids}


_logger = logging.getLogger(__name__)


def _organize_books(book_ids: list[int], pattern: str, root: str) -> None:
    """Background task to organize books.

    Each book is wrapped in its own try/except so a single failure
    (permission denied, disk full mid-copy, path collision) doesn't
    strand the remaining books in `organize_status="copying"` forever
    — which previously left the frontend spinner running indefinitely
    while no further work was happening.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for book_id in book_ids:
            try:
                book = (
                    db.query(Book)
                    .options(joinedload(Book.files), joinedload(Book.scanned_folder))
                    .filter(Book.id == book_id)
                    .first()
                )
                if not book:
                    continue
                organize_book(book, pattern, root, db)
            except Exception as e:
                _logger.exception("Organize failed for book %s", book_id)
                try:
                    db.rollback()
                    stuck = db.query(Book).filter(Book.id == book_id).first()
                    if stuck and stuck.organize_status == "copying":
                        stuck.organize_status = "failed"
                        db.commit()
                except Exception:
                    _logger.warning(
                        "Could not mark book %s as failed after organize error: %s",
                        book_id, type(e).__name__,
                    )
                    db.rollback()
    finally:
        db.close()


class UndoOrganizeRequest(BaseModel):
    book_ids: list[int]


class UndoOrganizeResult(BaseModel):
    book_id: int
    success: bool
    files_removed: int
    error: str | None = None


class UndoOrganizeResponse(BaseModel):
    results: list[UndoOrganizeResult]


@router.post("/undo", response_model=UndoOrganizeResponse)
def undo_organize(
    body: UndoOrganizeRequest, db: Session = Depends(get_db),
):
    """Reverse an organize operation: delete the copied destination
    files and reset the book back to organize_status="pending".

    Only safe when the original source files still exist — we refuse
    to delete the copy otherwise (that would leave the user with no
    copies of the audio anywhere). Sidecars and cover.jpg are deleted
    along with the audio.

    Books in organize_status="failed" can also be undone (cleans up
    partial state). Books that were already purged are skipped — by
    that point the originals are gone so reversing would lose data.
    """
    import os

    books = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    results: list[UndoOrganizeResult] = []
    for book in books:
        if book.purge_status == "purged":
            results.append(UndoOrganizeResult(
                book_id=book.id, success=False, files_removed=0,
                error="Already purged; cannot undo.",
            ))
            continue

        # Safety: refuse if ANY source file is missing.
        missing_sources = [
            bf for bf in book.files
            if bf.original_path and not os.path.exists(bf.original_path)
        ]
        if missing_sources:
            results.append(UndoOrganizeResult(
                book_id=book.id, success=False, files_removed=0,
                error=(
                    f"Refusing to undo: {len(missing_sources)} source file(s) "
                    "are missing. Removing the copy would lose data."
                ),
            ))
            continue

        files_removed = 0
        had_error: str | None = None
        output_dir = book.output_path
        for bf in book.files:
            dest = bf.destination_path
            if dest and os.path.isfile(dest):
                try:
                    os.remove(dest)
                    files_removed += 1
                except Exception as e:
                    had_error = f"Couldn't remove {dest}: {e}"
                    break
            bf.destination_path = None
            bf.copy_status = "pending"

        # Best-effort: remove sidecar + cover.jpg + empty output dir.
        if output_dir and os.path.isdir(output_dir):
            from app.services.organizer import COVER_FILENAME, SIDECAR_FILENAME

            for filename in (SIDECAR_FILENAME, COVER_FILENAME):
                p = os.path.join(output_dir, filename)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            try:
                if not os.listdir(output_dir):
                    os.rmdir(output_dir)
            except OSError:
                # Not empty (user added files manually, or shared with
                # another book) — leave it alone.
                pass

        if had_error is None:
            book.organize_status = "pending"
            book.output_path = None
            results.append(UndoOrganizeResult(
                book_id=book.id, success=True, files_removed=files_removed,
            ))
        else:
            results.append(UndoOrganizeResult(
                book_id=book.id, success=False,
                files_removed=files_removed, error=had_error,
            ))

    db.commit()
    return UndoOrganizeResponse(results=results)


@router.get("/status/{book_id}", response_model=OrganizeStatusResponse)
def get_organize_status(book_id: int, db: Session = Depends(get_db)):
    """Get copy progress for a book."""
    book = (
        db.query(Book)
        .options(joinedload(Book.files))
        .filter(Book.id == book_id)
        .first()
    )
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    files_total = len(book.files)
    files_copied = sum(1 for f in book.files if f.copy_status == "copied")
    files_failed = sum(1 for f in book.files if f.copy_status == "failed")

    return OrganizeStatusResponse(
        book_id=book.id,
        organize_status=book.organize_status,
        files_copied=files_copied,
        files_total=files_total,
        files_failed=files_failed,
    )


# Purge endpoints
purge_router = APIRouter(prefix="/api/purge", tags=["purge"])


@purge_router.post("/verify", response_model=PurgeVerifyResponse)
def verify_purge(body: OrganizeRequest, db: Session = Depends(get_db)):
    """Verify that destination files exist before purging."""
    books = (
        db.query(Book)
        .options(joinedload(Book.files))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    items = [verify_book(book) for book in books]
    return PurgeVerifyResponse(items=items)


@purge_router.post("/execute", response_model=PurgeResponse)
def execute_purge(body: PurgeRequest, db: Session = Depends(get_db)):
    """Delete original files for organized books."""
    books = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    if not books:
        raise HTTPException(status_code=404, detail="No books found")

    results = [purge_book(book, db) for book in books]
    return PurgeResponse(results=results)
