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
    parse_folder_path,
)

logger = logging.getLogger(__name__)


# Per-provider auto-apply thresholds. Audible gets the lowest bar
# (0.50) because:
#   - It's audiobook-native; if Audible returned ANY result for the
#     query, it's almost certainly the right book.
#   - Local match_score is dragged down by tag noise (publishers in
#     the author field, "audiobook" in the title) — Audible's own
#     metadata is more trustworthy than the local parse, so we'd
#     rather take a low-confidence Audible match than reject it and
#     fall back to bad tag data.
# iTunes gets a slightly higher bar — also audiobook-native but
# often wrong about author/edition. Google/OL are book-focused and
# only auto-apply on strong matches.
#
# Walk providers in this order and take the first per-provider top
# candidate that clears its threshold. Audible-first beats picking
# the globally highest-ranked candidate when Audible has a plausible
# answer.
PROVIDER_AUTO_APPLY_THRESHOLDS: dict[str, float] = {
    "audible": 0.50,
    "itunes": 0.65,
    "google_books": 0.75,
    "openlibrary": 0.80,
}
# Provider priority order — must match the trust ordering. Audible
# first, then iTunes, then Google, then OpenLibrary.
PROVIDER_PRIORITY: tuple[str, ...] = ("audible", "itunes", "google_books", "openlibrary")
# Providers we trust enough to overwrite series/year/narrator on the
# book when their candidate is applied. Lower-trust providers (Google,
# OpenLibrary) leave existing values alone — they're often wrong about
# audiobook-specific metadata.
TRUSTED_PROVIDERS_FOR_OVERWRITE: frozenset[str] = frozenset({"audible", "itunes"})

# Back-compat: kept as the fallback bar for providers not in
# PROVIDER_AUTO_APPLY_THRESHOLDS.
AUTO_APPLY_MATCH_THRESHOLD = 0.80


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

    # Build the lookup query from the FOLDER name, not from the
    # current book.title/book.author. Tags often poison those fields
    # (publisher in author, "audiobook" in title, etc.) — Audible's
    # search rejects garbage queries even when the right book is
    # findable. Re-parsing the folder is cheap (regex only) and gives
    # us the cleanest signal we have. We still fall back to the
    # post-merge fields when the folder parse turns up nothing.
    folder_title: str | None = None
    folder_author: str | None = None
    if book.scanned_folder and book.scanned_folder.folder_path:
        try:
            folder_parsed = parse_folder_path(book.scanned_folder.folder_path)
            if folder_parsed:
                folder_title = folder_parsed.title
                folder_author = folder_parsed.author
        except Exception:
            logger.debug(
                "parse_folder_path failed for book %s; falling back to "
                "book.title/book.author",
                book.id, exc_info=True,
            )

    lookup_title = folder_title or book.title
    lookup_author = folder_author or book.author

    query = clean_query(lookup_title, lookup_author)
    if not query or len(query) < 3:
        book.lookup_error = "Query too short to look up"
        db.commit()
        return []

    try:
        results = await lookup_book(query, lookup_author, api_key, db)
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

    # Score candidates against the CLEANEST signal we have for
    # title/author — the folder parse — but keep series/year/narrator
    # from the book itself (the user may have manually corrected
    # those). Without this, tag-poisoned book.title/book.author drag
    # every candidate's match_score down even when the folder name
    # was clearly the right book.
    parsed = ParsedMetadata(
        title=folder_title or book.title,
        author=folder_author or book.author,
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

    # Sort candidates by ranking_score (match × trust) descending. Trust
    # breaks ties between providers that scored similarly on match.
    candidates.sort(key=lambda c: c.ranking_score, reverse=True)

    if auto_apply:
        applied = _apply_best_in_priority_order(book, candidates, db)
        if applied is None:
            # Nothing cleared a provider threshold. Report the closest
            # miss so the user knows which provider was almost good
            # enough.
            top = candidates[0]
            top_threshold = PROVIDER_AUTO_APPLY_THRESHOLDS.get(
                top.provider, AUTO_APPLY_MATCH_THRESHOLD,
            )
            book.lookup_error = (
                f"Best candidate match {top.match_score:.2f} below threshold "
                f"{top_threshold:.2f} (provider: {top.provider})"
            )

    # Single commit at the end of the happy path instead of several
    # partial commits above. Early-return branches commit on their own
    # since they need to persist the lookup_error before returning.
    db.commit()
    return candidates


def _apply_best_in_priority_order(
    book: Book,
    candidates: list[LookupCandidate],
    db: Session,
) -> LookupCandidate | None:
    """Walk providers in trust order and apply the first one whose top
    candidate clears that provider's threshold.

    This means Audible's best candidate wins if it's plausibly correct
    (>= 0.50), even when an OpenLibrary result has a slightly higher
    raw match_score. Audible is the most trustworthy audiobook source
    we have, and a 0.65 Audible match is better than a 0.80 OpenLibrary
    match for an audiobook library.

    Returns the candidate that got applied, or None if no provider's
    top candidate met its threshold.
    """
    # Group candidates by provider, keeping the highest-ranking per
    # provider (candidates is already sorted desc by ranking_score).
    top_per_provider: dict[str, LookupCandidate] = {}
    for c in candidates:
        top_per_provider.setdefault(c.provider, c)

    # Walk in trust priority order; first provider whose top match
    # clears its threshold wins.
    for provider in PROVIDER_PRIORITY:
        top = top_per_provider.get(provider)
        if top is None:
            continue
        threshold = PROVIDER_AUTO_APPLY_THRESHOLDS.get(
            provider, AUTO_APPLY_MATCH_THRESHOLD,
        )
        if top.match_score >= threshold:
            apply_candidate(book, top, db)
            return top

    # Catch unknown providers that aren't in PROVIDER_PRIORITY — use
    # the legacy single threshold for those.
    for c in candidates:
        if c.provider in PROVIDER_PRIORITY:
            continue
        if c.match_score >= AUTO_APPLY_MATCH_THRESHOLD:
            apply_candidate(book, c, db)
            return c

    return None


def apply_candidate(book: Book, candidate: LookupCandidate, db: Session) -> None:
    """Copy a candidate's fields onto the book and mark it applied.

    Title and author are ALWAYS overwritten from the candidate when
    present, so re-apply after a user edit still works.

    Series / series_position / year / narrator behavior depends on
    provider trust:
      - Audible/iTunes (trusted): overwrite whatever's on the book.
        Their audiobook-specific metadata is more reliable than tag
        data, which is the source of "wrong narrator", "wrong series"
        complaints.
      - Google/OpenLibrary (book-focused, not audiobook-focused):
        only fill in fields the book is missing. They often have the
        wrong audiobook edition's series numbering or narrator info,
        so don't let them clobber better data.

    Locked books skip all of this — refresh_candidates already sets
    auto_apply=False for locked books, but if a user manually applies
    a candidate via the Candidates modal, the apply is intentional
    and we honor it.
    """
    # Unmark any previously-applied candidate for this book.
    for c in book.candidates:
        if c.applied and c.id != candidate.id:
            c.applied = False

    trusted = candidate.provider in TRUSTED_PROVIDERS_FOR_OVERWRITE

    if candidate.title:
        book.title = candidate.title
    if candidate.author:
        book.author = candidate.author

    if candidate.series and (trusted or not book.series):
        book.series = candidate.series
    if candidate.series_position and (trusted or not book.series_position):
        book.series_position = candidate.series_position
    if candidate.year and (trusted or not book.year):
        book.year = candidate.year
    if candidate.narrator and (trusted or not book.narrator):
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
