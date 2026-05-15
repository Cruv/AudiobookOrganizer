"""Tests for the purge bug fix and the new DELETE /api/books/{id}
endpoint.

The original bug: when source files were deleted externally between
organize and purge, the user got stuck — verification would fail
because of file-size or destination checks, and there was no way to
remove the orphan record from the UI.

These tests cover the resolved behaviors:
 - verify_book passes when the ORIGINAL is gone but destination is OK
 - verify_book fails when the DESTINATION is gone (intentional safety)
 - purge_book(force=True) marks the book purged regardless
 - delete_book wipes the Book + cascade + the ScannedFolder so the
   record is fully gone and won't be re-imported on the next scan
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_db():
    from app.models.base import Base
    # Touch all models so create_all registers their tables.
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


def _make_organized_book(db, tmp_path, *, original_present=True, destination_present=True):
    """Build a fully-organized book with one BookFile and known source/dest."""
    from app.models.book import Book, BookFile
    from app.models.scan import Scan, ScannedFolder

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "out" / "Author" / "Title"
    dst_dir.mkdir(parents=True)

    src_file = src_dir / "chapter01.mp3"
    dst_file = dst_dir / "chapter01.mp3"

    payload = b"audio" * 200  # 1000 bytes
    if original_present:
        src_file.write_bytes(payload)
    if destination_present:
        dst_file.write_bytes(payload)

    scan = Scan(source_dir=str(src_dir), status="completed")
    db.add(scan)
    db.flush()

    sf = ScannedFolder(
        scan_id=scan.id,
        folder_path=str(src_dir),
        folder_name="src",
        status="processed",
    )
    db.add(sf)
    db.flush()

    book = Book(
        scanned_folder_id=sf.id,
        title="Test",
        author="Auth",
        source="parsed",
        confidence=0.5,
        is_confirmed=True,
        organize_status="copied",
        output_path=str(dst_dir),
        purge_status="not_purged",
    )
    db.add(book)
    db.flush()

    bf = BookFile(
        book_id=book.id,
        original_path=str(src_file),
        filename="chapter01.mp3",
        file_size=len(payload),
        file_format="mp3",
        destination_path=str(dst_file),
        copy_status="copied",
    )
    db.add(bf)
    db.commit()

    db.refresh(book)
    return book


class TestVerifyBookMissingFiles:
    def test_original_missing_destination_present_verifies(self, tmp_path):
        """The user deleted source files manually. Verification should
        still succeed — there's nothing left to purge but the safety
        check (destination must exist) is satisfied."""
        from app.services.purger import verify_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=False, destination_present=True,
        )

        result = verify_book(book)
        assert result.verified is True
        assert result.missing_files == []

    def test_destination_missing_fails_verification(self, tmp_path):
        """Destination gone is the unsafe case: we don't know if the
        copy was ever good. Refuse to purge originals."""
        from app.services.purger import verify_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=True, destination_present=False,
        )

        result = verify_book(book)
        assert result.verified is False
        assert any("destination file missing" in m for m in result.missing_files)

    def test_both_missing_fails_verification(self, tmp_path):
        """If both are gone, verify still flags the destination (since
        that's the safety-critical check). The recovery path is the
        DELETE endpoint."""
        from app.services.purger import verify_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=False, destination_present=False,
        )

        result = verify_book(book)
        assert result.verified is False


class TestPurgeBookHandlesMissingOriginals:
    def test_purge_succeeds_when_original_gone(self, tmp_path):
        """The common case: user cleaned up sources between organize
        and purge. Purge should still mark the book purged so it
        leaves the list."""
        from app.services.purger import purge_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=False, destination_present=True,
        )

        result = purge_book(book, db)
        assert result.success is True
        assert result.files_deleted == 0  # nothing on disk to delete

        db.refresh(book)
        assert book.purge_status == "purged"
        assert book.files[0].copy_status == "purged"

    def test_force_purge_succeeds_when_destination_missing(self, tmp_path):
        """Force-purge bypasses verification — used when the user knows
        files are gone but wants the DB to reflect it."""
        from app.services.purger import purge_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=False, destination_present=False,
        )

        result = purge_book(book, db, force=True)
        assert result.success is True

        db.refresh(book)
        assert book.purge_status == "purged"

    def test_non_force_purge_blocked_when_destination_missing(self, tmp_path):
        """Without force, the safety check still applies."""
        from app.services.purger import purge_book

        db = _make_db()
        book = _make_organized_book(
            db, tmp_path, original_present=True, destination_present=False,
        )

        result = purge_book(book, db)
        assert result.success is False
        assert result.error and "destination file missing" in result.error


class TestDeleteBookEndpoint:
    """Cover the new DELETE /api/books/{id} flow at the function level
    (we test the router function directly to avoid having to spin up a
    full FastAPI test client + auth middleware here)."""

    def test_delete_removes_book_and_scanned_folder(self, tmp_path):
        from app.models.book import Book, BookFile
        from app.models.scan import ScannedFolder
        from app.routers.books import delete_book

        db = _make_db()
        book = _make_organized_book(db, tmp_path)
        book_id = book.id
        sf_id = book.scanned_folder_id

        result = delete_book(book_id, db)
        assert result == {"detail": "Book removed"}

        # Book gone
        assert db.query(Book).filter(Book.id == book_id).first() is None
        # BookFiles cascade-deleted
        assert db.query(BookFile).filter(BookFile.book_id == book_id).count() == 0
        # ScannedFolder also gone (so a future scan doesn't re-import it)
        assert db.query(ScannedFolder).filter(ScannedFolder.id == sf_id).first() is None

    def test_delete_does_not_touch_files_on_disk(self, tmp_path):
        from app.routers.books import delete_book

        db = _make_db()
        book = _make_organized_book(db, tmp_path)
        src_path = book.files[0].original_path
        dst_path = book.files[0].destination_path

        import os
        assert os.path.exists(src_path)
        assert os.path.exists(dst_path)

        delete_book(book.id, db)

        # Both files survive — DELETE is metadata only.
        assert os.path.exists(src_path)
        assert os.path.exists(dst_path)

    def test_delete_returns_404_for_missing_book(self):
        from fastapi import HTTPException

        from app.routers.books import delete_book

        db = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            delete_book(999, db)
        assert exc_info.value.status_code == 404
