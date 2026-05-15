"""Regression test for the lookup-cache silent-defeat bug.

The 30-day lookup cache uses a naive `DateTime` column in SQLite. The
old code compared the column's value against an aware
`datetime.now(timezone.utc)` — `naive > aware` raises TypeError. The
exception was swallowed by `_safe_provider` so every cache hit looked
like a miss and forced a fresh API call. The fix normalizes the
naive value to aware-UTC on read.
"""

import json
from datetime import datetime, timedelta, timezone

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


def _store_cache_row(db, *, query: str, provider: str, results_json: str, expires_at):
    """Insert a cache row directly so we can control the exact
    datetime stored (naive vs aware), regardless of what _set_cached
    would do today."""
    from app.services.lookup import _cache_key
    from app.models.lookup_cache import LookupCache

    row = LookupCache(
        query_hash=_cache_key(query, provider),
        provider=provider,
        query_text=query,
        response_json=results_json,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(row)
    db.commit()


def _sample_results_json():
    """Build a JSON blob that decodes into a list of LookupResult."""
    return json.dumps([
        {
            "provider": "google_books",
            "title": "Cached Title",
            "author": "Cached Author",
            "series": None,
            "series_position": None,
            "year": "2020",
            "narrator": None,
            "description": None,
            "cover_url": None,
            "confidence": 0.85,
        }
    ])


class TestGetCachedHandlesNaiveExpiresAt:
    def test_cache_hit_with_naive_future_datetime(self):
        """The bug: SQLite stores DateTime naively. The fix normalizes
        on read. Without the fix this would raise TypeError; with it,
        we get the cached results back."""
        from app.services.lookup import _get_cached

        db = _make_db()
        # Aware → SQLite strips tzinfo at write → naive on read.
        future = datetime.now(timezone.utc) + timedelta(days=10)
        _store_cache_row(
            db,
            query="brandon sanderson",
            provider="google_books",
            results_json=_sample_results_json(),
            expires_at=future,
        )

        results = _get_cached("brandon sanderson", "google_books", db)
        assert results is not None
        assert len(results) == 1
        assert results[0].title == "Cached Title"

    def test_cache_miss_when_expired_with_naive_datetime(self):
        """Expired rows should be deleted and treated as a miss —
        without raising TypeError from the comparison."""
        from app.models.lookup_cache import LookupCache
        from app.services.lookup import _get_cached

        db = _make_db()
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _store_cache_row(
            db,
            query="expired",
            provider="google_books",
            results_json=_sample_results_json(),
            expires_at=past,
        )

        results = _get_cached("expired", "google_books", db)
        assert results is None
        # Expired row should have been cleaned up.
        assert db.query(LookupCache).count() == 0

    def test_cache_miss_for_unknown_query(self):
        from app.services.lookup import _get_cached

        db = _make_db()
        results = _get_cached("nothing-cached", "google_books", db)
        assert results is None

    def test_round_trip_via_set_cached(self):
        """Verify that the production write path (_set_cached) also
        round-trips through the new normalize-on-read."""
        from app.schemas.book import LookupResult
        from app.services.lookup import _get_cached, _set_cached

        db = _make_db()
        result = LookupResult(
            provider="itunes",
            title="Round Trip",
            author="Author",
            series=None,
            series_position=None,
            year="2024",
            narrator=None,
            description=None,
            cover_url=None,
            confidence=0.9,
        )
        _set_cached("round trip query", "itunes", [result], db)

        # Read it back — must succeed even though SQLite returns naive.
        cached = _get_cached("round trip query", "itunes", db)
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].title == "Round Trip"
        assert cached[0].confidence == 0.9
