from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.book import Book
from app.models.scan import ScannedFolder
from app.schemas.book import (
    ApplyLookup,
    BookConfirmBatch,
    BookDetailResponse,
    BookResponse,
    BookUpdate,
    LookupResponse,
)
from app.services.lookup import lookup_book

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=list[BookResponse])
def list_books(
    scan_id: int | None = Query(None),
    confirmed: bool | None = Query(None),
    organize_status: str | None = Query(None),
    purge_status: str | None = Query(None),
    sort: str = Query("confidence"),
    db: Session = Depends(get_db),
):
    """List books with optional filtering."""
    query = db.query(Book).outerjoin(ScannedFolder)

    if scan_id is not None:
        query = query.filter(ScannedFolder.scan_id == scan_id)
    if confirmed is not None:
        query = query.filter(Book.is_confirmed == confirmed)
    if organize_status is not None:
        query = query.filter(Book.organize_status == organize_status)
    if purge_status is not None:
        query = query.filter(Book.purge_status == purge_status)

    if sort == "confidence":
        query = query.order_by(Book.confidence.asc())
    elif sort == "confidence_desc":
        query = query.order_by(Book.confidence.desc())
    elif sort == "title":
        query = query.order_by(Book.title.asc())
    elif sort == "author":
        query = query.order_by(Book.author.asc())
    else:
        query = query.order_by(Book.created_at.desc())

    books = query.all()

    # Attach folder info
    results = []
    for book in books:
        resp = BookResponse.model_validate(book)
        if book.scanned_folder:
            resp.folder_path = book.scanned_folder.folder_path
            resp.folder_name = book.scanned_folder.folder_name
        results.append(resp)

    return results


@router.get("/{book_id}", response_model=BookDetailResponse)
def get_book(book_id: int, db: Session = Depends(get_db)):
    """Get book details including files."""
    book = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id == book_id)
        .first()
    )
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    resp = BookDetailResponse.model_validate(book)
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    return resp


@router.patch("/{book_id}", response_model=BookResponse)
def update_book(book_id: int, body: BookUpdate, db: Session = Depends(get_db)):
    """Update book metadata."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)

    book.source = "manual"
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    return resp


@router.post("/{book_id}/confirm", response_model=BookResponse)
def confirm_book(book_id: int, db: Session = Depends(get_db)):
    """Mark a book as confirmed."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    book.is_confirmed = True
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    return resp


@router.post("/confirm-batch")
def confirm_batch(body: BookConfirmBatch, db: Session = Depends(get_db)):
    """Batch confirm books by IDs or confidence threshold."""
    query = db.query(Book)

    if body.book_ids:
        query = query.filter(Book.id.in_(body.book_ids))
    elif body.min_confidence is not None:
        query = query.filter(Book.confidence >= body.min_confidence)
        if body.scan_id is not None:
            query = query.join(ScannedFolder).filter(
                ScannedFolder.scan_id == body.scan_id
            )

    books = query.all()
    count = 0
    for book in books:
        if not book.is_confirmed:
            book.is_confirmed = True
            count += 1

    db.commit()
    return {"confirmed": count}


@router.post("/{book_id}/lookup", response_model=LookupResponse)
async def lookup_book_endpoint(book_id: int, db: Session = Depends(get_db)):
    """Trigger online metadata lookup for a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    title = book.title or ""
    if not title:
        raise HTTPException(
            status_code=400, detail="Book has no title to search for"
        )

    # Get API key from settings
    from app.models.settings import UserSetting

    api_key_setting = (
        db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    )
    api_key = api_key_setting.value if api_key_setting else None

    results = await lookup_book(title, book.author, api_key, db)
    return LookupResponse(results=results)


@router.post("/{book_id}/apply-lookup", response_model=BookResponse)
def apply_lookup(
    book_id: int, body: ApplyLookup, db: Session = Depends(get_db)
):
    """Apply a lookup result to a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Re-fetch the cached results to get the specific one
    import hashlib
    import json

    from app.models.lookup_cache import LookupCache

    # Find the most recent cache entry for this provider
    cache_entries = (
        db.query(LookupCache)
        .filter(LookupCache.provider == body.provider)
        .order_by(LookupCache.created_at.desc())
        .limit(10)
        .all()
    )

    result_data = None
    for entry in cache_entries:
        results = json.loads(entry.response_json)
        if body.result_index < len(results):
            result_data = results[body.result_index]
            break

    if not result_data:
        raise HTTPException(status_code=404, detail="Lookup result not found")

    # Apply the lookup data to the book
    if result_data.get("title"):
        book.title = result_data["title"]
    if result_data.get("author"):
        book.author = result_data["author"]
    if result_data.get("series"):
        book.series = result_data["series"]
    if result_data.get("series_position"):
        book.series_position = result_data["series_position"]
    if result_data.get("year"):
        book.year = result_data["year"]

    book.source = body.provider
    book.confidence = result_data.get("confidence", 0.85)
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    return resp
