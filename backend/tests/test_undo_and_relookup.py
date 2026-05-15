"""Tests for PR 5: undo_organize endpoint + bulk re-lookup."""

import os

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


def _make_organized_book(db, tmp_path, *, source_present=True, dest_present=True):
    """Same fixture pattern as test_purge_and_delete.py."""
    from app.models.book import Book, BookFile
    from app.models.scan import Scan, ScannedFolder

    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    dst_dir = tmp_path / "out" / "Author" / "Title"
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_file = src_dir / "chapter01.mp3"
    dst_file = dst_dir / "chapter01.mp3"

    payload = b"audio" * 100
    if source_present:
        src_file.write_bytes(payload)
    if dest_present:
        dst_file.write_bytes(payload)
        # Also drop a sidecar + cover.jpg in dst_dir so the undo path
        # exercises the cleanup branches.
        (dst_dir / ".audiobook-organizer.json").write_text("{}", encoding="utf-8")
        (dst_dir / "cover.jpg").write_bytes(b"jpeg")

    scan = Scan(source_dir=str(src_dir), status="completed")
    db.add(scan)
    db.flush()
    sf = ScannedFolder(
        scan_id=scan.id, folder_path=str(src_dir),
        folder_name="src", status="processed",
    )
    db.add(sf)
    db.flush()

    book = Book(
        scanned_folder_id=sf.id, title="T", author="A",
        source="parsed", confidence=0.5, is_confirmed=True,
        organize_status="copied", output_path=str(dst_dir),
        purge_status="not_purged",
    )
    db.add(book)
    db.flush()

    bf = BookFile(
        book_id=book.id, original_path=str(src_file),
        filename="chapter01.mp3", file_size=len(payload), file_format="mp3",
        destination_path=str(dst_file), copy_status="copied",
    )
    db.add(bf)
    db.commit()
    db.refresh(book)
    return book, src_file, dst_file, dst_dir


class TestUndoOrganize:
    def test_undo_removes_dest_and_resets_to_pending(self, tmp_path):
        from app.routers.organize import (
            UndoOrganizeRequest, undo_organize,
        )

        db = _make_db()
        book, src_file, dst_file, dst_dir = _make_organized_book(db, tmp_path)
        assert dst_file.exists()
        assert (dst_dir / "cover.jpg").exists()

        resp = undo_organize(UndoOrganizeRequest(book_ids=[book.id]), db)
        result = resp.results[0]
        assert result.success
        assert result.files_removed == 1

        db.refresh(book)
        assert book.organize_status == "pending"
        assert book.output_path is None
        assert book.files[0].destination_path is None
        assert book.files[0].copy_status == "pending"

        # Files
        assert src_file.exists()  # source untouched
        assert not dst_file.exists()  # copy removed
        # Sidecar + cover cleaned up; empty dir removed
        assert not (dst_dir / "cover.jpg").exists()
        assert not dst_dir.exists()

    def test_undo_refused_when_source_missing(self, tmp_path):
        from app.routers.organize import (
            UndoOrganizeRequest, undo_organize,
        )

        db = _make_db()
        book, src_file, dst_file, _ = _make_organized_book(
            db, tmp_path, source_present=False,
        )
        assert not src_file.exists()
        assert dst_file.exists()

        resp = undo_organize(UndoOrganizeRequest(book_ids=[book.id]), db)
        result = resp.results[0]
        assert not result.success
        assert "source file" in (result.error or "").lower()
        # Destination preserved — we never lose the only copy.
        assert dst_file.exists()
        db.refresh(book)
        assert book.organize_status == "copied"

    def test_undo_skipped_for_purged_books(self, tmp_path):
        from app.routers.organize import (
            UndoOrganizeRequest, undo_organize,
        )

        db = _make_db()
        book, _, _, _ = _make_organized_book(db, tmp_path)
        book.purge_status = "purged"
        db.commit()

        resp = undo_organize(UndoOrganizeRequest(book_ids=[book.id]), db)
        result = resp.results[0]
        assert not result.success
        assert "purged" in (result.error or "").lower()

    def test_undo_keeps_non_empty_output_dir(self, tmp_path):
        from app.routers.organize import (
            UndoOrganizeRequest, undo_organize,
        )

        db = _make_db()
        book, _, dst_file, dst_dir = _make_organized_book(db, tmp_path)
        # User dropped an unrelated file in the output dir.
        (dst_dir / "user_notes.txt").write_text("keep me", encoding="utf-8")

        undo_organize(UndoOrganizeRequest(book_ids=[book.id]), db)

        # Audio + sidecar + cover removed, but the user's file stays.
        assert not dst_file.exists()
        assert (dst_dir / "user_notes.txt").exists()
        assert dst_dir.exists()


class TestRelookupBatch:
    def test_relookup_batch_requires_book_ids(self):
        import asyncio

        from fastapi import HTTPException

        from app.routers.books import RelookupBatchRequest, relookup_batch

        db = _make_db()
        try:
            asyncio.run(
                relookup_batch(RelookupBatchRequest(book_ids=[]), db=db)
            )
            assert False, "should have raised"
        except HTTPException as e:
            assert e.status_code == 400

    def test_relookup_batch_processes_books(self, monkeypatch):
        """We don't want to hit the network — stub refresh_candidates
        out and just verify counts.

        relookup_batch creates fresh SessionLocal() instances per task,
        so we need the test's in-memory engine to be visible from
        SessionLocal too. We accomplish this by patching SessionLocal
        in app.database to point at the same engine our test session
        is using.
        """
        import asyncio

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401
        from app import database as db_mod
        from app.routers.books import RelookupBatchRequest, relookup_batch
        from app.services import candidates as candidates_mod
        from app.models.book import Book

        # Single engine shared by both the route-handler's SessionLocal
        # AND our test session — guarantees they see the same data.
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr(db_mod, "SessionLocal", Session)

        db = Session()
        b1 = Book(title="X", author="A", source="parsed", confidence=0.5)
        b2 = Book(title="Y", author="B", source="parsed", confidence=0.5)
        db.add_all([b1, b2])
        db.commit()
        db.refresh(b1)
        db.refresh(b2)

        async def _fake_refresh(*args, **kwargs):
            return []

        monkeypatch.setattr(candidates_mod, "refresh_candidates", _fake_refresh)

        resp = asyncio.run(
            relookup_batch(
                RelookupBatchRequest(book_ids=[b1.id, b2.id], auto_apply=True),
                db=db,
            )
        )
        assert resp.processed == 2
        assert resp.total == 2
        assert resp.failed == 0
