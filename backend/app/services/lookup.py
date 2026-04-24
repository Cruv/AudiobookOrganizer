"""Online metadata lookup via Google Books, OpenLibrary, and iTunes APIs."""

import asyncio
import hashlib
import html
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.models.lookup_cache import LookupCache
from app.schemas.book import LookupResult
from app.services.parser import clean_query, fuzzy_match

logger = logging.getLogger(__name__)


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_description(text: str | None, max_len: int = 400) -> str | None:
    """Strip HTML tags, decode entities, and collapse whitespace.

    iTunes in particular returns descriptions with embedded markup
    (`<i>`, `<b>`, `<br />`, `&#xa0;`). Showing that raw in the UI is
    ugly. We never render descriptions as HTML so stripping is safe.
    """
    if not text:
        return None
    stripped = _HTML_TAG_RE.sub(" ", text)
    decoded = html.unescape(stripped)
    collapsed = re.sub(r"\s+", " ", decoded).strip()
    if not collapsed:
        return None
    return collapsed[:max_len]


CACHE_DURATION_DAYS = 30

# Retry settings for external HTTP providers.
_HTTP_TIMEOUT = 10.0
_HTTP_MAX_ATTEMPTS = 3
_HTTP_BASE_BACKOFF = 0.5  # seconds; jittered exponential

# How much we trust each provider's data quality. Used as a multiplier
# on the raw match_score when picking the best candidate: audibles that
# barely match are preferred over iTunes results that barely match.
# Users can override via the "provider_trust_{name}" user setting.
DEFAULT_PROVIDER_TRUST = {
    "audible": 1.00,     # audiobook-native, has narrator, usually correct
    "itunes": 0.90,      # audiobook-native but often wrong author/edition
    "google_books": 0.75,  # book-oriented, rarely knows audiobook editions
    "openlibrary": 0.65,  # crowd-sourced, weakest of the four
}


def get_provider_trust(provider: str, db: Session | None = None) -> float:
    """Return the trust weight for a provider, 0.0–1.0.

    If a user setting named "provider_trust_<provider>" exists, use that;
    otherwise fall back to DEFAULT_PROVIDER_TRUST, otherwise 1.0.
    """
    from app.models.settings import UserSetting

    default = DEFAULT_PROVIDER_TRUST.get(provider, 1.0)
    if db is None:
        return default
    setting = (
        db.query(UserSetting)
        .filter(UserSetting.key == f"provider_trust_{provider}")
        .first()
    )
    if not setting or not setting.value:
        return default
    try:
        val = float(setting.value)
        # Clamp to sane range.
        return max(0.0, min(1.0, val))
    except ValueError:
        return default


async def _http_get_json(
    url: str,
    params: dict[str, str],
    provider: str,
) -> dict | None:
    """GET url with retry+backoff. Returns parsed JSON or None on failure.

    Retries on 429 (rate limit), 5xx, and network/timeout errors. 4xx
    other than 429 fails fast — they're client errors, retrying won't help.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url, params=params)

            if resp.status_code == 429 or resp.status_code >= 500:
                # Respect Retry-After when present
                delay = _HTTP_BASE_BACKOFF * (2 ** (attempt - 1))
                try:
                    retry_after = float(resp.headers.get("retry-after", "0"))
                    delay = max(delay, retry_after)
                except ValueError:
                    pass
                delay += random.uniform(0, 0.3)  # jitter
                if attempt < _HTTP_MAX_ATTEMPTS:
                    logger.info(
                        "%s returned %d, retrying in %.1fs (attempt %d/%d)",
                        provider, resp.status_code, delay, attempt, _HTTP_MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            return resp.json()

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            if attempt < _HTTP_MAX_ATTEMPTS:
                delay = _HTTP_BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                logger.info(
                    "%s %s, retrying in %.1fs (attempt %d/%d)",
                    provider, type(e).__name__, delay, attempt, _HTTP_MAX_ATTEMPTS,
                )
                await asyncio.sleep(delay)
                continue
            logger.warning("%s failed after %d attempts: %s", provider, attempt, type(e).__name__)
            return None
        except httpx.HTTPStatusError as e:
            # 4xx other than 429: don't retry
            logger.warning("%s returned %s", provider, e.response.status_code)
            return None
        except Exception as e:
            last_exc = e
            logger.warning("%s unexpected error: %s", provider, type(e).__name__)
            return None

    if last_exc:
        logger.warning("%s giving up after %d attempts", provider, _HTTP_MAX_ATTEMPTS)
    return None


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

    cached = _get_cached(query, "google_books", db)
    if cached is not None:
        return cached

    params: dict[str, str] = {"q": query, "maxResults": "5"}
    if api_key:
        params["key"] = api_key

    results: list[LookupResult] = []
    data = await _http_get_json(
        "https://www.googleapis.com/books/v1/volumes", params, "google_books"
    )
    if data is None:
        _set_cached(query, "google_books", results, db)
        return results
    try:
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
                    description=_clean_description(vol.get("description")),
                    cover_url=(vol.get("imageLinks") or {}).get("thumbnail"),
                    confidence=0.85,
                )
            )

    except Exception as e:
        logger.warning("Google Books search failed for '%s': %s", title, type(e).__name__)

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
    data = await _http_get_json(
        "https://openlibrary.org/search.json", params, "openlibrary"
    )
    if data is None:
        _set_cached(query, "openlibrary", results, db)
        return results
    try:
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

    except Exception as e:
        logger.warning("OpenLibrary search failed for '%s': %s", title, type(e).__name__)

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
    data = await _http_get_json(
        "https://itunes.apple.com/search", params, "itunes"
    )
    if data is None:
        _set_cached(query, "itunes", results, db)
        return results
    try:
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
                    description=_clean_description(description),
                    cover_url=cover_url,
                    confidence=0.90,  # Higher confidence — audiobook-specific
                )
            )

    except Exception as e:
        logger.warning("iTunes search failed for '%s': %s", title, type(e).__name__)

    _set_cached(query, "itunes", results, db)
    return results


AUDIBLE_AUTH_FILE = "/app/data/audible_auth.json"

# Region to TLD mapping for Audible API
AUDIBLE_LOCALE_MAP = {
    "us": "us", "uk": "uk", "au": "au", "ca": "ca",
    "de": "de", "fr": "fr", "in": "in", "it": "it",
    "jp": "jp", "es": "es",
}


async def search_audible(
    title: str,
    author: str | None,
    db: Session,
    locale: str = "us",
) -> list[LookupResult]:
    """Search Audible catalog API for audiobooks using the audible package."""
    import os

    if not os.path.exists(AUDIBLE_AUTH_FILE):
        return []

    query = clean_query(title, author)
    if not query:
        return []

    cache_query = f"audible:{locale}:{query}"
    cached = _get_cached(cache_query, "audible", db)
    if cached is not None:
        return cached

    results: list[LookupResult] = []
    try:
        import audible

        auth = audible.Authenticator.from_file(AUDIBLE_AUTH_FILE)
        async with audible.AsyncClient(auth=auth) as client:
            params = {
                "title": title,
                "num_results": 5,
                "response_groups": (
                    "contributors,product_attrs,product_desc,media,series"
                ),
                "products_sort_by": "Relevance",
            }
            if author:
                params["author"] = author

            data = await client.get(
                "1.0/catalog/products", **params
            )

        for product in (data.get("products") or [])[:5]:
            item_title = product.get("title", "")

            # Authors
            authors_list = [
                a.get("name", "")
                for a in (product.get("authors") or [])
                if a.get("name")
            ]
            item_author = authors_list[0] if authors_list else None

            # Narrators
            narrators_list = [
                n.get("name", "")
                for n in (product.get("narrators") or [])
                if n.get("name")
            ]
            item_narrator = ", ".join(narrators_list) if narrators_list else None

            # Release date / year
            release_date = product.get("release_date") or ""
            year = release_date[:4] if len(release_date) >= 4 else None

            # Series info
            series_name = None
            series_pos = None
            series_list = product.get("series") or []
            if series_list:
                primary = series_list[0]
                series_name = primary.get("title")
                series_pos = primary.get("sequence")

            # Cover image
            images = product.get("product_images") or {}
            cover_url = images.get("500") or images.get("1024") or None

            # Description
            summary = product.get("publisher_summary") or ""

            # Clean title
            if item_title:
                item_title = re.sub(
                    r"\s*\(Unabridged\)", "", item_title, flags=re.IGNORECASE
                ).strip()

            results.append(
                LookupResult(
                    provider="audible",
                    title=item_title or None,
                    author=item_author,
                    series=series_name,
                    series_position=series_pos,
                    year=year,
                    narrator=item_narrator,
                    description=_clean_description(summary),
                    cover_url=cover_url,
                    confidence=0.92,
                )
            )

    except Exception as e:
        logger.warning("Audible search failed for '%s': %s", title, type(e).__name__)

    _set_cached(cache_query, "audible", results, db)
    return results


async def lookup_book(
    title: str,
    author: str | None,
    api_key: str | None,
    db: Session,
) -> list[LookupResult]:
    """Search all APIs and return deduplicated results, best first."""
    audible_results = await search_audible(title, author, db)
    google_results = await search_google_books(title, author, api_key, db)
    ol_results = await search_openlibrary(title, author, db)
    itunes_results = await search_itunes(title, author, db)

    # Audible first so it wins dedup with highest confidence
    all_results = audible_results + itunes_results + google_results + ol_results

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
                    if not result.narrator and existing.narrator:
                        result.narrator = existing.narrator
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
                    if not existing.narrator and result.narrator:
                        existing.narrator = result.narrator
                is_dup = True
                break
        if not is_dup:
            seen.append(result)
    return seen


def _cache_key(query: str, provider: str) -> str:
    """Generate a cache key hash.

    Whitespace is collapsed so minor spacing differences don't cause
    cache misses (e.g. "Brandon  Sanderson" vs "Brandon Sanderson").
    """
    collapsed = re.sub(r"\s+", " ", query.lower().strip())
    normalized = f"{provider}:{collapsed}"
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
