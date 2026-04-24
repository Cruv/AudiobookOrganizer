"""Tests for Phase 2 features: persisted LookupCandidates, provider trust
weights, match breakdown, relookup / apply / reject flows.

The lookup_book network layer is stubbed so tests stay offline.
"""

import json

import pytest

from app.services.parser import (
    ParsedMetadata,
    auto_match_score,
    compute_match_breakdown,
)


# --- breakdown ---------------------------------------------------------

class TestMatchBreakdown:
    def test_perfect_match_breakdown_totals_to_one(self):
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        b = compute_match_breakdown(parsed, "The Final Empire", "Brandon Sanderson")
        assert b["title"] == 1.0
        assert b["author"] == 1.0
        assert b["series"] is None
        assert b["year"] is None
        assert b["narrator"] is None
        assert b["total"] == pytest.approx(1.0)

    def test_missing_result_field_is_none(self):
        parsed = ParsedMetadata(title="T", author="A", series="S")
        b = compute_match_breakdown(parsed, "T", "A")  # no series on result
        assert b["series"] is None
        # Total is still computed on title+author (weight redistributed)
        assert b["total"] == pytest.approx(1.0)

    def test_year_proximity_scored_exact(self):
        parsed = ParsedMetadata(title="T", author="A", year="2006")
        b = compute_match_breakdown(parsed, "T", "A", result_year="2006")
        assert b["year"] == 1.0

    def test_year_proximity_close(self):
        parsed = ParsedMetadata(title="T", author="A", year="2006")
        b = compute_match_breakdown(parsed, "T", "A", result_year="2007")
        assert b["year"] == 0.5

    def test_auto_match_score_matches_breakdown_total(self):
        parsed = ParsedMetadata(
            title="The Way of Kings",
            author="Brandon Sanderson",
            year="2010",
            narrator="Michael Kramer",
        )
        b = compute_match_breakdown(
            parsed, "The Way of Kings", "Brandon Sanderson",
            result_year="2010", result_narrator="Michael Kramer",
        )
        score = auto_match_score(
            parsed, "The Way of Kings", "Brandon Sanderson",
            result_year="2010", result_narrator="Michael Kramer",
        )
        assert score == pytest.approx(b["total"])


# --- provider trust ----------------------------------------------------

class TestProviderTrust:
    def test_default_trust_values(self):
        from app.services.lookup import DEFAULT_PROVIDER_TRUST, get_provider_trust

        assert DEFAULT_PROVIDER_TRUST["audible"] > DEFAULT_PROVIDER_TRUST["openlibrary"]
        assert get_provider_trust("audible") == DEFAULT_PROVIDER_TRUST["audible"]
        assert get_provider_trust("itunes") == DEFAULT_PROVIDER_TRUST["itunes"]

    def test_unknown_provider_defaults_to_one(self):
        from app.services.lookup import get_provider_trust

        assert get_provider_trust("made-up-provider") == 1.0

    def test_user_setting_overrides_default(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        from app.models.settings import UserSetting
        from app.services.lookup import get_provider_trust

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()

        db.add(UserSetting(key="provider_trust_itunes", value="0.5"))
        db.commit()

        assert get_provider_trust("itunes", db) == 0.5

    def test_malformed_setting_falls_back(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        from app.models.settings import UserSetting
        from app.services.lookup import DEFAULT_PROVIDER_TRUST, get_provider_trust

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()

        db.add(UserSetting(key="provider_trust_audible", value="not a number"))
        db.commit()

        assert get_provider_trust("audible", db) == DEFAULT_PROVIDER_TRUST["audible"]

    def test_setting_clamped_to_range(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        from app.models.settings import UserSetting
        from app.services.lookup import get_provider_trust

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()

        db.add(UserSetting(key="provider_trust_google_books", value="2.5"))
        db.add(UserSetting(key="provider_trust_openlibrary", value="-0.5"))
        db.commit()

        assert get_provider_trust("google_books", db) == 1.0
        assert get_provider_trust("openlibrary", db) == 0.0


# --- candidates service ------------------------------------------------

class TestCandidatesService:
    """End-to-end test of refresh_candidates with a stubbed lookup_book."""

    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        # Register all tables
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    def _stub_lookup(self, monkeypatch, results):
        """Replace lookup_book with a coroutine returning the given results."""
        async def fake_lookup_book(title, author, api_key, db):
            return results
        monkeypatch.setattr("app.services.candidates.lookup_book", fake_lookup_book)

    @pytest.mark.asyncio
    async def test_refresh_persists_candidates(self, monkeypatch):
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.models.scan import Scan, ScannedFolder
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = self._make_db()
        scan = Scan(source_dir="/x", status="completed")
        db.add(scan)
        db.flush()
        folder = ScannedFolder(scan_id=scan.id, folder_path="/x/book", folder_name="book")
        db.add(folder)
        db.flush()
        book = Book(
            scanned_folder_id=folder.id,
            title="The Way of Kings",
            author="Brandon Sanderson",
            parse_confidence=0.8,
        )
        db.add(book)
        db.commit()

        self._stub_lookup(monkeypatch, [
            LookupResult(
                provider="audible", title="The Way of Kings",
                author="Brandon Sanderson", series="Stormlight Archive",
                series_position="1", year="2010", narrator="Michael Kramer",
                description=None, cover_url=None, confidence=0.92,
            ),
            LookupResult(
                provider="google_books", title="Way of Kings",
                author="Sanderson", series=None, series_position=None,
                year="2010", narrator=None, description=None, cover_url=None,
                confidence=0.85,
            ),
        ])

        candidates = await refresh_candidates(book, db, auto_apply=True)

        assert len(candidates) == 2
        # Best (audible) should be applied
        audible = next(c for c in candidates if c.provider == "audible")
        assert audible.applied is True
        assert audible.match_score > 0.9
        # Breakdown JSON is valid
        breakdown = json.loads(audible.match_breakdown)
        assert breakdown["title"] is not None
        assert "total" in breakdown
        # Book got the data
        db.refresh(book)
        assert book.series == "Stormlight Archive"
        assert book.narrator == "Michael Kramer"
        assert book.source == "auto:audible"
        assert book.match_confidence > 0.9

        # Persisted count matches
        assert db.query(LookupCandidate).count() == 2

    @pytest.mark.asyncio
    async def test_rejected_candidate_not_resurrected(self, monkeypatch):
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = self._make_db()
        book = Book(
            title="The Way of Kings",
            author="Brandon Sanderson",
            parse_confidence=0.7,
        )
        db.add(book)
        db.commit()

        # First pass: one candidate
        self._stub_lookup(monkeypatch, [
            LookupResult(
                provider="itunes",
                title="The Way of Kings",
                author="Brandon Sanderson",
                series=None, series_position=None, year=None,
                narrator=None, description=None, cover_url=None, confidence=0.9,
            ),
        ])
        await refresh_candidates(book, db, auto_apply=False)

        # Reject it
        cand = db.query(LookupCandidate).first()
        assert cand is not None, "refresh_candidates should have persisted one candidate"
        cand.rejected = True
        db.commit()

        # Second pass: same provider returns same thing
        self._stub_lookup(monkeypatch, [
            LookupResult(
                provider="itunes",
                title="The Way of Kings",
                author="Brandon Sanderson",
                series=None, series_position=None, year=None,
                narrator=None, description=None, cover_url=None, confidence=0.9,
            ),
        ])
        result = await refresh_candidates(book, db, auto_apply=False)

        # The rejected one should still exist, and no NEW candidate should
        # have been created for the same fingerprint.
        assert len(result) == 0
        non_rejected = db.query(LookupCandidate).filter(LookupCandidate.rejected.is_(False)).count()
        assert non_rejected == 0
        # Rejected row still present
        assert db.query(LookupCandidate).filter(LookupCandidate.rejected.is_(True)).count() == 1

    @pytest.mark.asyncio
    async def test_auto_apply_skipped_when_below_threshold(self, monkeypatch):
        from app.models.book import Book
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = self._make_db()
        book = Book(title="Totally Different Title", author="Unknown", parse_confidence=0.4)
        db.add(book)
        db.commit()

        # Result that scores low against parsed
        self._stub_lookup(monkeypatch, [
            LookupResult(
                provider="openlibrary", title="Way of Kings",
                author="Sanderson", series=None, series_position=None,
                year=None, narrator=None, description=None, cover_url=None,
                confidence=0.8,
            ),
        ])
        candidates = await refresh_candidates(book, db, auto_apply=True)

        # Candidate exists but is not applied
        assert len(candidates) == 1
        assert candidates[0].applied is False
        db.refresh(book)
        assert book.match_confidence == 0.0
        assert book.source != "auto:openlibrary"

    def test_apply_candidate_copies_fields(self):
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.services.candidates import apply_candidate

        db = self._make_db()
        book = Book(title="Old Title", author="Old Author", parse_confidence=0.5)
        db.add(book)
        db.commit()
        cand = LookupCandidate(
            book_id=book.id, provider="audible",
            title="New Title", author="New Author",
            series="New Series", series_position="3",
            year="2020", narrator="Narrator Name",
            raw_confidence=0.92, match_score=0.88,
            trust_weight=1.0, ranking_score=0.88,
        )
        db.add(cand)
        db.commit()

        apply_candidate(book, cand, db)
        db.commit()

        assert book.title == "New Title"
        assert book.author == "New Author"
        assert book.series == "New Series"
        assert book.series_position == "3"
        assert book.year == "2020"
        assert book.narrator == "Narrator Name"
        assert book.source == "auto:audible"
        assert cand.applied is True
        assert book.match_confidence == 0.88

    def test_reject_undoes_apply(self):
        from app.models.book import Book
        from app.models.lookup_candidate import LookupCandidate
        from app.services.candidates import apply_candidate, reject_candidate

        db = self._make_db()
        book = Book(title="T", author="A", parse_confidence=0.5)
        db.add(book)
        db.commit()
        cand = LookupCandidate(
            book_id=book.id, provider="itunes",
            title="T2", author="A2",
            raw_confidence=0.9, match_score=0.8,
            trust_weight=0.9, ranking_score=0.72,
        )
        db.add(cand)
        db.commit()

        apply_candidate(book, cand, db)
        db.commit()
        assert book.source == "auto:itunes"

        reject_candidate(cand, db)
        db.commit()

        assert cand.rejected is True
        assert cand.applied is False
        assert book.source == "parsed"
        assert book.match_confidence == 0.0


# --- ranking: trust weights break ties --------------------------------

class TestRankingWithTrust:
    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    @pytest.mark.asyncio
    async def test_audible_wins_over_openlibrary_on_equal_match(self, monkeypatch):
        """Two providers return identical metadata; the more trusted one
        should win the auto-apply."""
        from app.models.book import Book
        from app.schemas.book import LookupResult
        from app.services.candidates import refresh_candidates

        db = self._make_db()
        book = Book(title="The Way of Kings", author="Brandon Sanderson", parse_confidence=0.8)
        db.add(book)
        db.commit()

        async def fake_lookup_book(title, author, api_key, db):
            return [
                LookupResult(
                    provider="openlibrary", title="The Way of Kings",
                    author="Brandon Sanderson", series=None, series_position=None,
                    year=None, narrator=None, description=None, cover_url=None,
                    confidence=0.80,
                ),
                LookupResult(
                    provider="audible", title="The Way of Kings",
                    author="Brandon Sanderson", series=None, series_position=None,
                    year=None, narrator=None, description=None, cover_url=None,
                    confidence=0.92,
                ),
            ]
        monkeypatch.setattr("app.services.candidates.lookup_book", fake_lookup_book)

        candidates = await refresh_candidates(book, db, auto_apply=True)

        # Both score 1.0 on match, but audible's trust weight is higher
        applied = [c for c in candidates if c.applied]
        assert len(applied) == 1
        assert applied[0].provider == "audible"
