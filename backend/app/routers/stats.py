"""Library statistics + duplicate-detection endpoints."""

import logging
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models.book import Book

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


# --- Stats schemas ----------------------------------------------------


class CountedItem(BaseModel):
    name: str
    count: int


class StatsTotals(BaseModel):
    books: int
    confirmed: int
    organized: int
    purged: int
    locked: int


class StatsResponse(BaseModel):
    totals: StatsTotals
    sources: list[CountedItem]
    editions: list[CountedItem]
    top_authors: list[CountedItem]
    top_series: list[CountedItem]
    by_decade: list[CountedItem]


@router.get("", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """Aggregate library counts for the Library dashboard.

    All queries are simple GROUP BY / COUNT and use the indexes added
    in PR 2 (organize_status, purge_status, author, etc.), so this
    endpoint stays fast even at 10k+ books.
    """
    totals = StatsTotals(
        books=db.query(func.count(Book.id)).scalar() or 0,
        confirmed=db.query(func.count(Book.id))
        .filter(Book.is_confirmed.is_(True))
        .scalar() or 0,
        organized=db.query(func.count(Book.id))
        .filter(Book.organize_status == "copied")
        .scalar() or 0,
        purged=db.query(func.count(Book.id))
        .filter(Book.purge_status == "purged")
        .scalar() or 0,
        locked=db.query(func.count(Book.id))
        .filter(Book.locked.is_(True))
        .scalar() or 0,
    )

    sources = [
        CountedItem(name=row[0] or "unknown", count=row[1])
        for row in db.query(Book.source, func.count(Book.id))
        .group_by(Book.source)
        .order_by(func.count(Book.id).desc())
        .all()
    ]

    editions = [
        CountedItem(name=row[0] or "Standard", count=row[1])
        for row in db.query(Book.edition, func.count(Book.id))
        .group_by(Book.edition)
        .order_by(func.count(Book.id).desc())
        .all()
    ]

    top_authors = [
        CountedItem(name=row[0], count=row[1])
        for row in db.query(Book.author, func.count(Book.id))
        .filter(Book.author.isnot(None))
        .filter(Book.author != "")
        .group_by(Book.author)
        .order_by(func.count(Book.id).desc())
        .limit(25)
        .all()
    ]

    top_series = [
        CountedItem(name=row[0], count=row[1])
        for row in db.query(Book.series, func.count(Book.id))
        .filter(Book.series.isnot(None))
        .filter(Book.series != "")
        .group_by(Book.series)
        .order_by(func.count(Book.id).desc())
        .limit(25)
        .all()
    ]

    # Bucket years into decades. SQLite has no native FLOOR, but we can
    # construct the bucket label with substring + concat. Doing this in
    # Python after a SELECT keeps the SQL portable.
    raw_years = (
        db.query(Book.year, func.count(Book.id))
        .filter(Book.year.isnot(None))
        .filter(Book.year != "")
        .group_by(Book.year)
        .all()
    )
    decade_counts: dict[str, int] = defaultdict(int)
    for year_str, count in raw_years:
        digits = re.sub(r"\D", "", year_str or "")
        if len(digits) >= 4:
            year = int(digits[:4])
            decade = f"{year // 10 * 10}s"
            decade_counts[decade] += count
    by_decade = [
        CountedItem(name=label, count=count)
        for label, count in sorted(
            decade_counts.items(), key=lambda kv: kv[0]
        )
    ]

    return StatsResponse(
        totals=totals,
        sources=sources,
        editions=editions,
        top_authors=top_authors,
        top_series=top_series,
        by_decade=by_decade,
    )


# --- Duplicates -------------------------------------------------------


class DuplicateBook(BaseModel):
    id: int
    title: str | None
    author: str | None
    edition: str | None
    confidence: float
    is_confirmed: bool
    folder_path: str | None
    cover_url: str | None
    organize_status: str


class DuplicateGroup(BaseModel):
    key: str
    title: str | None
    author: str | None
    edition: str | None
    books: list[DuplicateBook]


class DuplicatesResponse(BaseModel):
    groups: list[DuplicateGroup]


def _normalize(value: str | None) -> str:
    """Stable comparison key — lowercase, alphanumeric only."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


@router.get("/duplicates", response_model=DuplicatesResponse)
def get_duplicates(db: Session = Depends(get_db)):
    """Return groups of books that look like duplicates of each other.

    A duplicate group is books with the SAME normalized title+author
    AND the SAME edition (or both no edition). Different-edition
    matches (e.g. Graphic Audio vs standard) are intentionally NOT
    flagged — they're expected to coexist.
    """
    books = (
        db.query(Book)
        .options(
            joinedload(Book.scanned_folder),
            selectinload(Book.candidates),
        )
        .all()
    )

    groups: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        if not book.title:
            continue
        edition = book.edition or "standard"
        key = (
            _normalize(book.title)
            + "|" + _normalize(book.author)
            + "|" + _normalize(edition)
        )
        groups[key].append(book)

    result: list[DuplicateGroup] = []
    for key, books_in_group in groups.items():
        if len(books_in_group) < 2:
            continue
        # Sort: confirmed first, then highest confidence, then by id.
        books_in_group.sort(
            key=lambda b: (
                0 if b.is_confirmed else 1,
                -b.confidence,
                b.id,
            )
        )
        # Hydrate cover_url for each member.
        members: list[DuplicateBook] = []
        for b in books_in_group:
            cover = None
            for c in b.candidates:
                if not c.rejected and c.cover_url:
                    cover = c.cover_url
                    if c.applied:
                        break
            members.append(DuplicateBook(
                id=b.id,
                title=b.title,
                author=b.author,
                edition=b.edition,
                confidence=b.confidence,
                is_confirmed=b.is_confirmed,
                folder_path=b.scanned_folder.folder_path if b.scanned_folder else None,
                cover_url=cover,
                organize_status=b.organize_status,
            ))
        result.append(DuplicateGroup(
            key=key,
            title=books_in_group[0].title,
            author=books_in_group[0].author,
            edition=books_in_group[0].edition,
            books=members,
        ))

    # Sort groups so the worst offenders (most copies) show first.
    result.sort(key=lambda g: -len(g.books))
    return DuplicatesResponse(groups=result)


class ResolveDuplicatesRequest(BaseModel):
    """Resolve a duplicate group: keep `keep_id`, delete the rest."""
    keep_id: int
    delete_ids: list[int]


class ResolveDuplicatesResponse(BaseModel):
    deleted: int


@router.post("/duplicates/resolve", response_model=ResolveDuplicatesResponse)
def resolve_duplicates(
    body: ResolveDuplicatesRequest, db: Session = Depends(get_db),
):
    """Delete the books in `delete_ids` and keep `keep_id`.

    Does NOT touch files on disk — same semantics as
    `DELETE /api/books/{id}`. Drops the corresponding ScannedFolder
    rows so the next scan doesn't re-import the orphan.
    """
    if body.keep_id in body.delete_ids:
        raise HTTPException(
            status_code=400, detail="keep_id cannot be in delete_ids"
        )
    if not body.delete_ids:
        raise HTTPException(status_code=400, detail="delete_ids required")

    books_to_delete = (
        db.query(Book)
        .options(joinedload(Book.scanned_folder))
        .filter(Book.id.in_(body.delete_ids))
        .all()
    )
    deleted = 0
    for book in books_to_delete:
        scanned_folder = book.scanned_folder
        db.delete(book)
        if scanned_folder is not None:
            db.delete(scanned_folder)
        deleted += 1
    db.commit()
    return ResolveDuplicatesResponse(deleted=deleted)


