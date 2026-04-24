"""Tests for bulk-update, locked flag, and auto-lookup skip behavior.

Uses FastAPI's TestClient against an isolated in-memory SQLite DB. Auth
middleware is bypassed by not creating any users (the middleware only
protects routes once at least one user exists).
"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@contextmanager
def _test_client():
    """Build a TestClient wired to an in-memory DB.

    StaticPool + one connection so the seeding session and the
    HTTP-handler sessions share the same in-memory database (plain
    sqlite:///:memory: gives each connection its own isolated DB).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    from app.database import get_db
    from app.main import app
    from app.models import Base

    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        app.dependency_overrides.clear()


def _seed_books(session_factory, count=3) -> list[int]:
    """Create `count` books, return their IDs."""
    from app.models.book import Book
    from app.models.scan import Scan, ScannedFolder

    db = session_factory()
    scan = Scan(source_dir="/src", status="completed")
    db.add(scan)
    db.flush()
    ids = []
    for i in range(count):
        folder = ScannedFolder(
            scan_id=scan.id, folder_path=f"/src/book{i}", folder_name=f"book{i}"
        )
        db.add(folder)
        db.flush()
        book = Book(
            scanned_folder_id=folder.id,
            title=f"Title {i}",
            author="Original Author",
            source="parsed",
            confidence=0.5,
            parse_confidence=0.5,
        )
        db.add(book)
        db.flush()
        ids.append(book.id)
    db.commit()
    db.close()
    return ids


class TestBulkUpdate:
    def test_bulk_update_applies_patch_to_all(self):
        with _test_client() as (client, session):
            ids = _seed_books(session, 3)

            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {"author": "Brandon Sanderson"}},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["updated"] == 3
            assert body["field_counts"]["author"] == 3

            from app.models.book import Book

            db = session()
            try:
                authors = {b.author for b in db.query(Book).all()}
                assert authors == {"Brandon Sanderson"}
                # Source bumped to manual since this was a metadata edit
                sources = {b.source for b in db.query(Book).all()}
                assert sources == {"manual"}
            finally:
                db.close()

    def test_bulk_update_ignores_unknown_fields(self):
        with _test_client() as (client, session):
            ids = _seed_books(session, 2)

            resp = client.post(
                "/api/books/bulk-update",
                json={
                    "book_ids": ids,
                    "patch": {
                        "author": "Real Author",
                        "title": "Should Be Ignored",  # title NOT in allowlist
                        "random_field": "nope",
                    },
                },
            )
            assert resp.status_code == 200

            from app.models.book import Book

            db = session()
            try:
                books = db.query(Book).all()
                # Author applied
                assert all(b.author == "Real Author" for b in books)
                # Titles unchanged
                assert {b.title for b in books} == {"Title 0", "Title 1"}
            finally:
                db.close()

    def test_empty_string_clears_field(self):
        """User typing an empty value should clear (set to None) the field."""
        with _test_client() as (client, session):
            ids = _seed_books(session, 1)
            # First set a series so we can clear it
            client.patch(f"/api/books/{ids[0]}", json={"series": "Stormlight"})

            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {"series": ""}},
            )
            assert resp.status_code == 200

            from app.models.book import Book

            db = session()
            try:
                book = db.query(Book).filter(Book.id == ids[0]).first()
                assert book.series is None
            finally:
                db.close()

    def test_flags_only_patch_does_not_bump_source(self):
        """Confirming/locking in bulk shouldn't claim the user edited fields."""
        with _test_client() as (client, session):
            ids = _seed_books(session, 2)

            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {"is_confirmed": True}},
            )
            assert resp.status_code == 200
            assert resp.json()["updated"] == 2

            from app.models.book import Book

            db = session()
            try:
                for b in db.query(Book).all():
                    assert b.is_confirmed is True
                    # Source stays "parsed" because only flag changed
                    assert b.source == "parsed"
            finally:
                db.close()

    def test_bulk_lock_via_patch(self):
        """locked=True via bulk-update should freeze the books."""
        with _test_client() as (client, session):
            ids = _seed_books(session, 2)

            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {"locked": True}},
            )
            assert resp.status_code == 200

            from app.models.book import Book

            db = session()
            try:
                for b in db.query(Book).all():
                    assert b.locked is True
            finally:
                db.close()

    def test_empty_patch_rejected(self):
        with _test_client() as (client, session):
            ids = _seed_books(session, 1)
            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {}},
            )
            assert resp.status_code == 400

    def test_empty_book_ids_rejected(self):
        with _test_client() as (client, _session):
            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": [], "patch": {"author": "X"}},
            )
            assert resp.status_code == 400

    def test_all_unsafe_keys_rejected(self):
        """If patch has only disallowed keys, return 400."""
        with _test_client() as (client, session):
            ids = _seed_books(session, 1)
            resp = client.post(
                "/api/books/bulk-update",
                json={
                    "book_ids": ids,
                    "patch": {"title": "Bad", "confidence": "nope"},  # both unsafe
                },
            )
            assert resp.status_code == 400
            assert "allowed" in resp.json()["detail"].lower()

    def test_field_counts_only_count_actual_changes(self):
        """If a field already has the target value, don't double-count it."""
        with _test_client() as (client, session):
            ids = _seed_books(session, 3)

            # Books start with author="Original Author"
            resp = client.post(
                "/api/books/bulk-update",
                json={"book_ids": ids, "patch": {"author": "Original Author"}},
            )
            body = resp.json()
            # No actual change on any book
            assert body["updated"] == 0
            assert body["field_counts"]["author"] == 0


class TestLockFlag:
    def test_lock_unlock_endpoints(self):
        with _test_client() as (client, session):
            ids = _seed_books(session, 1)

            resp = client.post(f"/api/books/{ids[0]}/lock")
            assert resp.status_code == 200
            assert resp.json()["locked"] is True

            resp = client.post(f"/api/books/{ids[0]}/unlock")
            assert resp.status_code == 200
            assert resp.json()["locked"] is False

    def test_lock_nonexistent_404(self):
        with _test_client() as (client, _session):
            resp = client.post("/api/books/99999/lock")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_locked_book_not_auto_applied(self, monkeypatch):
        """A locked book should receive candidates but never auto-apply."""
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        with _test_client() as (_client, session):
            db = session()
            try:
                book = Book(
                    title="The Way of Kings",
                    author="Brandon Sanderson",
                    source="parsed",
                    confidence=0.5,
                    parse_confidence=0.5,
                    locked=True,
                )
                db.add(book)
                db.commit()

                async def fake_lookup(title, author, api_key, db_arg):
                    return [
                        LookupResult(
                            provider="audible",
                            title="The Way of Kings",
                            author="Brandon Sanderson",
                            series=None, series_position=None, year=None,
                            narrator=None, description=None, cover_url=None,
                            confidence=0.92,
                        ),
                    ]
                monkeypatch.setattr("app.services.candidates.lookup_book", fake_lookup)

                # auto_apply=True is requested, but book.locked should override.
                candidates = await refresh_candidates(book, db, auto_apply=True)

                assert len(candidates) == 1
                # Candidate exists but none is applied
                assert all(not c.applied for c in candidates)
                db.refresh(book)
                assert book.source == "parsed"
                assert book.match_confidence == 0.0
                # But the candidate row is persisted so user can apply manually
                assert db.query(LookupCandidate).count() == 1
            finally:
                db.close()


class TestRescanRespectsLock:
    def test_carry_forward_preserves_locked(self):
        """When the user locked a book and a new scan happens at the same
        folder path, the locked flag AND the edited fields should survive.
        """
        from app.models.book import Book
        from app.models.scan import Scan, ScannedFolder
        from app.services.scanner import _carry_forward_manual_edits

        with _test_client() as (_client, session):
            db = session()
            try:
                # Prior scan with a locked book
                prior = Scan(source_dir="/x", status="completed")
                db.add(prior)
                db.flush()
                prior_folder = ScannedFolder(
                    scan_id=prior.id, folder_path="/x/b1", folder_name="b1"
                )
                db.add(prior_folder)
                db.flush()
                prior_book = Book(
                    scanned_folder_id=prior_folder.id,
                    title="Correct Title",
                    author="Correct Author",
                    locked=True,
                    source="manual",
                    confidence=0.5,
                    parse_confidence=0.5,
                )
                db.add(prior_book)
                db.commit()

                # New scan at the same folder path with different parse
                new_scan = Scan(source_dir="/x", status="running")
                db.add(new_scan)
                db.flush()
                new_folder = ScannedFolder(
                    scan_id=new_scan.id, folder_path="/x/b1", folder_name="b1"
                )
                db.add(new_folder)
                db.flush()
                new_book = Book(
                    scanned_folder_id=new_folder.id,
                    title="Wrong Parser Title",
                    author="Wrong Parser Author",
                    source="parsed",
                    confidence=0.3,
                    parse_confidence=0.3,
                )
                db.add(new_book)
                db.commit()

                _carry_forward_manual_edits(new_scan, db)

                db.refresh(new_book)
                # Locked flag carried over
                assert new_book.locked is True
                # User's values carried over
                assert new_book.title == "Correct Title"
                assert new_book.author == "Correct Author"
                assert new_book.source == "manual"
            finally:
                db.close()
