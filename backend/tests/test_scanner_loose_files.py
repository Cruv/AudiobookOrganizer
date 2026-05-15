"""Tests for loose audiobook file detection (e.g. standalone .m4b files).

The scanner treats .m4b files as their own books regardless of how many
sit in the same directory, so a downloads folder full of unrelated m4bs
is parsed correctly. Other audio formats (mp3, flac, ...) keep the
existing 'folder = book' grouping for multi-file chapter sets.
"""

import pytest


def _make_audio(path):
    """Create a placeholder audio file. Tag-reading code accepts files
    with no embedded tags and just returns empty values, so a stub byte
    string is enough for parser-level tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class TestFindAudiobookFolders:
    def test_loose_m4b_at_root(self, tmp_path):
        from app.services.scanner import _find_audiobook_folders

        _make_audio(tmp_path / "Brandon Sanderson - The Final Empire.m4b")

        result = _find_audiobook_folders(str(tmp_path))

        # The file path itself should be returned, not the parent dir.
        assert str(tmp_path / "Brandon Sanderson - The Final Empire.m4b") in result
        # The parent dir should NOT be added as a folder unit — it has
        # no non-m4b audio files to group.
        assert str(tmp_path) not in result

    def test_multiple_unrelated_m4b_files_in_downloads(self, tmp_path):
        """The downloads-dir scenario: many unrelated single-file books."""
        from app.services.scanner import _find_audiobook_folders

        _make_audio(tmp_path / "Book One.m4b")
        _make_audio(tmp_path / "Author - Book Two.m4b")
        _make_audio(tmp_path / "Book Three (2020).m4b")

        result = _find_audiobook_folders(str(tmp_path))

        # Each m4b is its own scan unit — three separate books.
        m4b_paths = [p for p in result if p.endswith(".m4b")]
        assert len(m4b_paths) == 3

    def test_mp3_chapter_set_stays_as_folder(self, tmp_path):
        """A folder of .mp3 files keeps the 'folder = book' grouping."""
        from app.services.scanner import _find_audiobook_folders

        book_dir = tmp_path / "Some Book"
        _make_audio(book_dir / "01 - Chapter 1.mp3")
        _make_audio(book_dir / "02 - Chapter 2.mp3")
        _make_audio(book_dir / "03 - Chapter 3.mp3")

        result = _find_audiobook_folders(str(tmp_path))

        # One folder unit, no loose-file units.
        assert str(book_dir) in result
        assert len([p for p in result if p.endswith(".mp3")]) == 0

    def test_mixed_m4b_and_mp3_chapters_in_same_folder(self, tmp_path):
        """If a folder mixes mp3 chapters with an unrelated .m4b, the
        m4b is its own loose book and the mp3s become a folder unit."""
        from app.services.scanner import _find_audiobook_folders

        book_dir = tmp_path / "Book Dir"
        _make_audio(book_dir / "01.mp3")
        _make_audio(book_dir / "02.mp3")
        _make_audio(book_dir / "Side Story.m4b")

        result = _find_audiobook_folders(str(tmp_path))

        assert str(book_dir) in result
        assert str(book_dir / "Side Story.m4b") in result

    def test_loose_m4b_alongside_mp3_book_folder(self, tmp_path):
        """Library with one loose m4b and one mp3 book folder."""
        from app.services.scanner import _find_audiobook_folders

        _make_audio(tmp_path / "Loose Book.m4b")
        mp3_dir = tmp_path / "Chaptered Book"
        _make_audio(mp3_dir / "01.mp3")
        _make_audio(mp3_dir / "02.mp3")

        result = _find_audiobook_folders(str(tmp_path))

        assert str(tmp_path / "Loose Book.m4b") in result
        assert str(mp3_dir) in result

    def test_m4b_inside_nested_book_folder_is_still_loose(self, tmp_path):
        """Even inside a deep folder, every .m4b is its own book."""
        from app.services.scanner import _find_audiobook_folders

        deep = tmp_path / "Author" / "Series"
        _make_audio(deep / "Book One.m4b")
        _make_audio(deep / "Book Two.m4b")

        result = _find_audiobook_folders(str(tmp_path))

        assert str(deep / "Book One.m4b") in result
        assert str(deep / "Book Two.m4b") in result
        # The folder shouldn't appear because it has no non-m4b audio.
        assert str(deep) not in result


class TestProcessLooseFile:
    @pytest.fixture
    def db(self):
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401
        from app.models.base import Base
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        yield session
        session.close()

    def test_creates_book_for_loose_m4b(self, tmp_path, db):
        from app.models.scan import Scan
        from app.services.scanner import _process_folder

        file_path = tmp_path / "Brandon Sanderson - The Final Empire.m4b"
        _make_audio(file_path)

        scan = Scan(source_dir=str(tmp_path), status="running")
        db.add(scan)
        db.flush()

        # _process_folder dispatches to _process_loose_file for file paths.
        book = _process_folder(str(file_path), scan, db)
        db.commit()

        assert book is not None
        assert book.title == "The Final Empire"
        assert book.author == "Brandon Sanderson"
        assert len(book.files) == 1
        assert book.files[0].original_path == str(file_path)
        assert book.files[0].file_format == "m4b"
        # The ScannedFolder row should hold the file path, not the parent.
        assert book.scanned_folder.folder_path == str(file_path)
        assert book.scanned_folder.folder_name == file_path.name

    def test_missing_loose_file_marked_skipped(self, tmp_path, db):
        from app.models.scan import Scan
        from app.services.scanner import _process_folder

        fake_path = tmp_path / "Does Not Exist.m4b"

        scan = Scan(source_dir=str(tmp_path), status="running")
        db.add(scan)
        db.flush()

        book = _process_folder(str(fake_path), scan, db)
        db.commit()

        assert book is None
