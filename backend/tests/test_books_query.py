"""Tests for the PR 2 changes to the /api/books list endpoint:
- separate, lean count() query
- apply_lookup re-keys by book identity instead of "most recent N"
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_db():
    from app.models.base import Base
    import app.models.book  # noqa: F401
    import app.models.lookup_cache  # noqa: F401
    import app.models.lookup_candidate  # noqa: F401
    import app.models.scan  # noqa: F401
    import app.models.settings  # noqa: F401
    import app.models.user  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_book(db, *, title=None, author=None, is_confirmed=False, confidence=0.5):
    from app.models.book import Book

    b = Book(
        title=title or "Title",
        author=author or "Author",
        source="parsed",
        confidence=confidence,
        is_confirmed=is_confirmed,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


class TestListBooksCount:
    def test_total_matches_filtered_set(self):
        from app.routers.books import list_books

        db = _make_db()
        _add_book(db, title="A", is_confirmed=True)
        _add_book(db, title="B", is_confirmed=False)
        _add_book(db, title="C", is_confirmed=True)

        resp = list_books(
            scan_id=None, confirmed=True, organize_status=None,
            purge_status=None, sort="confidence", page=1, page_size=10,
            edition=None, min_confidence=None, max_confidence=None,
            search=None, db=db,
        )
        assert resp.total == 2
        assert len(resp.items) == 2
        assert all(b.is_confirmed for b in resp.items)

    def test_pagination_respects_total(self):
        from app.routers.books import list_books

        db = _make_db()
        for i in range(25):
            _add_book(db, title=f"T{i}")

        resp = list_books(
            scan_id=None, confirmed=None, organize_status=None,
            purge_status=None, sort="title", page=2, page_size=10,
            edition=None, min_confidence=None, max_confidence=None,
            search=None, db=db,
        )
        assert resp.total == 25
        assert resp.page == 2
        assert resp.total_pages == 3
        assert len(resp.items) == 10

    def test_no_results_returns_total_zero(self):
        from app.routers.books import list_books

        db = _make_db()
        resp = list_books(
            scan_id=None, confirmed=None, organize_status=None,
            purge_status=None, sort="confidence", page=1, page_size=10,
            edition=None, min_confidence=None, max_confidence=None,
            search=None, db=db,
        )
        assert resp.total == 0
        assert resp.items == []
        # Pagination math should still produce a sensible page count
        # even when total is 0 (avoid /0 errors).
        assert resp.total_pages == 1


class TestApplyLookupKeyedToBook:
    def _seed_cache(self, db, *, provider, query, results):
        from app.models.lookup_cache import LookupCache
        from app.services.lookup import _cache_key

        row = LookupCache(
            query_hash=_cache_key(query, provider),
            provider=provider,
            query_text=query,
            response_json=json.dumps(results),
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db.add(row)
        db.commit()

    def test_apply_lookup_finds_matching_cache_row_by_book_query(self):
        """The cache row is keyed by THIS book's clean_query, not the
        most recent provider row."""
        from app.routers.books import apply_lookup
        from app.schemas.book import ApplyLookup

        db = _make_db()
        target = _add_book(db, title="My Test Book", author="Test Author")
        # Wrong book's cache row — must NOT be picked.
        decoy = _add_book(db, title="Wrong Book", author="Other Author")
        self._seed_cache(
            db,
            provider="google_books",
            query=f"intitle:{decoy.title}+inauthor:{decoy.author}",
            results=[{"title": "Wrong Title", "author": "Wrong Author"}],
        )
        # Right book's cache row.
        self._seed_cache(
            db,
            provider="google_books",
            query=f"intitle:{target.title}+inauthor:{target.author}",
            results=[
                {"title": "Right Title", "author": "Right Author", "confidence": 0.9},
            ],
        )

        resp = apply_lookup(
            target.id,
            ApplyLookup(provider="google_books", result_index=0),
            db=db,
        )
        assert resp.title == "Right Title"
        assert resp.author == "Right Author"
        assert resp.source == "google_books"

    def test_apply_lookup_returns_404_when_no_cache_for_book(self):
        from fastapi import HTTPException

        from app.routers.books import apply_lookup
        from app.schemas.book import ApplyLookup

        db = _make_db()
        book = _add_book(db, title="No Cache Yet", author="Author")

        with pytest.raises(HTTPException) as exc_info:
            apply_lookup(
                book.id,
                ApplyLookup(provider="google_books", result_index=0),
                db=db,
            )
        assert exc_info.value.status_code == 404

    def test_apply_lookup_rejects_negative_index(self):
        from fastapi import HTTPException

        from app.routers.books import apply_lookup
        from app.schemas.book import ApplyLookup

        db = _make_db()
        book = _add_book(db)

        with pytest.raises(HTTPException) as exc_info:
            apply_lookup(
                book.id,
                ApplyLookup(provider="google_books", result_index=-1),
                db=db,
            )
        assert exc_info.value.status_code == 400

    def test_apply_lookup_rejects_out_of_range_index(self):
        from fastapi import HTTPException

        from app.routers.books import apply_lookup
        from app.schemas.book import ApplyLookup

        db = _make_db()
        book = _add_book(db, title="Book One", author="Au")
        self._seed_cache(
            db,
            provider="google_books",
            query=f"intitle:{book.title}+inauthor:{book.author}",
            results=[{"title": "Only One"}],  # length 1
        )

        with pytest.raises(HTTPException) as exc_info:
            apply_lookup(
                book.id,
                ApplyLookup(provider="google_books", result_index=5),
                db=db,
            )
        assert exc_info.value.status_code == 404
