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
    narrator: str | None = None
    edition: str | None = None
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
    r"\b(?:retail|proper|repack)\b",
    r"\b(?:complete\s+(?:series|collection))\b",
    r"\b(?:graphic\s+audio)\b",
    r"\(GA\)",
    r"\(GraphicAudio\)",
    r"\(Graphic\s+Audio\)",
    r"\[Dramatized\s+Adaptation\]",
    r"\(Dramatized\s+Adaptation\)",
    r"\[.*?\]",
    r"\((?:mp3|m4b|flac|audiobook|unabridged|abridged|\d+\s*kbps).*?\)",
]

# Patterns that identify Graphic Audio as a publisher/producer (not a real author)
GRAPHIC_AUDIO_AUTHOR_PATTERNS = re.compile(
    r"^(?:GraphicAudio|Graphic\s*Audio(?:\s*LLC\.?)?|GraphicAdio)$",
    re.IGNORECASE,
)

# Edition detection patterns for folder paths and names
GRAPHIC_AUDIO_PATH_PATTERN = re.compile(
    r"Graphic\s*Audio", re.IGNORECASE
)
GRAPHIC_AUDIO_NAME_PATTERN = re.compile(
    r"\(GA\)|\[GA\]|\(GraphicAudio\)|\[GraphicAudio(?:-\d+)?\]|\(Graphic\s+Audio\)",
    re.IGNORECASE,
)
DRAMATIZED_PATTERN = re.compile(
    r"\[Dramatized\s+Adaptation\]|\(Dramatized\s+Adaptation\)",
    re.IGNORECASE,
)

# Multi-part indicators: "(Part 2 of 2)", "Part 1 of 3" - NOT series positions
MULTI_PART_PATTERN = re.compile(
    r"\(?\s*Part\s+\d+\s+of\s+\d+\s*\)?", re.IGNORECASE
)

# Bracket series position: [04], [01], [1] - book number in brackets
BRACKET_POSITION_PATTERN = re.compile(r"\[(\d{1,3})\]")

# Leading track/book numbers: "01 ", "01. ", "01 - "
LEADING_NUMBER_PATTERN = re.compile(r"^\d{1,3}(?:\s*[-–—.)\]]\s*|\s+)(?=[A-Z])")

YEAR_PATTERN = re.compile(r"(?:^|\D)((?:19|20)\d{2})(?:\D|$)")

SERIES_POSITION_PATTERNS = [
    re.compile(
        r"(?:Book|Vol(?:ume)?|Part|#|No\.?)\s*(\d+\.?\d*)", re.IGNORECASE
    ),
    re.compile(r"\b(\d+\.?\d*)\s*(?:of\s+\d+)\b", re.IGNORECASE),
]

# Narrator extraction: "narrated by Name" or "read by Name"
NARRATOR_PATTERN = re.compile(
    r"(?:narrated|read|performed)\s+by\s+([^,\-–—()\[\]]+)", re.IGNORECASE
)

# Values that indicate the tag field is generic/useless
GENERIC_VALUES = re.compile(
    r"^(track\s*\d*|unknown|various|untitled|artist|album|"
    r"audiobook|chapter\s*\d*|disc\s*\d*|part\s*\d*|"
    r"http[s]?://|www\.).*$",
    re.IGNORECASE,
)

# Author names that are clearly not real people (franchises, publishers)
SUSPECT_AUTHOR_PATTERNS = [
    re.compile(r"^\d+$"),  # Pure numbers
    re.compile(r"^.{1,2}$"),  # Too short
    re.compile(r"^.{80,}$"),  # Too long
    re.compile(r"(?:collection|complete|series|edition|publishing|books?$)", re.IGNORECASE),
    re.compile(r"\d+[a-z]?\s*$", re.IGNORECASE),  # Ends with numbers (e.g. "Warhammer 40k")
    re.compile(r"^(?:the|a|an)\s", re.IGNORECASE),  # Starts with article (e.g. "The Expanse")
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


def _strip_leading_number(text: str) -> str:
    """Strip leading track/book numbers like '01 ', '01. ', '01 - '."""
    return LEADING_NUMBER_PATTERN.sub("", text)


def _extract_narrator(text: str) -> tuple[str | None, str]:
    """Extract narrator from 'narrated by X' patterns."""
    match = NARRATOR_PATTERN.search(text)
    if match:
        narrator = match.group(1).strip()
        cleaned = text[: match.start()] + text[match.end() :]
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return narrator, cleaned
    return None, text


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


def _extract_bracket_position(text: str) -> tuple[str | None, str]:
    """Extract series position from bracket notation like [04], [01].

    Must be called BEFORE _clean_text which strips all [.*?] content.
    """
    match = BRACKET_POSITION_PATTERN.search(text)
    if match:
        pos = str(int(match.group(1)))  # "04" -> "4"
        cleaned = text[: match.start()] + text[match.end() :]
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return pos, cleaned
    return None, text


def _extract_series_position(text: str) -> tuple[str | None, str]:
    """Extract series position number from text."""
    # Strip multi-part indicators first - "(Part 2 of 2)" is NOT a series position
    text = MULTI_PART_PATTERN.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)  # Clean leftover empty parens
    text = re.sub(r"\s+", " ", text).strip()

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


def _is_generic_value(value: str | None) -> bool:
    """Check if a value is generic/useless metadata."""
    if not value:
        return True
    return bool(GENERIC_VALUES.match(value.strip()))


def _is_suspect_author(author: str | None) -> bool:
    """Check if an author name looks invalid (franchise, publisher, etc.)."""
    if not author:
        return True
    if _is_graphic_audio_author(author):
        return True
    for pattern in SUSPECT_AUTHOR_PATTERNS:
        if pattern.search(author):
            return True
    return False


def _is_graphic_audio_author(author: str | None) -> bool:
    """Check if an author value is actually GraphicAudio (publisher, not a person)."""
    if not author:
        return False
    return bool(GRAPHIC_AUDIO_AUTHOR_PATTERNS.match(author.strip()))


def detect_edition(
    folder_path: str,
    folder_name: str | None = None,
    tags: dict[str, str | None] | None = None,
) -> str | None:
    """Detect audiobook edition from folder path, name, and tags.

    Returns edition string (e.g. "Graphic Audio") or None.
    """
    # Check folder path for "Graphic Audio"
    if GRAPHIC_AUDIO_PATH_PATTERN.search(folder_path):
        return "Graphic Audio"

    # Check folder name for GA markers
    if folder_name and GRAPHIC_AUDIO_NAME_PATTERN.search(folder_name):
        return "Graphic Audio"

    # Check tag_author for GraphicAudio variants
    if tags:
        tag_author = tags.get("author")
        if tag_author and _is_graphic_audio_author(tag_author):
            return "Graphic Audio"

        # Check tag_title/tag_album for [Dramatized Adaptation]
        for field in ("title", "album"):
            val = tags.get(field)
            if val and DRAMATIZED_PATTERN.search(val):
                return "Graphic Audio"

    return None


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


def _strategy_title_dash_author(text: str) -> ParsedMetadata | None:
    """Pattern: Title - Author (reverse of author-title, tried last)."""
    pattern = re.compile(r"^(?P<title>.+?)\s*[-–—]\s*(?P<author>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)$")
    match = pattern.match(text)
    if match:
        author = _sanitize_name(match.group("author"))
        title = _sanitize_name(match.group("title"))
        # Only match if author looks like a real name (First Last)
        if author and title and not _is_suspect_author(author):
            return ParsedMetadata(
                title=title, author=author, confidence=0.70
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

        # Extract bracket position (e.g. [04]) before junk cleaning removes it
        bracket_pos, title_no_bracket = _extract_bracket_position(title_candidate)

        # Check if the middle part looks like a series (short, might have numbers)
        author = _sanitize_name(_clean_text(author_candidate))
        series = _sanitize_name(_clean_text(series_candidate))
        title = _sanitize_name(_clean_text(_strip_leading_number(title_no_bracket)))

        if author and series and title:
            pos, series_clean = _extract_series_position(title)
            if not pos:
                pos, series_clean2 = _extract_series_position(series)
                if pos:
                    series = _sanitize_name(series_clean2)
                title_clean = title
            else:
                title_clean = series_clean

            # Prefer bracket position [04] over text-extracted position
            if bracket_pos:
                pos = bracket_pos

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
        title = _sanitize_name(_clean_text(_strip_leading_number(title_candidate)))
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

    # Extract bracket position (e.g. [04]) before junk cleaning removes it
    bracket_pos, leaf_no_bracket = _extract_bracket_position(leaf)

    cleaned = _clean_text(leaf_no_bracket)

    # Strip leading track/book numbers
    cleaned = _strip_leading_number(cleaned)

    # Extract narrator before other processing
    narrator, cleaned = _extract_narrator(cleaned)

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
        _strategy_title_dash_author,
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

    # Apply bracket position if no series position found
    if bracket_pos and not best.series_position:
        best.series_position = bracket_pos

    # Apply extracted narrator
    if narrator and not best.narrator:
        best.narrator = narrator

    # Apply year to the best result
    if year and not best.year:
        best.year = year
        best.confidence = min(best.confidence + 0.05, 1.0)

    # Confidence adjustments
    if best.title and len(best.title) < 3:
        best.confidence = max(best.confidence - 0.10, 0.0)
    if best.title and len(best.title) > 100:
        best.confidence = max(best.confidence - 0.10, 0.0)
    if _is_suspect_author(best.author):
        best.confidence = max(best.confidence - 0.15, 0.0)

    return best


def merge_with_tags(
    parsed: ParsedMetadata, tags: dict[str, str | None]
) -> ParsedMetadata:
    """Merge parsed metadata with audio file tag data.

    Tags generally win for author/title when present and non-generic.
    """
    tag_author = tags.get("author")
    tag_title = tags.get("title")
    tag_album = tags.get("album")
    tag_year = tags.get("year")
    tag_narrator = tags.get("narrator")

    # Filter out generic tag values
    if _is_generic_value(tag_author):
        tag_author = None
    if _is_generic_value(tag_title):
        tag_title = None
    if _is_generic_value(tag_album):
        tag_album = None
    if _is_generic_value(tag_narrator):
        tag_narrator = None

    # Clean edition markers from tag values before using them
    if tag_title:
        tag_title = DRAMATIZED_PATTERN.sub("", tag_title).strip()
        tag_title = re.sub(r"\s+", " ", tag_title).strip() or None
    if tag_album:
        tag_album = DRAMATIZED_PATTERN.sub("", tag_album).strip()
        tag_album = re.sub(r"\s+", " ", tag_album).strip() or None

    # Use tag author if it looks like a real name (NOT GraphicAudio)
    if tag_author and not _is_graphic_audio_author(tag_author):
        if parsed.author and fuzzy_match(parsed.author, tag_author):
            parsed.confidence = min(parsed.confidence + 0.10, 1.0)
        elif not parsed.author or _is_suspect_author(parsed.author):
            parsed.author = tag_author
            parsed.source = "tag"
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)
        else:
            # Tag and parsed disagree - prefer tag for author
            parsed.author = tag_author
            parsed.source = "tag"

    # Use tag album as title if it looks real (album is usually the book title)
    if tag_album:
        if parsed.title and fuzzy_match(parsed.title, tag_album):
            parsed.confidence = min(parsed.confidence + 0.10, 1.0)
        elif not parsed.title:
            parsed.title = tag_album
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)

    # Use individual track title to extract series info
    if tag_title and tag_album and tag_title != tag_album:
        # If title has series info the album doesn't, try to extract it
        if not parsed.series:
            pos, _ = _extract_series_position(tag_title)
            if pos:
                parsed.series_position = pos

    # Use tag year if we don't have one
    if tag_year and not parsed.year:
        # Clean year (might be "2020-01-15" format)
        year_match = re.match(r"(\d{4})", tag_year)
        if year_match:
            parsed.year = year_match.group(1)
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)

    # Use narrator from tags
    if tag_narrator and not parsed.narrator:
        parsed.narrator = tag_narrator

    return parsed


def clean_query(title: str | None, author: str | None = None) -> str:
    """Clean a title/author for use as a search query.

    Strips track numbers, junk tokens, year, and other noise to produce
    a clean search string.
    """
    parts = []
    if title:
        q = _clean_text(title)
        q = _strip_leading_number(q)
        q = re.sub(r"\b\d{4}\b", "", q)  # strip years
        q = re.sub(r"\s+", " ", q).strip()
        if q:
            parts.append(q)
    if author and not _is_suspect_author(author):
        parts.append(author)
    return " ".join(parts)


def fuzzy_match(a: str, b: str) -> bool:
    """Check if two strings are similar using normalized comparison."""
    norm_a = re.sub(r"[^a-z0-9]", "", a.lower())
    norm_b = re.sub(r"[^a-z0-9]", "", b.lower())
    if not norm_a or not norm_b:
        return False
    # Check containment
    if norm_a in norm_b or norm_b in norm_a:
        return True
    # Levenshtein-like: check if edit distance is small relative to length
    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if len(shorter) < 3:
        return shorter == longer
    # Check common character ratio
    common = sum(1 for c in shorter if c in longer)
    ratio = common / len(shorter)
    if ratio >= 0.8:
        # Also check prefix overlap
        prefix_len = 0
        for ca, cb in zip(norm_a, norm_b):
            if ca == cb:
                prefix_len += 1
            else:
                break
        return prefix_len >= min(len(norm_a), len(norm_b)) * 0.5
    return False


def auto_match_score(parsed: ParsedMetadata, result_title: str | None, result_author: str | None) -> float:
    """Score how well a lookup result matches parsed metadata. 0.0 to 1.0."""
    score = 0.0
    if parsed.title and result_title:
        if fuzzy_match(parsed.title, result_title):
            score += 0.6
    if parsed.author and result_author:
        if fuzzy_match(parsed.author, result_author):
            score += 0.4
    elif not parsed.author and result_author:
        # No parsed author - partial credit if title matched
        score += 0.1
    return score
