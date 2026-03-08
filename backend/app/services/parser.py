"""Filename and folder path parser for audiobook metadata extraction.

Uses multiple regex strategies with confidence scoring to extract
title, author, series, series position, and year from messy folder names.
"""

import re
from dataclasses import dataclass, field


@dataclass
class ParsedMetadata:
    title: str | None = None
    author: str | None = None
    series: str | None = None
    series_position: str | None = None
    year: str | None = None
    confidence: float = 0.0
    source: str = "parsed"


# Junk tokens commonly found in audiobook folder names
JUNK_PATTERNS = [
    r"\b(?:un)?abridged\b",
    r"\b\d{2,3}\s*kbps\b",
    r"\b(?:mp3|m4b|m4a|flac|ogg|aac|wma|opus)\b",
    r"\b(?:cbr|vbr)\b",
    r"\b\d{2}\.?\d?\s*khz\b",
    r"\b(?:audiobook|audio\s*book)\b",
    r"\b(?:narrated\s+by)\b",
    r"\b(?:hq|lq|high\s*quality)\b",
    r"\[.*?\]",
    r"\((?:mp3|m4b|flac|audiobook|unabridged|abridged|\d+\s*kbps).*?\)",
]

YEAR_PATTERN = re.compile(r"(?:^|\D)((?:19|20)\d{2})(?:\D|$)")

SERIES_POSITION_PATTERNS = [
    re.compile(
        r"(?:Book|Vol(?:ume)?|Part|#|No\.?)\s*(\d+\.?\d*)", re.IGNORECASE
    ),
    re.compile(r"\b(\d+\.?\d*)\s*(?:of\s+\d+)\b", re.IGNORECASE),
]


def _clean_text(text: str) -> str:
    """Remove junk tokens and normalize whitespace."""
    # Replace dots and underscores with spaces (but preserve dots in numbers)
    cleaned = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    cleaned = cleaned.replace("_", " ")

    for pattern in JUNK_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_year(text: str) -> tuple[str | None, str]:
    """Extract a 4-digit year from text. Returns (year, text_without_year)."""
    match = YEAR_PATTERN.search(text)
    if match:
        year = match.group(1)
        # Remove the year from the text
        cleaned = text[: match.start(1)] + text[match.end(1) :]
        # Clean up leftover parentheses/brackets
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return year, cleaned
    return None, text


def _extract_series_position(text: str) -> tuple[str | None, str]:
    """Extract series position number from text."""
    for pattern in SERIES_POSITION_PATTERNS:
        match = pattern.search(text)
        if match:
            position = match.group(1)
            # Remove the series position pattern from text
            cleaned = text[: match.start()] + text[match.end() :]
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return position, cleaned
    return None, text


def _sanitize_name(name: str) -> str:
    """Clean up a name after extraction - remove leading/trailing separators."""
    name = re.sub(r"^[\s\-–—,.:]+|[\s\-–—,.:]+$", "", name)
    return name.strip()


def _strategy_author_series_title(text: str) -> ParsedMetadata | None:
    """Pattern: Author Name - Series Name Book N - Title"""
    pattern = re.compile(
        r"^(?P<author>.+?)\s*[-–—]\s*(?P<series>.+?)\s+"
        r"(?:Book|Vol(?:ume)?|#|No\.?)\s*(?P<pos>\d+\.?\d*)"
        r"\s*[-–—]\s*(?P<title>.+)$",
        re.IGNORECASE,
    )
    match = pattern.match(text)
    if match:
        return ParsedMetadata(
            author=_sanitize_name(match.group("author")),
            series=_sanitize_name(match.group("series")),
            series_position=match.group("pos"),
            title=_sanitize_name(match.group("title")),
            confidence=0.85,
        )
    return None


def _strategy_author_title(text: str) -> ParsedMetadata | None:
    """Pattern: Author Name - Book Title"""
    pattern = re.compile(r"^(?P<author>.+?)\s*[-–—]\s*(?P<title>.+)$")
    match = pattern.match(text)
    if match:
        author = _sanitize_name(match.group("author"))
        title = _sanitize_name(match.group("title"))
        # Avoid matching if "author" side has too many dashes (likely title)
        if author and title and len(author) > 1:
            result = ParsedMetadata(
                author=author, title=title, confidence=0.80
            )
            # Check if title contains series info
            pos, title_clean = _extract_series_position(title)
            if pos:
                # Try to split series from title
                series_match = re.match(
                    r"^(?P<series>.+?)\s*[-–—]\s*(?P<title>.+)$", title_clean
                )
                if series_match:
                    result.series = _sanitize_name(series_match.group("series"))
                    result.title = _sanitize_name(series_match.group("title"))
                    result.series_position = pos
                    result.confidence = 0.83
                else:
                    result.title = _sanitize_name(title_clean)
                    result.series_position = pos
            return result
    return None


def _strategy_title_by_author(text: str) -> ParsedMetadata | None:
    """Pattern: Title by Author Name"""
    pattern = re.compile(r"^(?P<title>.+?)\s+by\s+(?P<author>.+)$", re.IGNORECASE)
    match = pattern.match(text)
    if match:
        return ParsedMetadata(
            title=_sanitize_name(match.group("title")),
            author=_sanitize_name(match.group("author")),
            confidence=0.80,
        )
    return None


def _strategy_series_num_title_author(text: str) -> ParsedMetadata | None:
    """Pattern: Series #N - Title - Author"""
    pattern = re.compile(
        r"^(?P<series>.+?)\s*#\s*(?P<pos>\d+\.?\d*)"
        r"\s*[-–—]\s*(?P<title>.+?)\s*[-–—]\s*(?P<author>.+)$"
    )
    match = pattern.match(text)
    if match:
        return ParsedMetadata(
            series=_sanitize_name(match.group("series")),
            series_position=match.group("pos"),
            title=_sanitize_name(match.group("title")),
            author=_sanitize_name(match.group("author")),
            confidence=0.75,
        )
    return None


def _strategy_nested_folders(folder_path: str) -> ParsedMetadata | None:
    """Extract metadata from nested folder structure: Author/Series/Book or Author/Book."""
    parts = folder_path.replace("\\", "/").split("/")
    # Filter out empty and root-like parts
    parts = [p for p in parts if p and not re.match(r"^[A-Z]:?$", p)]

    if len(parts) < 2:
        return None

    # Take the last 2-3 meaningful parts
    if len(parts) >= 3:
        author_candidate = parts[-3]
        series_candidate = parts[-2]
        title_candidate = parts[-1]

        # Check if the middle part looks like a series (short, might have numbers)
        author = _sanitize_name(_clean_text(author_candidate))
        series = _sanitize_name(_clean_text(series_candidate))
        title = _sanitize_name(_clean_text(title_candidate))

        if author and series and title:
            pos, series_clean = _extract_series_position(title)
            if not pos:
                pos, series_clean2 = _extract_series_position(series)
                if pos:
                    series = _sanitize_name(series_clean2)
                title_clean = title
            else:
                title_clean = series_clean

            return ParsedMetadata(
                author=author,
                series=series,
                series_position=pos,
                title=_sanitize_name(title_clean) if title_clean else title,
                confidence=0.85,
            )

    if len(parts) >= 2:
        author_candidate = parts[-2]
        title_candidate = parts[-1]
        author = _sanitize_name(_clean_text(author_candidate))
        title = _sanitize_name(_clean_text(title_candidate))
        if author and title:
            return ParsedMetadata(
                author=author, title=title, confidence=0.75
            )

    return None


def parse_folder_path(folder_path: str) -> ParsedMetadata:
    """Parse an audiobook folder path to extract metadata.

    Tries multiple strategies and returns the best result by confidence.
    """
    # Get just the leaf folder name for pattern matching
    leaf = folder_path.replace("\\", "/").rstrip("/").split("/")[-1]
    cleaned = _clean_text(leaf)

    # Extract year before applying strategies
    year, cleaned_no_year = _extract_year(cleaned)

    results: list[ParsedMetadata] = []

    # Strategy: Nested folder structure
    nested = _strategy_nested_folders(folder_path)
    if nested:
        results.append(nested)

    # Try leaf-name strategies on cleaned text (without year)
    strategies = [
        _strategy_author_series_title,
        _strategy_author_title,
        _strategy_title_by_author,
        _strategy_series_num_title_author,
    ]

    for strategy in strategies:
        result = strategy(cleaned_no_year)
        if result:
            results.append(result)

    # If nothing worked, also try on the original cleaned text (with year in it)
    if not results:
        for strategy in strategies:
            result = strategy(cleaned)
            if result:
                results.append(result)

    # If still nothing, fall back to using the folder name as title
    if not results:
        results.append(
            ParsedMetadata(
                title=_sanitize_name(cleaned_no_year) or _sanitize_name(cleaned) or leaf,
                confidence=0.20,
            )
        )

    # Pick the best result
    best = max(results, key=lambda r: r.confidence)

    # Apply year to the best result
    if year and not best.year:
        best.year = year
        best.confidence = min(best.confidence + 0.05, 1.0)

    # Confidence adjustments
    if best.title and len(best.title) < 3:
        best.confidence = max(best.confidence - 0.10, 0.0)
    if best.title and len(best.title) > 100:
        best.confidence = max(best.confidence - 0.10, 0.0)
    if best.author and re.search(r"\d", best.author):
        best.confidence = max(best.confidence - 0.20, 0.0)

    return best


def merge_with_tags(
    parsed: ParsedMetadata, tags: dict[str, str | None]
) -> ParsedMetadata:
    """Merge parsed metadata with audio file tag data.

    Tags generally win for author/title when present and non-generic.
    """
    tag_author = tags.get("author")
    tag_album = tags.get("album")
    tag_year = tags.get("year")

    # Use tag author if it looks like a real name
    if tag_author and not re.match(r"^(Track|Unknown|Various)\b", tag_author, re.IGNORECASE):
        if parsed.author and _fuzzy_match(parsed.author, tag_author):
            parsed.confidence = min(parsed.confidence + 0.10, 1.0)
        elif not parsed.author:
            parsed.author = tag_author
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)
        else:
            # Tag and parsed disagree - prefer tag
            parsed.author = tag_author
            parsed.source = "tag"

    # Use tag album as title if it looks real
    if tag_album and not re.match(r"^(Track|Unknown|Untitled)\b", tag_album, re.IGNORECASE):
        if parsed.title and _fuzzy_match(parsed.title, tag_album):
            parsed.confidence = min(parsed.confidence + 0.10, 1.0)
        elif not parsed.title:
            parsed.title = tag_album
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)

    # Use tag year if we don't have one
    if tag_year and not parsed.year:
        parsed.year = tag_year
        parsed.confidence = min(parsed.confidence + 0.05, 1.0)

    return parsed


def _fuzzy_match(a: str, b: str) -> bool:
    """Simple fuzzy match - check if normalized strings are similar."""
    norm_a = re.sub(r"[^a-z0-9]", "", a.lower())
    norm_b = re.sub(r"[^a-z0-9]", "", b.lower())
    if not norm_a or not norm_b:
        return False
    # Check if one contains the other or they share a long common prefix
    if norm_a in norm_b or norm_b in norm_a:
        return True
    # Check prefix match (at least 80% of the shorter string)
    min_len = min(len(norm_a), len(norm_b))
    common = 0
    for ca, cb in zip(norm_a, norm_b):
        if ca == cb:
            common += 1
        else:
            break
    return common >= min_len * 0.8
