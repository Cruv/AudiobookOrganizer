"""Online metadata lookup via Google Books and OpenLibrary APIs."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.models.lookup_cache import LookupCache
from app.schemas.book import LookupResult


CACHE_DURATION_DAYS = 30


async def search_google_books(
    title: str,
    author: str | None,
    api_key: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search Google Books API for matching books."""
    query_parts = [f"intitle:{title}"]
    if author:
        query_parts.append(f"inauthor:{author}")
    query = "+".join(query_parts)

    # Check cache
    cached = _get_cached(query, "google_books", db)
    if cached is not None:
        return cached

    params: dict[str, str] = {"q": query, "maxResults": "5"}
    if api_key:
        params["key"] = api_key

    results: list[LookupResult] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/books/v1/volumes", params=params
            )
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("items", []):
            vol = item.get("volumeInfo", {})
            authors = vol.get("authors", [])
            published = vol.get("publishedDate", "")

            # Extract series from subtitle or title
            series_name = None
            series_pos = None
            subtitle = vol.get("subtitle", "")
            if subtitle:
                import re
                series_match = re.search(
                    r"(?:Book|Vol(?:ume)?|#)\s*(\d+\.?\d*)", subtitle, re.IGNORECASE
                )
                if series_match:
                    series_pos = series_match.group(1)
                    # Use the part before "Book N" as series name
                    series_name = subtitle[: series_match.start()].strip(" -–—:,")

            results.append(
                LookupResult(
                    provider="google_books",
                    title=vol.get("title"),
                    author=authors[0] if authors else None,
                    series=series_name,
                    series_position=series_pos,
                    year=published[:4] if len(published) >= 4 else None,
                    description=vol.get("description", "")[:200] if vol.get("description") else None,
                    cover_url=(vol.get("imageLinks") or {}).get("thumbnail"),
                    confidence=0.85,
                )
            )

    except Exception:
        pass

    _set_cached(query, "google_books", results, db)
    return results


async def search_openlibrary(
    title: str,
    author: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search OpenLibrary API for matching books."""
    params: dict[str, str] = {"title": title, "limit": "5"}
    if author:
        params["author"] = author

    query = f"title={title}&author={author or ''}"

    # Check cache
    cached = _get_cached(query, "openlibrary", db)
    if cached is not None:
        return cached

    results: list[LookupResult] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://openlibrary.org/search.json", params=params
            )
            resp.raise_for_status()
            data = resp.json()

        for doc in data.get("docs", [])[:5]:
            authors = doc.get("author_name", [])
            year = doc.get("first_publish_year")
            cover_id = doc.get("cover_i")
            cover_url = (
                f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                if cover_id
                else None
            )

            results.append(
                LookupResult(
                    provider="openlibrary",
                    title=doc.get("title"),
                    author=authors[0] if authors else None,
                    series=None,
                    series_position=None,
                    year=str(year) if year else None,
                    description=None,
                    cover_url=cover_url,
                    confidence=0.80,
                )
            )

    except Exception:
        pass

    _set_cached(query, "openlibrary", results, db)
    return results


async def lookup_book(
    title: str,
    author: str | None,
    api_key: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search both APIs and return merged results, best first."""
    google_results = await search_google_books(title, author, api_key, db)
    ol_results = await search_openlibrary(title, author, db)

    all_results = google_results + ol_results
    # Sort by confidence descending
    all_results.sort(key=lambda r: r.confidence, reverse=True)
    return all_results


def _cache_key(query: str, provider: str) -> str:
    """Generate a cache key hash."""
    normalized = f"{provider}:{query.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def _get_cached(query: str, provider: str, db: Session) -> list[LookupResult] | None:
    """Get cached lookup results if available and not expired."""
    key = _cache_key(query, provider)
    cached = db.query(LookupCache).filter(LookupCache.query_hash == key).first()
    if cached and cached.expires_at > datetime.now(timezone.utc):
        data = json.loads(cached.response_json)
        return [LookupResult(**item) for item in data]
    if cached and cached.expires_at <= datetime.now(timezone.utc):
        db.delete(cached)
        db.commit()
    return None


def _set_cached(
    query: str, provider: str, results: list[LookupResult], db: Session
) -> None:
    """Cache lookup results."""
    key = _cache_key(query, provider)
    data = json.dumps([r.model_dump() for r in results])
    now = datetime.now(timezone.utc)

    existing = db.query(LookupCache).filter(LookupCache.query_hash == key).first()
    if existing:
        existing.response_json = data
        existing.created_at = now
        existing.expires_at = now + timedelta(days=CACHE_DURATION_DAYS)
    else:
        cache_entry = LookupCache(
            query_hash=key,
            provider=provider,
            query_text=query,
            response_json=data,
            created_at=now,
            expires_at=now + timedelta(days=CACHE_DURATION_DAYS),
        )
        db.add(cache_entry)
    db.commit()
