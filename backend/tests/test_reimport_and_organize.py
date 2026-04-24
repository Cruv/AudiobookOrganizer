"""Tests for Phase 3 changes: preflight, staged copy, sidecar write, and
re-import from sidecars. Uses tmp_path throughout so no real FS touched
beyond the test's own temp dir.
"""

import json
import os
from types import SimpleNamespace

import pytest

from app.services.organizer import (
    InsufficientDiskSpaceError,
    SIDECAR_FILENAME,
    STAGING_SUFFIX,
    _write_sidecar,
    preflight_disk_space,
)


# --- preflight ---------------------------------------------------------

class TestPreflight:
    def test_passes_when_enough_free(self, tmp_path):
        # tmp_path lives on the test machine, which has gigs free — a
        # request for 1KB should always pass.
        preflight_disk_space(str(tmp_path), required_bytes=1024)

    def test_raises_when_requirement_exceeds_disk(self, tmp_path):
        # Request 10 exabytes — nothing has that much.
        with pytest.raises(InsufficientDiskSpaceError) as exc_info:
            preflight_disk_space(str(tmp_path), required_bytes=10 * 2**60)
        err = exc_info.value
        assert err.required > err.available
        assert err.path == str(tmp_path)

    def test_creates_missing_directory(self, tmp_path):
        new_dir = tmp_path / "not_yet_created"
        preflight_disk_space(str(new_dir), required_bytes=1)
        assert new_dir.is_dir()


# --- sidecar write -----------------------------------------------------

def _fake_book(tmp_path, files):
    """Build a minimal duck-typed Book for _write_sidecar."""
    scanned_folder = SimpleNamespace(folder_path=str(tmp_path / "source"))
    book = SimpleNamespace(
        id=1,
        title="Test Title",
        author="Test Author",
        series="Test Series",
        series_position="1",
        year="2020",
        narrator="Test Narrator",
        edition=None,
        source="manual",
        confidence=0.91,
        is_confirmed=True,
        scanned_folder=scanned_folder,
        files=files,
    )
    return book


class TestSidecar:
    def test_writes_valid_json(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        files = [
            SimpleNamespace(
                filename="01.mp3",
                file_size=1234,
                original_path=str(tmp_path / "source" / "01.mp3"),
                copy_status="copied",
                tag_title="Chapter 1",
                tag_author=None,
                tag_album="Test Title",
                tag_year="2020",
                tag_narrator=None,
            ),
        ]
        book = _fake_book(tmp_path, files)

        _write_sidecar(book, str(out))

        sidecar = out / SIDECAR_FILENAME
        assert sidecar.exists()
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert data["book"]["title"] == "Test Title"
        assert data["book"]["is_confirmed"] is True
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "01.mp3"
        assert data["source_folder"].endswith("source")

    def test_skips_failed_files(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        files = [
            SimpleNamespace(
                filename="good.mp3", file_size=100, original_path="/x/good.mp3",
                copy_status="copied", tag_title=None, tag_author=None,
                tag_album=None, tag_year=None, tag_narrator=None,
            ),
            SimpleNamespace(
                filename="bad.mp3", file_size=200, original_path="/x/bad.mp3",
                copy_status="failed", tag_title=None, tag_author=None,
                tag_album=None, tag_year=None, tag_narrator=None,
            ),
        ]
        book = _fake_book(tmp_path, files)
        _write_sidecar(book, str(out))

        data = json.loads((out / SIDECAR_FILENAME).read_text(encoding="utf-8"))
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "good.mp3"

    def test_atomic_tmp_renamed(self, tmp_path):
        """After writing, there should be no .tmp artifact left behind."""
        out = tmp_path / "out"
        out.mkdir()
        files = [
            SimpleNamespace(
                filename="a.mp3", file_size=1, original_path="/x/a.mp3",
                copy_status="copied", tag_title=None, tag_author=None,
                tag_album=None, tag_year=None, tag_narrator=None,
            ),
        ]
        book = _fake_book(tmp_path, files)
        _write_sidecar(book, str(out))

        tmps = list(out.glob("*.tmp"))
        assert tmps == []


# --- reimport ----------------------------------------------------------

class TestReimportFindsSidecars:
    """We test _find_sidecars and _reimport_one without a real DB by
    using an in-memory SQLite. This keeps the test focused on the
    filesystem-walking and JSON-parsing logic.
    """

    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        # Import models so tables are registered with Base metadata.
        import app.models.book  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    def test_finds_nested_sidecars(self, tmp_path):
        from app.services.reimport import _find_sidecars

        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "b" / SIDECAR_FILENAME).write_text("{}", encoding="utf-8")
        (tmp_path / "c").mkdir()
        (tmp_path / "c" / SIDECAR_FILENAME).write_text("{}", encoding="utf-8")
        (tmp_path / "d").mkdir()  # no sidecar

        results = _find_sidecars(str(tmp_path))
        assert len(results) == 2
        assert all(r.endswith(SIDECAR_FILENAME) for r in results)

    def test_reimport_creates_book_from_sidecar(self, tmp_path):
        from app.models.book import Book
        from app.models.scan import ScannedFolder
        from app.services.reimport import reimport_from_sidecars

        # Arrange: organized book dir with a real file + sidecar
        book_dir = tmp_path / "Author" / "Title"
        book_dir.mkdir(parents=True)
        audio_path = book_dir / "track01.mp3"
        audio_path.write_bytes(b"x" * 500)

        sidecar = {
            "schema_version": 1,
            "organized_at": "2026-04-23T00:00:00+00:00",
            "source_folder": "/srv/source/original",
            "book": {
                "title": "Reimported Title",
                "author": "Reimported Author",
                "series": None,
                "series_position": None,
                "year": "2022",
                "narrator": None,
                "edition": None,
                "source": "manual",
                "confidence": 0.88,
                "is_confirmed": True,
            },
            "files": [
                {
                    "filename": "track01.mp3",
                    "size": 500,
                    "original_path": "/srv/source/original/track01.mp3",
                    "tag_title": None,
                    "tag_author": None,
                    "tag_album": None,
                    "tag_year": None,
                    "tag_narrator": None,
                },
            ],
        }
        (book_dir / SIDECAR_FILENAME).write_text(
            json.dumps(sidecar), encoding="utf-8"
        )

        # Act
        db = self._make_db()
        scan = reimport_from_sidecars(str(tmp_path), db)

        # Assert
        assert scan.status == "completed"
        assert scan.processed_folders == 1

        folders = db.query(ScannedFolder).all()
        assert len(folders) == 1
        assert folders[0].status == "reimported"

        books = db.query(Book).all()
        assert len(books) == 1
        b = books[0]
        assert b.title == "Reimported Title"
        assert b.is_confirmed is True
        assert b.organize_status == "copied"
        assert b.output_path == str(book_dir)
        assert len(b.files) == 1
        # File exists on disk, so copy_status should be "copied", not "missing"
        assert b.files[0].copy_status == "copied"

    def test_reimport_marks_missing_files(self, tmp_path):
        from app.models.book import Book
        from app.services.reimport import reimport_from_sidecars

        book_dir = tmp_path / "Author" / "Title"
        book_dir.mkdir(parents=True)
        # Sidecar references a file that doesn't exist
        sidecar = {
            "schema_version": 1,
            "book": {"title": "T", "author": "A", "series": None,
                     "series_position": None, "year": None, "narrator": None,
                     "edition": None, "source": "manual", "confidence": 0.5,
                     "is_confirmed": False},
            "files": [{"filename": "gone.mp3", "size": 1,
                       "original_path": "/x/gone.mp3"}],
        }
        (book_dir / SIDECAR_FILENAME).write_text(
            json.dumps(sidecar), encoding="utf-8"
        )

        db = self._make_db()
        reimport_from_sidecars(str(tmp_path), db)

        books = db.query(Book).all()
        assert len(books) == 1
        assert books[0].files[0].copy_status == "missing"

    def test_reimport_rejects_unknown_schema_version(self, tmp_path):
        from app.models.book import Book
        from app.models.scan import ScannedFolder
        from app.services.reimport import reimport_from_sidecars

        book_dir = tmp_path / "book"
        book_dir.mkdir()
        (book_dir / SIDECAR_FILENAME).write_text(
            json.dumps({"schema_version": 99, "book": {}, "files": []}),
            encoding="utf-8",
        )

        db = self._make_db()
        reimport_from_sidecars(str(tmp_path), db)

        # Should be skipped, not imported
        assert db.query(Book).count() == 0
        # The folder is recorded as skipped with an error
        folders = db.query(ScannedFolder).all()
        assert len(folders) == 1
        assert folders[0].status == "skipped"
        assert folders[0].error_message is not None

    def test_reimport_handles_malformed_json(self, tmp_path):
        """A corrupt sidecar file should fail soft: folder marked skipped,
        other books still import, overall scan still completes."""
        from app.models.book import Book
        from app.models.scan import ScannedFolder
        from app.services.reimport import reimport_from_sidecars

        # Corrupt sidecar
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / SIDECAR_FILENAME).write_text(
            "{ this is not valid json",
            encoding="utf-8",
        )

        # Valid sidecar alongside it
        good_dir = tmp_path / "good"
        good_dir.mkdir()
        (good_dir / "audio.mp3").write_bytes(b"x")
        (good_dir / SIDECAR_FILENAME).write_text(
            json.dumps({
                "schema_version": 1,
                "book": {"title": "Good Book", "author": "Good Author"},
                "files": [{"filename": "audio.mp3", "size": 1,
                           "original_path": "/x/audio.mp3"}],
            }),
            encoding="utf-8",
        )

        db = self._make_db()
        scan = reimport_from_sidecars(str(tmp_path), db)

        assert scan.status == "completed"
        # Good book imported; bad folder marked skipped with error
        books = db.query(Book).all()
        assert len(books) == 1
        assert books[0].title == "Good Book"

        skipped = db.query(ScannedFolder).filter(ScannedFolder.status == "skipped").all()
        assert len(skipped) == 1
        assert "JSONDecodeError" in (skipped[0].error_message or "")


# --- staging suffix constant is exported ------------------------------

def test_staging_suffix_is_distinctive():
    """The staging suffix needs to be unlikely to collide with real
    filenames, so it includes the project name."""
    assert "audiobook-organizer" in STAGING_SUFFIX


# --- startup cleanup of orphaned staging files ------------------------

class TestStagingCleanup:
    def test_removes_orphaned_staging_files(self, tmp_path):
        from app.services.organizer import cleanup_orphan_staging_files

        # Nested structure with some real files and some staging artifacts
        (tmp_path / "Author" / "Book").mkdir(parents=True)
        real = tmp_path / "Author" / "Book" / "chapter.mp3"
        real.write_bytes(b"real")
        orphan1 = tmp_path / "Author" / "Book" / f"chapter.mp3{STAGING_SUFFIX}"
        orphan1.write_bytes(b"partial")
        orphan2 = tmp_path / "Author" / f"cover.jpg{STAGING_SUFFIX}"
        orphan2.write_bytes(b"partial")

        removed = cleanup_orphan_staging_files(str(tmp_path))

        assert removed == 2
        assert real.exists()  # real files untouched
        assert not orphan1.exists()
        assert not orphan2.exists()

    def test_missing_output_root_returns_zero(self, tmp_path):
        from app.services.organizer import cleanup_orphan_staging_files

        fake = str(tmp_path / "does_not_exist")
        assert cleanup_orphan_staging_files(fake) == 0

    def test_empty_dir_returns_zero(self, tmp_path):
        from app.services.organizer import cleanup_orphan_staging_files

        assert cleanup_orphan_staging_files(str(tmp_path)) == 0
