"""Tests for the lookup priority rework (v1.21.0):
  - lookup query uses folder-parsed title/author, not book.title/book.author
  - per-provider auto-apply thresholds (Audible 0.50, iTunes 0.65, ...)
  - trusted providers (Audible/iTunes) overwrite series/year/narrator
"""

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


def _make_book(
    db,
    *,
    folder_path: str = "/library/Brandon Sanderson/The Final Empire",
    title: str = "Audiobook Track 01",
    author: str = "Random Publisher",
    series: str | None = None,
    year: str | None = None,
    narrator: str | None = None,
):
    """Build a Book with deliberately bad tag-derived title/author and
    a clean folder path. Mirrors the real "bad tags poison the search"
    failure mode."""
    from app.models.book import Book
    from app.models.scan import Scan, ScannedFolder

    scan = Scan(source_dir="/library", status="completed")
    db.add(scan)
    db.flush()
    folder = ScannedFolder(
        scan_id=scan.id, folder_path=folder_path,
        folder_name=folder_path.rstrip("/").split("/")[-1],
    )
    db.add(folder)
    db.flush()
    book = Book(
        scanned_folder_id=folder.id,
        title=title, author=author,
        series=series, year=year, narrator=narrator,
        source="parsed", confidence=0.5,
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def _stub_lookup(monkeypatch, results):
    """Replace lookup_book with a coroutine. Captures the (title,
    author) the lookup was called with so we can assert the folder
    parse was used."""
    captured = {}

    async def fake_lookup_book(title, author, api_key, db):
        captured["title"] = title
        captured["author"] = author
        return results

    monkeypatch.setattr("app.services.candidates.lookup_book", fake_lookup_book)
    return captured


class TestFolderOnlyQuery:
    @pytest.mark.asyncio
    async def test_lookup_uses_folder_parse_not_tag_values(self, monkeypatch):
        """The book has bad tag-derived title ("Audiobook Track 01")
        and author ("Random Publisher"), but the folder path encodes
        the real title + author. The lookup must use the folder-parsed
        values."""
        from app.services.candidates import refresh_candidates

        db = _make_db()
        book = _make_book(
            db,
            folder_path="/library/Brandon Sanderson/The Final Empire",
            title="Audiobook Track 01",
            author="Random Publisher",
        )
        captured = _stub_lookup(monkeypatch, [])

        await refresh_candidates(book, db, auto_apply=False)

        # The lookup query must come from the folder parse, not from
        # book.title/book.author.
        assert "sanderson" in (captured.get("title") or "").lower() \
            or "sanderson" in (captured.get("author") or "").lower() \
            or "final empire" in (captured.get("title") or "").lower()
        assert "audiobook track 01" not in (captured.get("title") or "").lower()

    @pytest.mark.asyncio
    async def test_falls_back_to_book_fields_when_no_scanned_folder(self, monkeypatch):
        """If the book has no scanned_folder (manually-added entry, or
        loose-file book with a path that parsed nothing), fall back to
        book.title/book.author so we at least attempt SOMETHING."""
        from app.models.book import Book
        from app.services.candidates import refresh_candidates

        db = _make_db()
        # No ScannedFolder attached.
        book = Book(
            title="Real Title", author="Real Author",
            source="parsed", confidence=0.5,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        captured = _stub_lookup(monkeypatch, [])

        await refresh_candidates(book, db, auto_apply=False)

        # No folder to parse from → must use book.title/book.author.
        query = (captured.get("title") or "").lower()
        assert "real" in query or "title" in query


class TestPerProviderThresholds:
    @pytest.mark.asyncio
    async def test_audible_auto_applies_at_low_match_score(self, monkeypatch):
        """An Audible result with match_score ~0.55 (below the old
        single 0.80 threshold) should still auto-apply because
        Audible's per-provider threshold is 0.50."""
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = _make_db()
        book = _make_book(
            db,
            folder_path="/library/Brandon Sanderson/The Final Empire",
        )
        # The candidate doesn't perfectly match the book fields, so
        # compute_match_breakdown will yield something around 0.5-0.7.
        _stub_lookup(monkeypatch, [
            LookupResult(
                provider="audible",
                title="The Final Empire",
                author="Brandon Sanderson",
                series=None,
                series_position=None,
                year="2006",
                narrator="Michael Kramer",
                description=None,
                cover_url=None,
                confidence=0.92,
            ),
        ])

        candidates = await refresh_candidates(book, db, auto_apply=True)
        # The Audible candidate should be applied — its score clears the
        # 0.50 Audible-specific bar even though it'd miss the global 0.80.
        applied = [c for c in candidates if c.applied]
        assert len(applied) == 1
        assert applied[0].provider == "audible"

        db.refresh(book)
        assert book.source == "auto:audible"
        assert book.author == "Brandon Sanderson"

    @pytest.mark.asyncio
    async def test_audible_wins_over_higher_scored_openlibrary(self, monkeypatch):
        """Provider priority beats raw ranking_score: if Audible AND
        OpenLibrary both returned matches and OL's score is higher,
        Audible still wins."""
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = _make_db()
        book = _make_book(db)
        # Two providers return reasonable matches. OL's match might
        # rank higher because Audible's title differs slightly.
        _stub_lookup(monkeypatch, [
            LookupResult(
                provider="openlibrary",
                title="The Final Empire",
                author="Brandon Sanderson",
                series=None, series_position=None,
                year="2006", narrator=None,
                description=None, cover_url=None, confidence=0.90,
            ),
            LookupResult(
                provider="audible",
                title="The Final Empire (Mistborn, Book 1)",
                author="Brandon Sanderson",
                series="Mistborn", series_position="1",
                year="2006", narrator="Michael Kramer",
                description=None, cover_url=None, confidence=0.92,
            ),
        ])

        await refresh_candidates(book, db, auto_apply=True)
        db.refresh(book)
        # Audible-first policy means we should end up with auto:audible.
        assert book.source == "auto:audible"

    @pytest.mark.asyncio
    async def test_openlibrary_still_applies_when_only_provider(self, monkeypatch):
        """OL alone with a strong match should still auto-apply at its
        higher threshold."""
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = _make_db()
        book = _make_book(
            db,
            folder_path="/library/Brandon Sanderson/The Final Empire",
        )
        _stub_lookup(monkeypatch, [
            LookupResult(
                provider="openlibrary",
                title="The Final Empire",
                author="Brandon Sanderson",
                series=None, series_position=None,
                year="2006", narrator=None,
                description=None, cover_url=None, confidence=0.80,
            ),
        ])

        await refresh_candidates(book, db, auto_apply=True)
        db.refresh(book)
        # OL was the only provider that matched, and its score clears
        # the 0.80 OL threshold against a clean folder query.
        assert book.source == "auto:openlibrary"


class TestTrustedOverwrite:
    def test_audible_overwrites_existing_narrator(self):
        """Audible (trusted) replaces an existing narrator field even
        when the book already has one — the previous value was tag-
        derived noise."""
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.services.candidates import apply_candidate

        db = _make_db()
        book = Book(
            title="X", author="Y", narrator="Wrong Narrator",
            source="parsed", confidence=0.5,
        )
        db.add(book)
        db.flush()
        cand = LookupCandidate(
            book_id=book.id, provider="audible",
            title="X", author="Y", narrator="Right Narrator",
            year="2020", series="Series", series_position="3",
            match_score=0.7, trust_weight=1.0, ranking_score=0.7,
        )
        db.add(cand)
        db.flush()

        apply_candidate(book, cand, db)
        db.refresh(book)
        assert book.narrator == "Right Narrator"
        assert book.series == "Series"
        assert book.series_position == "3"
        assert book.year == "2020"

    def test_openlibrary_does_not_overwrite_existing_narrator(self):
        """Low-trust providers leave existing audiobook metadata alone
        — OL often has the wrong audiobook edition's data."""
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.services.candidates import apply_candidate

        db = _make_db()
        book = Book(
            title="X", author="Y", narrator="Existing Narrator",
            year="2019", series="Existing Series",
            source="parsed", confidence=0.5,
        )
        db.add(book)
        db.flush()
        cand = LookupCandidate(
            book_id=book.id, provider="openlibrary",
            title="X", author="Y", narrator="OL Narrator",
            year="2020", series="OL Series",
            match_score=0.9, trust_weight=0.65, ranking_score=0.59,
        )
        db.add(cand)
        db.flush()

        apply_candidate(book, cand, db)
        db.refresh(book)
        # Existing values preserved; OL didn't get to clobber them.
        assert book.narrator == "Existing Narrator"
        assert book.year == "2019"
        assert book.series == "Existing Series"

    def test_low_trust_fills_in_missing_fields(self):
        """OL fills in fields the book is missing — just doesn't
        overwrite existing values."""
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.services.candidates import apply_candidate

        db = _make_db()
        book = Book(
            title="X", author="Y",
            source="parsed", confidence=0.5,
        )
        db.add(book)
        db.flush()
        cand = LookupCandidate(
            book_id=book.id, provider="openlibrary",
            title="X", author="Y", year="2020", series="Filled Series",
            match_score=0.9, trust_weight=0.65, ranking_score=0.59,
        )
        db.add(cand)
        db.flush()

        apply_candidate(book, cand, db)
        db.refresh(book)
        assert book.year == "2020"
        assert book.series == "Filled Series"
