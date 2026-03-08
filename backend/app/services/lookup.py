"""Online metadata lookup via Google Books, OpenLibrary, and iTunes APIs."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.models.lookup_cache import LookupCache
from app.schemas.book import LookupResult
from app.services.parser import clean_query, fuzzy_match


CACHE_DURATION_DAYS = 30


async def search_google_books(
    title: str,
    author: str | None,
    api_key: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search Google Books API for matching books."""
    cleaned = clean_query(title, author)
    query_parts = [f"intitle:{title}"]
    if author:
        query_parts.append(f"inauthor:{author}")
    query = "+".join(query_parts)

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

            series_name = None
            series_pos = None
            subtitle = vol.get("subtitle", "")
            if subtitle:
                series_match = re.search(
                    r"(?:Book|Vol(?:ume)?|#)\s*(\d+\.?\d*)", subtitle, re.IGNORECASE
                )
                if series_match:
                    series_pos = series_match.group(1)
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


async def search_itunes(
    title: str,
    author: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search iTunes/Apple Books API for audiobooks."""
    query = clean_query(title, author)
    if not query:
        return []

    cached = _get_cached(query, "itunes", db)
    if cached is not None:
        return cached

    params: dict[str, str] = {
        "term": query,
        "media": "audiobook",
        "limit": "5",
    }

    results: list[LookupResult] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://itunes.apple.com/search", params=params
            )
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("results", []):
            item_title = item.get("collectionName") or item.get("trackName")
            item_author = item.get("artistName")
            release_date = item.get("releaseDate", "")
            year = release_date[:4] if len(release_date) >= 4 else None
            description = item.get("description", "")
            cover_url = item.get("artworkUrl100")

            # Try to extract series info from title
            series_name = None
            series_pos = None
            if item_title:
                series_match = re.search(
                    r",?\s*(?:Book|Vol(?:ume)?|#)\s*(\d+\.?\d*)",
                    item_title,
                    re.IGNORECASE,
                )
                if series_match:
                    series_pos = series_match.group(1)
                    clean_title = item_title[: series_match.start()].strip(" -–—:,")
                    # Check if there's a colon-separated series
                    colon_split = clean_title.split(":")
                    if len(colon_split) == 2:
                        series_name = colon_split[0].strip()
                        item_title = colon_split[1].strip()
                    else:
                        item_title = clean_title

                # Also check "Title (Series Name, Book N)" pattern
                paren_match = re.search(
                    r"\((.+?),?\s*(?:Book|#)\s*(\d+\.?\d*)\)",
                    item_title,
                    re.IGNORECASE,
                )
                if paren_match and not series_name:
                    series_name = paren_match.group(1).strip()
                    series_pos = paren_match.group(2)
                    item_title = item_title[: paren_match.start()].strip()

                # Strip "(Unabridged)" suffix
                item_title = re.sub(r"\s*\(Unabridged\)", "", item_title, flags=re.IGNORECASE).strip()

            results.append(
                LookupResult(
                    provider="itunes",
                    title=item_title,
                    author=item_author,
                    series=series_name,
                    series_position=series_pos,
                    year=year,
                    description=description[:200] if description else None,
                    cover_url=cover_url,
                    confidence=0.90,  # Higher confidence — audiobook-specific
                )
            )

    except Exception:
        pass

    _set_cached(query, "itunes", results, db)
    return results


async def lookup_book(
    title: str,
    author: str | None,
    api_key: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search all APIs and return deduplicated results, best first."""
    google_results = await search_google_books(title, author, api_key, db)
    ol_results = await search_openlibrary(title, author, db)
    itunes_results = await search_itunes(title, author, db)

    all_results = itunes_results + google_results + ol_results

    # Deduplicate by title+author similarity
    deduped = _deduplicate_results(all_results)

    # Sort by confidence descending
    deduped.sort(key=lambda r: r.confidence, reverse=True)
    return deduped


def _deduplicate_results(results: list[LookupResult]) -> list[LookupResult]:
    """Remove duplicate results across providers, keeping highest confidence."""
    seen: list[LookupResult] = []
    for result in results:
        is_dup = False
        for existing in seen:
            title_match = (
                result.title
                and existing.title
                and fuzzy_match(result.title, existing.title)
            )
            author_match = (
                result.author
                and existing.author
                and fuzzy_match(result.author, existing.author)
            )
            if title_match and author_match:
                # Keep the one with higher confidence; merge missing fields
                if result.confidence > existing.confidence:
                    if not result.series and existing.series:
                        result.series = existing.series
                        result.series_position = existing.series_position
                    if not result.year and existing.year:
                        result.year = existing.year
                    if not result.cover_url and existing.cover_url:
                        result.cover_url = existing.cover_url
                    seen.remove(existing)
                    seen.append(result)
                else:
                    if not existing.series and result.series:
                        existing.series = result.series
                        existing.series_position = result.series_position
                    if not existing.year and result.year:
                        existing.year = result.year
                    if not existing.cover_url and result.cover_url:
                        existing.cover_url = result.cover_url
                is_dup = True
                break
        if not is_dup:
            seen.append(result)
    return seen


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
