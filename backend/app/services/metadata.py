"""Audio file metadata reader using mutagen.

Reads tags from multiple audio files in a folder and builds
consensus metadata from the most common values.
"""

import logging
import os
import re
from collections import Counter

from mutagen import File as MutagenFile
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".m4b", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".aac"}

# Maximum number of files to sample for consensus
MAX_SAMPLE_FILES = 10


def is_audio_file(filepath: str) -> bool:
    """Check if a file is a supported audio file by extension."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in AUDIO_EXTENSIONS


def read_tags(file_path: str) -> dict[str, str | None]:
    """Read audio tags from a file using mutagen.

    Returns a normalized dict with keys:
    title, author, album, year, track, narrator, genre, series, comment
    """
    result: dict[str, str | None] = {
        "title": None,
        "author": None,
        "album": None,
        "year": None,
        "track": None,
        "narrator": None,
        "genre": None,
        "series": None,
        "comment": None,
    }

    try:
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            return result

        if isinstance(audio, MP4):
            return _read_mp4_tags(file_path)

        # EasyID3-compatible tags (MP3, FLAC, OGG, etc.)
        result["title"] = _get_tag(audio, "title")
        result["author"] = _get_tag(audio, "artist") or _get_tag(audio, "albumartist")
        result["album"] = _get_tag(audio, "album")
        result["year"] = _get_tag(audio, "date")
        result["track"] = _get_tag(audio, "tracknumber")
        result["genre"] = _get_tag(audio, "genre")

        # Narrator can be in composer, performer, or conductor fields
        result["narrator"] = (
            _get_tag(audio, "composer")
            or _get_tag(audio, "performer")
            or _get_tag(audio, "conductor")
        )

        # Some taggers use grouping or content group for series
        result["series"] = _get_tag(audio, "grouping") or _get_tag(audio, "contentgroup")

        # Comments may contain useful metadata
        result["comment"] = _get_tag(audio, "comment")

    except Exception:
        logger.debug("Failed to read tags from %s", file_path, exc_info=True)

    return result


def _read_mp4_tags(file_path: str) -> dict[str, str | None]:
    """Read tags from MP4/M4B files."""
    result: dict[str, str | None] = {
        "title": None,
        "author": None,
        "album": None,
        "year": None,
        "track": None,
        "narrator": None,
        "genre": None,
        "series": None,
        "comment": None,
    }

    try:
        mp4 = MP4(file_path)
        tags = mp4.tags
        if not tags:
            return result

        result["title"] = _get_mp4_tag(tags, "\xa9nam")
        result["author"] = _get_mp4_tag(tags, "\xa9ART") or _get_mp4_tag(tags, "aART")
        result["album"] = _get_mp4_tag(tags, "\xa9alb")
        result["year"] = _get_mp4_tag(tags, "\xa9day")
        result["genre"] = _get_mp4_tag(tags, "\xa9gen")
        result["comment"] = _get_mp4_tag(tags, "\xa9cmt")

        # Narrator: try composer, then writer, then encoding tool comment
        result["narrator"] = (
            _get_mp4_tag(tags, "\xa9wrt")  # composer/writer
            or _get_mp4_tag(tags, "----:com.apple.iTunes:NARRATOR")
        )

        # Series: try custom iTunes tags
        result["series"] = (
            _get_mp4_tag(tags, "----:com.apple.iTunes:SERIES")
            or _get_mp4_tag(tags, "\xa9grp")  # grouping
        )

        track = tags.get("trkn")
        if track and isinstance(track, list) and len(track) > 0:
            result["track"] = str(track[0][0]) if isinstance(track[0], tuple) else str(track[0])

    except Exception:
        logger.debug("Failed to read MP4 tags from %s", file_path, exc_info=True)

    return result


def read_folder_tags(folder_path: str) -> dict[str, str | None]:
    """Read tags from multiple audio files in a folder and build consensus.

    Samples up to MAX_SAMPLE_FILES files and uses the most common
    non-empty values for each field.
    """
    audio_files = []
    for filename in sorted(os.listdir(folder_path)):
        filepath = os.path.join(folder_path, filename)
        if os.path.isfile(filepath) and is_audio_file(filepath):
            audio_files.append(filepath)
            if len(audio_files) >= MAX_SAMPLE_FILES:
                break

    if not audio_files:
        return {
            "title": None, "author": None, "album": None, "year": None,
            "track": None, "narrator": None, "genre": None, "series": None,
            "comment": None,
        }

    # Collect all tag values across files
    all_tags: list[dict[str, str | None]] = []
    for filepath in audio_files:
        all_tags.append(read_tags(filepath))

    # Build consensus: most common non-empty value per field
    consensus: dict[str, str | None] = {}
    for field in ["author", "album", "year", "narrator", "genre", "series"]:
        values = [t[field] for t in all_tags if t.get(field)]
        if values:
            counter = Counter(values)
            consensus[field] = counter.most_common(1)[0][0]
        else:
            consensus[field] = None

    # Album tag usually holds the book title; individual file titles are
    # chapter names. But when album is missing, fall back to the most
    # common per-file title tag with chapter/track boilerplate stripped —
    # otherwise books without an album tag contribute nothing from tags.
    consensus["title"] = consensus.get("album")
    if not consensus["title"]:
        stripped_titles: list[str] = []
        for t in all_tags:
            title_val = t.get("title")
            if not title_val:
                continue
            cleaned = re.sub(
                r"^(?:chapter|track|part|disc|cd)\s*\d+\s*[-–—:.]*\s*",
                "",
                title_val,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"^\s*\d+\s*[-–—:.]+\s*", "", cleaned).strip()
            if cleaned and len(cleaned) >= 3:
                stripped_titles.append(cleaned)
        if stripped_titles:
            consensus["title"] = Counter(stripped_titles).most_common(1)[0][0]

    # Track number: not useful for consensus
    consensus["track"] = all_tags[0].get("track") if all_tags else None

    # Comments: check first file's comment for metadata clues
    consensus["comment"] = all_tags[0].get("comment") if all_tags else None

    # Try to extract narrator from comment if not found in tags
    if not consensus["narrator"] and consensus.get("comment"):
        narrator_match = re.search(
            r"(?:narrated|read|performed)\s+by\s+([^,\n]+)",
            consensus["comment"],
            re.IGNORECASE,
        )
        if narrator_match:
            consensus["narrator"] = narrator_match.group(1).strip()

    return consensus


def _get_tag(audio, key: str) -> str | None:
    """Safely get a tag value from an EasyID3-compatible object."""
    try:
        values = audio.get(key)
        if values and isinstance(values, list) and len(values) > 0:
            val = str(values[0]).strip()
            return val if val else None
        if values and isinstance(values, str):
            val = values.strip()
            return val if val else None
    except Exception:
        pass
    return None


def _get_mp4_tag(tags, key: str) -> str | None:
    """Safely get a tag value from MP4 tags."""
    try:
        values = tags.get(key)
        if values and isinstance(values, list) and len(values) > 0:
            val = str(values[0]).strip()
            return val if val else None
    except Exception:
        pass
    return None
