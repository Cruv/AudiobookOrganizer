"""Tests for PR 4: cover.jpg download during organize + cover_url
attached to BookResponse.
"""

import os

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


def _make_book_with_candidates(db, *, applied_cover=None, fallback_cover=None, rejected_cover=None):
    """Build a book with up to three candidates so cover-pick logic can
    be exercised end-to-end."""
    from app.models.book import Book
    from app.models.lookup_candidate import LookupCandidate

    b = Book(
        title="T", author="A", source="parsed",
        confidence=0.5, is_confirmed=True, organize_status="pending",
    )
    db.add(b)
    db.flush()

    if applied_cover is not None:
        db.add(LookupCandidate(
            book_id=b.id, provider="audible", title="X",
            cover_url=applied_cover, applied=True, ranking_score=0.9,
        ))
    if fallback_cover is not None:
        db.add(LookupCandidate(
            book_id=b.id, provider="itunes", title="Y",
            cover_url=fallback_cover, applied=False, ranking_score=0.7,
        ))
    if rejected_cover is not None:
        db.add(LookupCandidate(
            book_id=b.id, provider="openlibrary", title="Z",
            cover_url=rejected_cover, applied=False, rejected=True,
            ranking_score=0.6,
        ))
    db.commit()
    db.refresh(b)
    return b


class TestPickCoverUrl:
    def test_prefers_applied_candidate(self):
        from app.services.organizer import _pick_cover_url

        db = _make_db()
        book = _make_book_with_candidates(
            db,
            applied_cover="https://x.test/applied.jpg",
            fallback_cover="https://x.test/fallback.jpg",
        )
        assert _pick_cover_url(book) == "https://x.test/applied.jpg"

    def test_uses_fallback_when_no_applied(self):
        from app.services.organizer import _pick_cover_url

        db = _make_db()
        book = _make_book_with_candidates(
            db, fallback_cover="https://x.test/fallback.jpg",
        )
        assert _pick_cover_url(book) == "https://x.test/fallback.jpg"

    def test_skips_rejected_even_if_only_option(self):
        from app.services.organizer import _pick_cover_url

        db = _make_db()
        book = _make_book_with_candidates(
            db, rejected_cover="https://x.test/rejected.jpg",
        )
        assert _pick_cover_url(book) is None

    def test_returns_none_when_no_candidates(self):
        from app.services.organizer import _pick_cover_url

        db = _make_db()
        book = _make_book_with_candidates(db)
        assert _pick_cover_url(book) is None


class TestDownloadCoverArt:
    def test_downloads_to_cover_jpg_when_url_present(self, tmp_path, monkeypatch):
        """Mock httpx so we don't hit the network — verify the file
        lands at <output_dir>/cover.jpg with the mocked bytes."""
        from app.services import organizer

        db = _make_db()
        book = _make_book_with_candidates(
            db, applied_cover="https://covers.test/foo.jpg",
        )

        # Monkeypatch httpx.Client used inside _download_cover_art.
        class _MockResp:
            content = b"\x89PNG\r\n\x1a\nimg-bytes-here"
            headers = {"content-type": "image/jpeg"}

            def raise_for_status(self):
                pass

        class _MockClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return _MockResp()

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "Client", _MockClient)

        out = tmp_path / "Author" / "Title"
        out.mkdir(parents=True)
        organizer._download_cover_art(book, str(out))

        cover_path = out / "cover.jpg"
        assert cover_path.exists()
        assert cover_path.read_bytes() == _MockResp.content
        # Staging artifact should be cleaned up.
        assert not any(out.glob(f"*{organizer.STAGING_SUFFIX}"))

    def test_no_op_when_book_has_no_cover_url(self, tmp_path):
        from app.services import organizer

        db = _make_db()
        book = _make_book_with_candidates(db)

        out = tmp_path / "out"
        out.mkdir()
        organizer._download_cover_art(book, str(out))
        assert not (out / "cover.jpg").exists()

    def test_no_op_when_cover_already_exists(self, tmp_path):
        """Don't overwrite a cover the user (or another tool) placed."""
        from app.services import organizer

        db = _make_db()
        book = _make_book_with_candidates(
            db, applied_cover="https://covers.test/foo.jpg",
        )

        out = tmp_path / "out"
        out.mkdir()
        existing = out / "cover.jpg"
        existing.write_bytes(b"manual cover")

        organizer._download_cover_art(book, str(out))
        # Existing bytes preserved.
        assert existing.read_bytes() == b"manual cover"


class TestBookResponseCoverUrl:
    def test_cover_url_attached_to_book_response(self):
        from app.routers.books import _attach_book_info
        from app.schemas.book import BookResponse

        db = _make_db()
        book = _make_book_with_candidates(
            db,
            applied_cover="https://example.com/applied.jpg",
            fallback_cover="https://example.com/fallback.jpg",
        )
        resp = BookResponse.model_validate(book)
        _attach_book_info(book, resp, db, pattern="{Title}", root="/x")
        assert resp.cover_url == "https://example.com/applied.jpg"

    def test_cover_url_falls_back_to_highest_ranking_non_rejected(self):
        from app.routers.books import _attach_book_info
        from app.schemas.book import BookResponse

        db = _make_db()
        book = _make_book_with_candidates(
            db,
            fallback_cover="https://example.com/fallback.jpg",
            rejected_cover="https://example.com/rejected.jpg",
        )
        resp = BookResponse.model_validate(book)
        _attach_book_info(book, resp, db, pattern="{Title}", root="/x")
        assert resp.cover_url == "https://example.com/fallback.jpg"

    def test_cover_url_none_when_no_candidates(self):
        from app.routers.books import _attach_book_info
        from app.schemas.book import BookResponse

        db = _make_db()
        book = _make_book_with_candidates(db)
        resp = BookResponse.model_validate(book)
        _attach_book_info(book, resp, db, pattern="{Title}", root="/x")
        assert resp.cover_url is None


class TestCoverEndpoint:
    def test_returns_404_when_no_output_path(self):
        from fastapi import HTTPException

        from app.routers.books import get_book_cover

        db = _make_db()
        book = _make_book_with_candidates(db)
        with pytest.raises(HTTPException) as exc_info:
            get_book_cover(book.id, db)
        assert exc_info.value.status_code == 404

    def test_returns_404_when_cover_jpg_missing(self, tmp_path):
        from fastapi import HTTPException

        from app.routers.books import get_book_cover

        db = _make_db()
        book = _make_book_with_candidates(db)
        book.output_path = str(tmp_path)
        # No cover.jpg in tmp_path
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            get_book_cover(book.id, db)
        assert exc_info.value.status_code == 404

    def test_serves_cover_jpg_when_present(self, tmp_path):
        from app.routers.books import get_book_cover

        db = _make_db()
        book = _make_book_with_candidates(db)
        book.output_path = str(tmp_path)
        db.commit()

        (tmp_path / "cover.jpg").write_bytes(b"jpegbytes")

        resp = get_book_cover(book.id, db)
        # FileResponse — verify it points at our file.
        assert os.path.basename(resp.path) == "cover.jpg"
