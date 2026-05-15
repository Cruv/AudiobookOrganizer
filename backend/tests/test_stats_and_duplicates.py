"""Tests for the /api/stats and /api/stats/duplicates endpoints."""

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


def _add_book(
    db, *,
    title="T", author="A", source="parsed", edition=None, year=None,
    is_confirmed=False, locked=False,
    organize_status="pending", purge_status="not_purged",
    series=None, confidence=0.5,
):
    from app.models.book import Book

    b = Book(
        title=title, author=author, source=source, edition=edition,
        year=year, is_confirmed=is_confirmed, locked=locked,
        organize_status=organize_status, purge_status=purge_status,
        series=series, confidence=confidence,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


class TestGetStats:
    def test_empty_library(self):
        from app.routers.stats import get_stats

        db = _make_db()
        resp = get_stats(db)
        assert resp.totals.books == 0
        assert resp.totals.confirmed == 0
        assert resp.sources == []
        assert resp.top_authors == []

    def test_totals_aggregate_correctly(self):
        from app.routers.stats import get_stats

        db = _make_db()
        _add_book(db, is_confirmed=True, organize_status="copied")
        _add_book(db, is_confirmed=True, organize_status="pending")
        _add_book(db, is_confirmed=False, locked=True)
        _add_book(
            db, is_confirmed=True, organize_status="copied",
            purge_status="purged",
        )

        resp = get_stats(db)
        assert resp.totals.books == 4
        assert resp.totals.confirmed == 3
        assert resp.totals.organized == 2
        assert resp.totals.purged == 1
        assert resp.totals.locked == 1

    def test_top_authors_sorted_by_count(self):
        from app.routers.stats import get_stats

        db = _make_db()
        for _ in range(3):
            _add_book(db, author="Sanderson")
        for _ in range(2):
            _add_book(db, author="Jordan")
        _add_book(db, author="Hobb")
        # null author should be excluded
        _add_book(db, author=None)

        resp = get_stats(db)
        assert [(a.name, a.count) for a in resp.top_authors] == [
            ("Sanderson", 3), ("Jordan", 2), ("Hobb", 1),
        ]

    def test_by_decade_buckets_years(self):
        from app.routers.stats import get_stats

        db = _make_db()
        for y in ("2020", "2021", "2025"):
            _add_book(db, year=y, title=f"T{y}")
        for y in ("2010", "2015"):
            _add_book(db, year=y, title=f"T{y}")
        _add_book(db, year=None, title="no year")

        resp = get_stats(db)
        # 2020s = 3, 2010s = 2
        as_dict = {d.name: d.count for d in resp.by_decade}
        assert as_dict.get("2020s") == 3
        assert as_dict.get("2010s") == 2

    def test_edition_groups_use_standard_label_for_null(self):
        from app.routers.stats import get_stats

        db = _make_db()
        _add_book(db, edition=None, title="A")
        _add_book(db, edition=None, title="B")
        _add_book(db, edition="Graphic Audio", title="C")

        resp = get_stats(db)
        as_dict = {e.name: e.count for e in resp.editions}
        assert as_dict.get("Standard") == 2
        assert as_dict.get("Graphic Audio") == 1


class TestGetDuplicates:
    def test_no_duplicates(self):
        from app.routers.stats import get_duplicates

        db = _make_db()
        _add_book(db, title="A", author="X")
        _add_book(db, title="B", author="X")
        resp = get_duplicates(db)
        assert resp.groups == []

    def test_same_title_same_author_same_edition_groups(self):
        from app.routers.stats import get_duplicates

        db = _make_db()
        _add_book(db, title="The Way of Kings", author="Sanderson")
        _add_book(db, title="THE WAY OF KINGS", author="Sanderson")
        _add_book(db, title="Mistborn", author="Sanderson")

        resp = get_duplicates(db)
        assert len(resp.groups) == 1
        assert resp.groups[0].title == "The Way of Kings"
        assert len(resp.groups[0].books) == 2

    def test_different_editions_not_grouped(self):
        from app.routers.stats import get_duplicates

        db = _make_db()
        _add_book(db, title="Mistborn", author="Sanderson", edition=None)
        _add_book(db, title="Mistborn", author="Sanderson", edition="Graphic Audio")
        resp = get_duplicates(db)
        assert resp.groups == []

    def test_groups_sorted_by_size_desc(self):
        from app.routers.stats import get_duplicates

        db = _make_db()
        # Group A: 3 copies
        for _ in range(3):
            _add_book(db, title="A", author="Z")
        # Group B: 2 copies
        for _ in range(2):
            _add_book(db, title="B", author="Y")
        resp = get_duplicates(db)
        assert len(resp.groups) == 2
        assert len(resp.groups[0].books) == 3
        assert len(resp.groups[1].books) == 2


class TestResolveDuplicates:
    def test_resolve_removes_only_the_chosen_ids(self):
        from app.models.book import Book
        from app.routers.stats import (
            ResolveDuplicatesRequest, resolve_duplicates,
        )

        db = _make_db()
        keeper = _add_book(db, title="Same", author="Author")
        dup1 = _add_book(db, title="Same", author="Author")
        dup2 = _add_book(db, title="Same", author="Author")

        resp = resolve_duplicates(
            ResolveDuplicatesRequest(keep_id=keeper.id, delete_ids=[dup1.id, dup2.id]),
            db,
        )
        assert resp.deleted == 2
        ids = [b.id for b in db.query(Book).all()]
        assert ids == [keeper.id]

    def test_resolve_rejects_keep_id_in_delete_ids(self):
        from fastapi import HTTPException

        from app.routers.stats import (
            ResolveDuplicatesRequest, resolve_duplicates,
        )

        db = _make_db()
        book = _add_book(db)
        try:
            resolve_duplicates(
                ResolveDuplicatesRequest(keep_id=book.id, delete_ids=[book.id]),
                db,
            )
            assert False, "should have raised"
        except HTTPException as e:
            assert e.status_code == 400

    def test_resolve_rejects_empty_delete_ids(self):
        from fastapi import HTTPException

        from app.routers.stats import (
            ResolveDuplicatesRequest, resolve_duplicates,
        )

        db = _make_db()
        book = _add_book(db)
        try:
            resolve_duplicates(
                ResolveDuplicatesRequest(keep_id=book.id, delete_ids=[]),
                db,
            )
            assert False, "should have raised"
        except HTTPException as e:
            assert e.status_code == 400
