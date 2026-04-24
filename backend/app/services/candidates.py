"""Persist and apply lookup candidates for a book.

This is the glue between the network-facing lookup providers and the
Book table. Each call to `refresh_candidates` does one full lookup pass
for a single book, persists every result as a LookupCandidate row, and
optionally applies the best non-rejected one to the book's fields.

Keeping candidates in the DB (rather than in the provider's HTTP cache
only) means the UI can show them side-by-side, the user can reject a
bad match so it won't be re-suggested, and switching between providers
doesn't need to re-hit the network.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.lookup_candidate import LookupCandidate
from app.services.lookup import DEFAULT_PROVIDER_TRUST, get_provider_trust, lookup_book
from app.services.parser import (
    ParsedMetadata,
    clean_narrator,
    clean_query,
    compute_match_breakdown,
)

logger = logging.getLogger(__name__)


# Minimum ranking_score (= match_score × trust_weight) required before a
# candidate is auto-applied. Separate from the raw match threshold so
# trust-weighting actually has teeth.
AUTO_APPLY_RANKING_THRESHOLD = 0.70


async def refresh_candidates(
    book: Book,
    db: Session,
    api_key: str | None = None,
    auto_apply: bool = True,
) -> list[LookupCandidate]:
    """Re-run lookup for one book, replace its non-rejected candidates,
    and (optionally) auto-apply the best one.

    Returns the freshly-persisted LookupCandidate rows, best first.

    Locked books always get auto_apply=False regardless of the argument,
    so the user can still inspect candidates without the book being
    mutated behind their back.
    """
    if book.locked:
        auto_apply = False

    query = clean_query(book.title, book.author)
    if not query or len(query) < 3:
        book.lookup_error = "Query too short to look up"
        db.commit()
        return []

    try:
        results = await lookup_book(query, book.author, api_key, db)
    except Exception as e:
        logger.warning("Lookup failed for book %s: %s", book.id, type(e).__name__, exc_info=True)
        book.lookup_error = f"{type(e).__name__}: {str(e)[:200]}"
        db.commit()
        return []

    # Keep rejected candidate fingerprints so we don't resurrect them.
    rejected_fingerprints: set[tuple[str, str | None, str | None]] = set()
    for existing in book.candidates:
        if existing.rejected:
            rejected_fingerprints.add(_fingerprint(existing.provider, existing.title, existing.author))

    # Remove previous non-rejected candidates before writing fresh ones —
    # keeps the candidate list bounded and consistent with the lookup.
    for existing in list(book.candidates):
        if not existing.rejected:
            db.delete(existing)
    db.flush()

    parsed = ParsedMetadata(
        title=book.title,
        author=book.author,
        series=book.series,
        series_position=book.series_position,
        year=book.year,
        narrator=book.narrator,
    )

    # Cache trust weights per-provider for the span of this call so we
    # don't hit the UserSetting table once per candidate.
    trust_cache: dict[str, float] = {}

    def _trust_for(provider: str) -> float:
        if provider not in trust_cache:
            trust_cache[provider] = get_provider_trust(provider, db)
        return trust_cache[provider]

    # Warm the cache with known providers so obvious ones don't
    # generate a query each. Unknown providers fall through to the
    # per-provider DB check.
    for prov in DEFAULT_PROVIDER_TRUST:
        _trust_for(prov)

    candidates: list[LookupCandidate] = []
    for rank, result in enumerate(results):
        fp = _fingerprint(result.provider, result.title, result.author)
        if fp in rejected_fingerprints:
            continue

        breakdown = compute_match_breakdown(
            parsed,
            result.title,
            result.author,
            result_series=result.series,
            result_year=result.year,
            result_narrator=result.narrator,
        )
        trust = _trust_for(result.provider)
        match_score = breakdown.get("total") or 0.0
        ranking = match_score * trust

        candidate = LookupCandidate(
            book_id=book.id,
            provider=result.provider,
            provider_rank=rank,
            title=result.title,
            author=result.author,
            series=result.series,
            series_position=result.series_position,
            year=result.year,
            narrator=result.narrator,
            description=result.description,
            cover_url=result.cover_url,
            raw_confidence=result.confidence,
            match_score=match_score,
            trust_weight=trust,
            ranking_score=ranking,
            match_breakdown=json.dumps(breakdown),
        )
        db.add(candidate)
        candidates.append(candidate)

    db.flush()

    if not candidates:
        book.lookup_error = "No non-rejected matches from any provider"
        db.commit()
        return []

    # Clear any prior "no matches" error — we got some this time.
    book.lookup_error = None

    candidates.sort(key=lambda c: c.ranking_score, reverse=True)

    if auto_apply:
        best = candidates[0]
        if best.ranking_score >= AUTO_APPLY_RANKING_THRESHOLD:
            apply_candidate(book, best, db)
        else:
            book.lookup_error = (
                f"Best candidate ranking {best.ranking_score:.2f} below "
                f"threshold {AUTO_APPLY_RANKING_THRESHOLD:.2f}"
            )

    # Single commit at the end of the happy path instead of several
    # partial commits above. Early-return branches commit on their own
    # since they need to persist the lookup_error before returning.
    db.commit()
    return candidates


def apply_candidate(book: Book, candidate: LookupCandidate, db: Session) -> None:
    """Copy a candidate's fields onto the book and mark it applied.

    Leaves fields the user explicitly set (where the book already has a
    non-None value) alone for author/series/year/narrator; title and
    author ARE overwritten from the candidate when present so re-apply
    after editing still works.
    """
    # Unmark any previously-applied candidate for this book.
    for c in book.candidates:
        if c.applied and c.id != candidate.id:
            c.applied = False

    if candidate.title:
        book.title = candidate.title
    if candidate.author:
        book.author = candidate.author
    if candidate.series and not book.series:
        book.series = candidate.series
    if candidate.series_position and not book.series_position:
        book.series_position = candidate.series_position
    if candidate.year and not book.year:
        book.year = candidate.year
    if candidate.narrator and not book.narrator:
        book.narrator = clean_narrator(candidate.narrator, book.edition)

    book.source = f"auto:{candidate.provider}"
    book.match_confidence = candidate.match_score
    # Keep the legacy single field in sync for the existing UI.
    book.confidence = max(book.parse_confidence, candidate.match_score)

    candidate.applied = True
    candidate.rejected = False
    db.flush()


def reject_candidate(candidate: LookupCandidate, db: Session) -> None:
    """Mark a candidate as rejected. If it was applied, undo the apply."""
    candidate.rejected = True
    if candidate.applied:
        candidate.applied = False
        # Revert source to parsed — user has explicitly said "no" to the
        # applied lookup, so the book should no longer claim auto:X.
        book = candidate.book
        if book.source.startswith("auto:"):
            book.source = "parsed"
            book.match_confidence = 0.0
            book.confidence = book.parse_confidence
    db.flush()


def _fingerprint(provider: str, title: str | None, author: str | None) -> tuple[str, str | None, str | None]:
    """Normalized (provider, title, author) tuple for rejection matching."""
    def norm(s: str | None) -> str | None:
        if not s:
            return None
        return " ".join(s.lower().split())
    return (provider.lower(), norm(title), norm(author))
