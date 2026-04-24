import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.book import Book
from app.models.lookup_candidate import LookupCandidate
from app.models.scan import ScannedFolder
from app.models.settings import UserSetting
from app.schemas.book import (
    ApplyLookup,
    BookBulkUpdate,
    BookBulkUpdateResponse,
    BookConfirmBatch,
    BookDetailResponse,
    BookResponse,
    BookSearch,
    BookUpdate,
    LookupResponse,
    PaginatedBooksResponse,
)
from app.services.candidates import apply_candidate, refresh_candidates, reject_candidate
from app.services.lookup import lookup_book
from app.services.organizer import build_output_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


def _get_settings(db: Session) -> tuple[str, str]:
    """Get output pattern and root from settings."""
    pattern_setting = db.query(UserSetting).filter(UserSetting.key == "output_pattern").first()
    root_setting = db.query(UserSetting).filter(UserSetting.key == "output_root").first()
    pattern = pattern_setting.value if pattern_setting else "{Author}/{Series}/{SeriesPosition} - {Title} ({Year}) {EditionBracketed}"
    root = root_setting.value if root_setting else "/audiobooks"
    return pattern, root


def _attach_book_info(
    book: Book,
    resp: BookResponse,
    db: Session,
    *,
    pattern: str | None = None,
    root: str | None = None,
) -> None:
    """Attach folder info and projected path to a book response.

    `pattern` / `root` can be passed to avoid a per-book settings lookup
    when we're attaching info for many books in a row. When they're
    None we fall back to _get_settings(db) so single-book callers
    don't have to change.
    """
    if book.scanned_folder:
        resp.folder_path = book.scanned_folder.folder_path
        resp.folder_name = book.scanned_folder.folder_name
    if pattern is None or root is None:
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

    # Fetch output settings once, not per-book — used to render projected_path.
    pattern, root = _get_settings(db)
    results = []
    for book in books:
        resp = BookResponse.model_validate(book)
        _attach_book_info(book, resp, db, pattern=pattern, root=root)
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


# --------------------------------------------------------------------- #
# Bulk update — applies a single patch to N books at once. Used for
# fixing a series/author/edition across multiple books after a scan.
# Positioned before the single-book PATCH route so FastAPI resolves
# /books/bulk-update to this handler, not /books/{book_id}.
# --------------------------------------------------------------------- #


# Only these fields are safe to bulk-patch. Title is excluded because
# bulk-setting the same title across many books is almost never intended.
_BULK_EDITABLE_FIELDS = frozenset({
    "author", "series", "series_position", "year",
    "narrator", "edition", "is_confirmed", "locked",
})


@router.post("/bulk-update", response_model=BookBulkUpdateResponse)
def bulk_update_books(body: BookBulkUpdate, db: Session = Depends(get_db)):
    """Apply one patch to many books.

    Only fields in _BULK_EDITABLE_FIELDS are accepted; unknown or unsafe
    keys are silently dropped. Empty-string values set the field to None
    (so users can bulk-clear a field). Books not found are skipped.
    Sets source="manual" on every touched book unless the only fields
    being patched are is_confirmed/locked (flags, not metadata edits).
    """
    if not body.book_ids:
        raise HTTPException(status_code=400, detail="book_ids required")
    if not body.patch:
        raise HTTPException(status_code=400, detail="patch required")

    # Filter to only allowed fields
    clean_patch: dict[str, str | bool | None] = {}
    for key, value in body.patch.items():
        if key not in _BULK_EDITABLE_FIELDS:
            continue
        # Normalize empty strings to None so users can clear a field.
        if isinstance(value, str) and value.strip() == "":
            clean_patch[key] = None
        else:
            clean_patch[key] = value

    if not clean_patch:
        raise HTTPException(
            status_code=400,
            detail="No valid fields in patch (allowed: "
            + ", ".join(sorted(_BULK_EDITABLE_FIELDS)) + ")",
        )

    only_flags = set(clean_patch.keys()).issubset({"is_confirmed", "locked"})

    books = db.query(Book).filter(Book.id.in_(body.book_ids)).all()
    updated = 0
    field_counts: dict[str, int] = {f: 0 for f in clean_patch.keys()}

    for book in books:
        touched = False
        for field, value in clean_patch.items():
            # Only count a change when the value actually differs.
            if getattr(book, field) != value:
                setattr(book, field, value)
                field_counts[field] += 1
                touched = True
        if touched:
            if not only_flags:
                book.source = "manual"
            updated += 1

    db.commit()
    return BookBulkUpdateResponse(updated=updated, field_counts=field_counts)


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


class MarkOrganizedBatch(BaseModel):
    book_ids: list[int]


def _mark_book_organized(book: Book) -> bool:
    """Mark a book's files as in-place ("already organized") using the
    book's scanned folder path as the destination. Returns True if the
    book was updated. No-op on books that are already marked copied.

    Useful when the user's library was organized by hand (or by another
    tool) and we don't want to re-offer it on the Organize page.
    """
    if book.organize_status == "copied":
        return False
    if not book.scanned_folder:
        return False

    folder_path = book.scanned_folder.folder_path
    book.organize_status = "copied"
    book.output_path = folder_path
    for bf in book.files:
        bf.destination_path = bf.original_path
        bf.copy_status = "copied"
    return True


@router.post("/{book_id}/mark-organized", response_model=BookResponse)
def mark_organized(book_id: int, db: Session = Depends(get_db)):
    """Treat this book as already organized in place (no copy needed).

    Sets organize_status="copied" + output_path to the source folder +
    every BookFile's destination_path = its original_path. Use when the
    book is already in its final location and you don't want the
    Organize page to re-offer it.
    """
    book = db.query(Book).options(joinedload(Book.files)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _mark_book_organized(book)
    db.commit()
    db.refresh(book)
    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


@router.post("/mark-organized-batch")
def mark_organized_batch(body: MarkOrganizedBatch, db: Session = Depends(get_db)):
    """Bulk version of mark_organized. Skips books that are already
    copied or that have no scanned folder."""
    if not body.book_ids:
        raise HTTPException(status_code=400, detail="book_ids required")

    books = (
        db.query(Book)
        .options(joinedload(Book.files), joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.book_ids))
        .all()
    )
    updated = sum(1 for b in books if _mark_book_organized(b))
    db.commit()
    return {"updated": updated, "total": len(books)}


@router.post("/{book_id}/lock", response_model=BookResponse)
def lock_book(book_id: int, db: Session = Depends(get_db)):
    """Freeze a book's metadata: neither re-scan nor auto-lookup will
    overwrite locked fields. Useful when the book is *correct* and you
    don't trust the parser to leave it alone on the next scan."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book.locked = True
    db.commit()
    db.refresh(book)
    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


@router.post("/{book_id}/unlock", response_model=BookResponse)
def unlock_book(book_id: int, db: Session = Depends(get_db)):
    """Allow auto-lookup / re-scan to mutate this book's metadata again."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book.locked = False
    db.commit()
    db.refresh(book)
    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


@router.post("/{book_id}/unconfirm", response_model=BookResponse)
def unconfirm_book(book_id: int, db: Session = Depends(get_db)):
    """Remove confirmation from a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    book.is_confirmed = False
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


@router.post("/unconfirm-batch")
def unconfirm_batch(body: BookConfirmBatch, db: Session = Depends(get_db)):
    """Batch unconfirm books by IDs, confidence threshold, or all."""
    query = db.query(Book)

    if body.book_ids:
        query = query.filter(Book.id.in_(body.book_ids))
    elif body.min_confidence is not None:
        query = query.filter(Book.confidence >= body.min_confidence)
        if body.scan_id is not None:
            query = query.join(ScannedFolder).filter(
                ScannedFolder.scan_id == body.scan_id
            )
    elif body.scan_id is not None:
        query = query.join(ScannedFolder).filter(
            ScannedFolder.scan_id == body.scan_id
        )

    books = query.all()
    count = 0
    for book in books:
        if book.is_confirmed:
            book.is_confirmed = False
            count += 1

    db.commit()
    return {"unconfirmed": count}


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

    try:
        results = await lookup_book(title, book.author, api_key, db)
    except Exception as e:
        logger.warning(
            "Lookup failed for book %s: %s", book_id, type(e).__name__, exc_info=True
        )
        raise HTTPException(
            status_code=502,
            detail=f"Lookup provider error ({type(e).__name__}). Try again shortly.",
        ) from e
    return LookupResponse(results=results)


@router.post("/{book_id}/search", response_model=LookupResponse)
async def search_book_endpoint(
    book_id: int, body: BookSearch, db: Session = Depends(get_db)
):
    """Search online with a custom query for a book.

    Upstream lookup providers raise a variety of transient errors (Audible
    token expiry, iTunes 503, Google Books rate-limit). Any uncaught
    exception returns 500 which hides the real cause; instead we catch,
    log the exception type + traceback, and return a 502 with a user-
    actionable hint.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is empty")
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="Search query too long")

    api_key_setting = (
        db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    )
    api_key = api_key_setting.value if api_key_setting else None

    try:
        results = await lookup_book(query, None, api_key, db)
    except Exception as e:
        logger.warning(
            "Search failed for book %s, query %r: %s",
            book_id, query, type(e).__name__, exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Lookup provider error ({type(e).__name__}). Try again shortly.",
        ) from e
    return LookupResponse(results=results)


# --------------------------------------------------------------------- #
# Persisted lookup candidates
# --------------------------------------------------------------------- #

class CandidateResponse(BaseModel):
    id: int
    book_id: int
    provider: str
    provider_rank: int
    title: str | None
    author: str | None
    series: str | None
    series_position: str | None
    year: str | None
    narrator: str | None
    description: str | None
    cover_url: str | None
    raw_confidence: float
    match_score: float
    trust_weight: float
    ranking_score: float
    match_breakdown: dict | None
    rejected: bool
    applied: bool

    model_config = {"from_attributes": True}


def _candidate_to_response(c: LookupCandidate) -> CandidateResponse:
    breakdown = None
    if c.match_breakdown:
        try:
            breakdown = json.loads(c.match_breakdown)
        except (ValueError, TypeError):
            breakdown = None
    return CandidateResponse(
        id=c.id, book_id=c.book_id, provider=c.provider,
        provider_rank=c.provider_rank, title=c.title, author=c.author,
        series=c.series, series_position=c.series_position, year=c.year,
        narrator=c.narrator, description=c.description, cover_url=c.cover_url,
        raw_confidence=c.raw_confidence, match_score=c.match_score,
        trust_weight=c.trust_weight, ranking_score=c.ranking_score,
        match_breakdown=breakdown, rejected=c.rejected, applied=c.applied,
    )


@router.get("/{book_id}/candidates", response_model=list[CandidateResponse])
def list_candidates(
    book_id: int,
    include_rejected: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List persisted lookup candidates for a book, best first."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    q = db.query(LookupCandidate).filter(LookupCandidate.book_id == book_id)
    if not include_rejected:
        q = q.filter(LookupCandidate.rejected.is_(False))
    candidates = q.order_by(LookupCandidate.ranking_score.desc()).all()
    return [_candidate_to_response(c) for c in candidates]


@router.post("/{book_id}/relookup", response_model=list[CandidateResponse])
async def relookup_book(
    book_id: int,
    auto_apply: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Re-run lookup for a single book: refresh candidates and, unless
    ?auto_apply=false, apply the best non-rejected one.

    Does NOT reset rejected candidates — if the user has explicitly said
    no to a provider's result, that stays.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    api_key_setting = (
        db.query(UserSetting).filter(UserSetting.key == "google_books_api_key").first()
    )
    api_key = api_key_setting.value if api_key_setting else None

    candidates = await refresh_candidates(book, db, api_key=api_key, auto_apply=auto_apply)
    return [_candidate_to_response(c) for c in candidates]


@router.post("/{book_id}/candidates/{candidate_id}/apply", response_model=BookResponse)
def apply_candidate_endpoint(
    book_id: int, candidate_id: int, db: Session = Depends(get_db)
):
    """Apply a specific persisted candidate to the book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    candidate = (
        db.query(LookupCandidate)
        .filter(
            LookupCandidate.id == candidate_id,
            LookupCandidate.book_id == book_id,
        )
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    apply_candidate(book, candidate, db)
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


@router.post("/{book_id}/candidates/{candidate_id}/reject", response_model=BookResponse)
def reject_candidate_endpoint(
    book_id: int, candidate_id: int, db: Session = Depends(get_db)
):
    """Reject a persisted candidate. If it was applied, revert the book
    to the parsed state (source=parsed, match_confidence=0).
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    candidate = (
        db.query(LookupCandidate)
        .filter(
            LookupCandidate.id == candidate_id,
            LookupCandidate.book_id == book_id,
        )
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    reject_candidate(candidate, db)
    db.commit()
    db.refresh(book)

    resp = BookResponse.model_validate(book)
    _attach_book_info(book, resp, db)
    return resp


# --------------------------------------------------------------------- #
# Legacy apply-lookup (cached-results lookup by index). Kept so the
# existing SearchModal keeps working until the frontend migrates.
# --------------------------------------------------------------------- #


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
