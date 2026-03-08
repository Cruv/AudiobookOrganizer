from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
from app.services.organizer import organize_book, preview_output_path
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
    """Start organizing books (copying files)."""
    pattern, root = _get_settings(db)

    books = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )

    if not books:
        raise HTTPException(status_code=404, detail="No books found")

    # Mark as copying
    for book in books:
        book.organize_status = "copying"
    db.commit()

    # Run in background
    book_ids = [b.id for b in books]
    background_tasks.add_task(_organize_books, book_ids, pattern, root)

    return {"detail": f"Organizing {len(books)} books", "book_ids": book_ids}


def _organize_books(book_ids: list[int], pattern: str, root: str) -> None:
    """Background task to organize books."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for book_id in book_ids:
            book = (
                db.query(Book)
                .options(joinedload(Book.files), joinedload(Book.scanned_folder))
                .filter(Book.id == book_id)
                .first()
            )
            if book:
                organize_book(book, pattern, root, db)
    finally:
        db.close()


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
