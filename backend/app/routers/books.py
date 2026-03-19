import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.book import Book
from app.models.scan import ScannedFolder
from app.models.settings import UserSetting
from app.schemas.book import (
    ApplyLookup,
    BookConfirmBatch,
    BookDetailResponse,
    BookResponse,
    BookSearch,
    BookUpdate,
    LookupResponse,
    PaginatedBooksResponse,
)
from app.services.lookup import lookup_book
from app.services.organizer import build_output_path

router = APIRouter(prefix="/api/books", tags=["books"])


def _get_settings(db: Session) -> tuple[str, str]:
    """Get output pattern and root from settings."""
    pattern_setting = db.query(UserSetting).filter(UserSetting.key == "output_pattern").first()
    root_setting = db.query(UserSetting).filter(UserSetting.key == "output_root").first()
    pattern = pattern_setting.value if pattern_setting else "{Author}/{Series}/{SeriesPosition} - {Title} ({Year}) {EditionBracketed}"
    root = root_setting.value if root_setting else "/audiobooks"
    return pattern, root


def _attach_book_info(book: Book, resp: BookResponse, db: Session) -> None:
    """Attach folder info and projected path to a book response."""
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    pattern, root = _get_settings(db)
    resp.projected_path = build_output_path(book, pattern, root)


@router.get("", response_model=PaginatedBooksResponse)
def list_books(
    scan_id: int | None = Query(None),
    confirmed: bool | None = Query(None),
    organize_status: str | None = Query(None),
    purge_status: str | None = Query(None),
    sort: str = Query("confidence"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    edition: str | None = Query(None),
    min_confidence: float | None = Query(None),
    max_confidence: float | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """List books with optional filtering and pagination."""
    query = db.query(Book).outerjoin(ScannedFolder).options(joinedload(Book.scanned_folder))

    if scan_id is not None:
        query = query.filter(ScannedFolder.scan_id == scan_id)
    if confirmed is not None:
        query = query.filter(Book.is_confirmed == confirmed)
    if organize_status is not None:
        query = query.filter(Book.organize_status == organize_status)
    if purge_status is not None:
        query = query.filter(Book.purge_status == purge_status)
    if edition is not None:
        query = query.filter(Book.edition == edition)
    if min_confidence is not None:
        query = query.filter(Book.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Book.confidence <= max_confidence)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Book.title.ilike(search_term)) | (Book.author.ilike(search_term))
        )

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

    total = query.count()
    books = query.offset((page - 1) * page_size).limit(page_size).all()

    results = []
    for book in books:
        resp = BookResponse.model_validate(book)
        _attach_book_info(book, resp, db)
        results.append(resp)

    return PaginatedBooksResponse(
        items=results,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/export")
def export_books(
    scan_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Export all books as streaming JSON for debugging matching quality."""
    pattern, root = _get_settings(db)

    query = (
        db.query(Book)
        .outerjoin(ScannedFolder)
        .options(joinedload(Book.scanned_folder), joinedload(Book.files))
    )
    if scan_id is not None:
        query = query.filter(ScannedFolder.scan_id == scan_id)
    query = query.order_by(Book.confidence.asc())

    total = query.count()

    def _generate():
        yield '{"total": ' + str(total)
        yield ', "pattern": ' + json.dumps(pattern)
        yield ', "output_root": ' + json.dumps(root)
        yield ', "books": ['

        first = True
        for book in query.yield_per(50):
            folder_path = book.scanned_folder.folder_path if book.scanned_folder else None
            folder_name = book.scanned_folder.folder_name if book.scanned_folder else None
            projected = build_output_path(book, pattern, root)

            first_file = book.files[0] if book.files else None
            tag_info = None
            if first_file:
                tag_info = {
                    "tag_title": first_file.tag_title,
                    "tag_author": first_file.tag_author,
                    "tag_album": first_file.tag_album,
                    "tag_year": first_file.tag_year,
                    "tag_narrator": first_file.tag_narrator,
                }

            entry = {
                "id": book.id,
                "folder_path": folder_path,
                "folder_name": folder_name,
                "title": book.title,
                "author": book.author,
                "series": book.series,
                "series_position": book.series_position,
                "year": book.year,
                "narrator": book.narrator,
                "edition": book.edition,
                "confidence": book.confidence,
                "source": book.source,
                "is_confirmed": book.is_confirmed,
                "projected_path": projected,
                "file_count": len(book.files),
                "tags_from_file": tag_info,
            }

            if not first:
                yield ", "
            yield json.dumps(entry)
            first = False

        yield "]}"

    return StreamingResponse(_generate(), media_type="application/json")


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
    _attach_book_info(book, resp, db)
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
    _attach_book_info(book, resp, db)
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
    _attach_book_info(book, resp, db)
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

    api_key_setting = (
        db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    )
    api_key = api_key_setting.value if api_key_setting else None

    results = await lookup_book(title, book.author, api_key, db)
    return LookupResponse(results=results)


@router.post("/{book_id}/search", response_model=LookupResponse)
async def search_book_endpoint(
    book_id: int, body: BookSearch, db: Session = Depends(get_db)
):
    """Search online with a custom query for a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    api_key_setting = (
        db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    )
    api_key = api_key_setting.value if api_key_setting else None

    results = await lookup_book(body.query, None, api_key, db)
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
    _attach_book_info(book, resp, db)
    return resp
