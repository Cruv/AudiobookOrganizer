"""Filename and folder path parser for audiobook metadata extraction.

Uses multiple regex strategies with confidence scoring to extract
title, author, series, series position, and year from messy folder names.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz


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

# GA author with real author embedded in brackets: "GraphicAudio [Author Name]"
GRAPHIC_AUDIO_AUTHOR_BRACKET = re.compile(
    r"^(?:GraphicAudio|Graphic\s*Audio(?:\s*LLC\.?)?)\s*\[(.+?)\]$",
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

# Multi-part indicators - NOT series positions:
#   "(Part 2 of 2)", "Part 1 of 3" - with "Part" keyword (parens optional)
#   "(3 of 3)" - parenthesized N of M (parens required when no "Part")
#   "(Part 1 and 2)" - combined parts with "and"
#   "(Parts 02)" - just "Parts NN" in parens
MULTI_PART_PATTERN = re.compile(
    r"\(\s*(?:Parts?\s+)?\d+\s+(?:of|and)\s+\d+\s*\)"
    r"|Parts?\s+\d+\s+(?:of|and)\s+\d+"
    r"|\(\s*Parts?\s+\d+\s*\)",
    re.IGNORECASE,
)

# Bracket series position: [04], [01], [1] - book number in brackets
BRACKET_POSITION_PATTERN = re.compile(r"\[(\d{1,3})\]")

# GA prefix in series names: "GA - Series Name" -> "Series Name"
GA_SERIES_PREFIX = re.compile(r"^GA\s*[-–—]\s*", re.IGNORECASE)

# Known publishers/producers that should not be narrators
PUBLISHER_NARRATOR_PATTERNS = re.compile(
    r"^(?:Black Library|Heavy Entertainment|Graphic Audio(?:\s*LLC\.?)?|"
    r"GraphicAudio|Hachette|Penguin|Random House|HarperCollins|"
    r"Macmillan|Simon\s*&\s*Schuster|Audible|Brilliance|"
    r"Recorded Books|Tantor|Blackstone|BBC|Bolinda)$",
    re.IGNORECASE,
)

# Leading track/book numbers: "01 ", "01. ", "01 - "
LEADING_NUMBER_PATTERN = re.compile(r"^\d{1,3}(?:\s*[-–—.)\]]\s*|\s+)(?=[A-Z])")

# Primarch-style prefix: "P01. Title" - extract position and strip
PRIMARCH_PREFIX_PATTERN = re.compile(r"^P(\d{1,2})\.\s*", re.IGNORECASE)

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
    re.compile(r"(?:collection|complete|series|edition|publishing|books?$|antholog|omnibus|compilation|boxset|box\s*set)", re.IGNORECASE),
    re.compile(r"\d+[a-z]?\s*$", re.IGNORECASE),  # Ends with numbers (e.g. "Warhammer 40k")
    re.compile(r"^(?:the|a|an)\s", re.IGNORECASE),  # Starts with article (e.g. "The Expanse")
    re.compile(r"^audiobooks?$", re.IGNORECASE),  # Root folder name
    re.compile(
        r"^(?:warhammer|horus\s+heresy|stormlight|cosmere|forgotten\s+realms|"
        r"dragonlance|star\s+wars|star\s+trek|deathlands|outlanders)",
        re.IGNORECASE,
    ),  # Franchise names
]


def _clean_text(text: str) -> str:
    """Remove junk tokens and normalize whitespace."""
    # Replace dots and underscores with spaces (but preserve dots in numbers)
    cleaned = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    cleaned = cleaned.replace("_", " ")

    for pattern in JUNK_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    # Clean empty brackets/parens left after junk stripping
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    cleaned = re.sub(r"\{\s*\}", "", cleaned)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _strip_leading_number(text: str) -> str:
    """Strip leading track/book numbers like '01 ', '01. ', '01 - ' and 'P01.'."""
    text = PRIMARCH_PREFIX_PATTERN.sub("", text)
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
            # Skip range patterns: "Book 1-7" means books 1 through 7, not position 1
            rest = text[match.end():]
            if re.match(r"\s*[-–—]\s*\d+", rest):
                continue
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
    stripped = author.strip()
    return bool(
        GRAPHIC_AUDIO_AUTHOR_PATTERNS.match(stripped)
        or GRAPHIC_AUDIO_AUTHOR_BRACKET.match(stripped)
    )


def _extract_ga_real_author(author: str) -> str | None:
    """Extract real author from 'GraphicAudio [Author Name]' bracket patterns.

    Returns cleaned author name or None if not a GA bracket pattern.
    E.g. "GraphicAudio [William W. Johnstone / J.A. Johnstone]"
         -> "William W. Johnstone, J.A. Johnstone"
    """
    match = GRAPHIC_AUDIO_AUTHOR_BRACKET.match(author.strip())
    if match:
        real = match.group(1).strip()
        # Normalize slash separators to commas
        real = re.sub(r"\s*/\s*", ", ", real)
        return real
    return None


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

            # Resolve final title
            final_title = _sanitize_name(title_clean) if title_clean else title

            # If title is just a multi-part indicator ("Part 01", "Disc 2"),
            # use the parent folder (series) as the real title
            if not final_title or re.match(
                r"^(?:Part|Pt|Disc|CD)\s*\d*$", final_title, re.IGNORECASE
            ):
                final_title = series

            # Lower confidence when author looks suspect (franchise, range, etc.)
            # so leaf-name strategies that correctly parse author can win
            confidence = 0.85
            if _is_suspect_author(author):
                confidence = 0.65

            return ParsedMetadata(
                author=author,
                series=series,
                series_position=pos,
                title=final_title,
                confidence=confidence,
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

    # Extract real author from "GraphicAudio [Author Name]" bracket patterns
    if tag_author:
        ga_real = _extract_ga_real_author(tag_author)
        if ga_real:
            tag_author = ga_real

    # Reject tag author if it matches the title (mislabeled tags)
    if tag_author and parsed.title and fuzzy_match(tag_author, parsed.title):
        tag_author = None
    if tag_author and tag_album and fuzzy_match(tag_author, tag_album):
        tag_author = None

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
        elif parsed.title and parsed.author:
            # Check if parsed title is actually the author name
            # (happens when folder = author, not book title)
            title_words = set(re.sub(r"[^a-z0-9 ]", "", parsed.title.lower()).split())
            author_words = set(re.sub(r"[^a-z0-9 ]", "", parsed.author.lower()).split())
            if title_words and title_words.issubset(author_words):
                parsed.title = tag_album
                parsed.confidence = min(parsed.confidence + 0.05, 1.0)

    # Use tag series if available (from grouping/contentgroup tags)
    tag_series = tags.get("series")
    if _is_generic_value(tag_series):
        tag_series = None
    if tag_series:
        if parsed.series and fuzzy_match(parsed.series, tag_series):
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)
        elif not parsed.series:
            parsed.series = tag_series
            parsed.confidence = min(parsed.confidence + 0.05, 1.0)
        else:
            # Parsed and tag series disagree - prefer tag
            parsed.series = tag_series

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

    # --- Post-merge cleanup ---

    # Clean GA prefix from series: "GA - Series Name" -> "Series Name"
    if parsed.series:
        parsed.series = GA_SERIES_PREFIX.sub("", parsed.series).strip()
        if not parsed.series:
            parsed.series = None

    # Dedup: if series matches author, clear series (folder repeated author as series)
    if parsed.series and parsed.author and fuzzy_match(parsed.series, parsed.author):
        parsed.series = None

    # Strip author name from end of title: "Ashes of Man Christopher Ruocchio" -> "Ashes of Man"
    if parsed.title and parsed.author and not _is_suspect_author(parsed.author):
        author_words = parsed.author.lower().split()
        if len(author_words) >= 2:
            title_words = parsed.title.split()
            if len(title_words) > len(author_words):
                tail = [w.lower() for w in title_words[-len(author_words):]]
                if tail == author_words:
                    parsed.title = " ".join(title_words[:-len(author_words)]).strip()
                    parsed.title = re.sub(r"[\s\-–—,]+$", "", parsed.title).strip()

    # Clean empty parens/brackets that may remain in title
    if parsed.title:
        parsed.title = re.sub(r"\(\s*\)", "", parsed.title)
        parsed.title = re.sub(r"\[\s*\]", "", parsed.title)
        parsed.title = re.sub(r"\s+", " ", parsed.title).strip()

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


def _normalize_for_match(s: str) -> str:
    """Normalize a string for matching: lowercase, strip articles, collapse whitespace."""
    if not s:
        return ""
    normalized = s.lower().strip()
    # Strip leading articles (the, a, an) — "The Final Empire" vs "Final Empire" should match
    normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized)
    # Collapse whitespace and punctuation runs
    normalized = re.sub(r"[\s_.\-–—:;,]+", " ", normalized).strip()
    return normalized


def similarity(a: str | None, b: str | None) -> float:
    """Return a 0.0–1.0 similarity score between two strings.

    Uses rapidfuzz token_set_ratio which handles word reordering and
    partial overlap. Normalizes case, articles, and punctuation first.
    """
    if not a or not b:
        return 0.0
    na = _normalize_for_match(a)
    nb = _normalize_for_match(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # token_set_ratio handles word reordering and extra/missing words well
    return fuzz.token_set_ratio(na, nb) / 100.0


def fuzzy_match(a: str | None, b: str | None, threshold: float = 0.80) -> bool:
    """Binary check: are these two strings similar enough to be considered the same?

    Default threshold 0.80 matches the strictness of the old handrolled
    character-ratio check but is order-aware (fixes false positives where
    "starwars" and "starwhores" scored the same character ratio).
    """
    if not a or not b:
        return False
    return similarity(a, b) >= threshold


def _year_proximity(a: str | None, b: str | None) -> float:
    """Score year similarity: 1.0 if equal, 0.5 if within 1 year, 0.0 otherwise."""
    if not a or not b:
        return 0.0
    try:
        ya, yb = int(re.match(r"\d{4}", a).group()), int(re.match(r"\d{4}", b).group())
    except (AttributeError, ValueError):
        return 0.0
    diff = abs(ya - yb)
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.5
    return 0.0


# Weights for each field when scoring a lookup result against parsed data.
# Title dominates, author is the strong secondary, series/year/narrator break ties.
_MATCH_WEIGHTS = {
    "title": 0.50,
    "author": 0.30,
    "series": 0.10,
    "year": 0.05,
    "narrator": 0.05,
}


def auto_match_score(
    parsed: ParsedMetadata,
    result_title: str | None,
    result_author: str | None,
    result_series: str | None = None,
    result_year: str | None = None,
    result_narrator: str | None = None,
) -> float:
    """Score how well a lookup result matches parsed metadata, 0.0 to 1.0.

    Weighted, partial-credit: each field contributes its weight times its
    similarity. Weights of fields that are missing on BOTH sides are
    redistributed proportionally to the remaining fields so a book with
    no series/year/narrator can still reach 1.0 on title+author alone.
    """
    field_scores: dict[str, float | None] = {}

    # Title and author are always expected
    field_scores["title"] = similarity(parsed.title, result_title) if (parsed.title and result_title) else None
    field_scores["author"] = similarity(parsed.author, result_author) if (parsed.author and result_author) else None
    field_scores["series"] = similarity(parsed.series, result_series) if (parsed.series and result_series) else None
    field_scores["year"] = _year_proximity(parsed.year, result_year) if (parsed.year and result_year) else None
    field_scores["narrator"] = similarity(parsed.narrator, result_narrator) if (parsed.narrator and result_narrator) else None

    # Redistribute weight from fields missing on both sides
    active_weight = sum(w for k, w in _MATCH_WEIGHTS.items() if field_scores[k] is not None)
    if active_weight == 0:
        return 0.0

    score = 0.0
    for field, weight in _MATCH_WEIGHTS.items():
        s = field_scores[field]
        if s is None:
            continue
        score += (weight / active_weight) * s

    # Penalty when parsed side has a value but result side doesn't (missing data):
    # Shouldn't fully disqualify but should dent confidence so a richer result wins.
    for field in ("title", "author"):
        parsed_val = getattr(parsed, field, None)
        result_val = {"title": result_title, "author": result_author}[field]
        if parsed_val and not result_val:
            score *= 0.85

    return min(score, 1.0)


def clean_narrator(narrator: str | None, edition: str | None = None) -> str | None:
    """Clean and normalize narrator value.

    - Rejects GraphicAudio/publishers as narrator
    - Extracts real name from GA bracket patterns
    - Strips role descriptions ("as Character") and credit suffixes
    - Normalizes long GA cast lists to "Full Cast"
    - Strips trailing punctuation
    """
    if not narrator:
        return None

    narrator = narrator.strip()
    if not narrator:
        return None

    # Extract real name from "GraphicAudio [Author Name]" in narrator field
    ga_real = _extract_ga_real_author(narrator)
    if ga_real:
        narrator = ga_real

    # Reject GraphicAudio as narrator
    if _is_graphic_audio_author(narrator):
        return None

    # Split comma-separated names and filter out publishers
    parts = [n.strip() for n in narrator.split(",") if n.strip()]
    clean_parts = []
    for part in parts:
        if not PUBLISHER_NARRATOR_PATTERNS.match(part):
            clean_parts.append(part)
    if not clean_parts:
        return None

    # Normalize long GA cast lists to "Full Cast"
    if edition == "Graphic Audio":
        if len(clean_parts) >= 4 or any("full cast" in p.lower() for p in clean_parts):
            return "Full Cast"

    narrator = ", ".join(clean_parts)

    # Strip "as Character" role descriptions: "Richard Rohan as Ryan & Jak"
    narrator = re.sub(r"\s+as\s+\w+(?:\s*[&,]\s*\w+)*\s*$", "", narrator)

    # Strip "With performances by..." suffixes
    narrator = re.sub(
        r"\s*(?:With\s+performances?\s+by|[Pp]erformed\s+by).*$", "", narrator
    )

    # Strip trailing punctuation (semicolons, periods, commas)
    narrator = re.sub(r"[;.,]+\s*$", "", narrator).strip()

    return narrator if narrator else None
