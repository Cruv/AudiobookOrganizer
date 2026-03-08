"""Audio file metadata reader using mutagen."""

import os

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.mp4 import MP4

AUDIO_EXTENSIONS = {".mp3", ".m4b", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".aac"}


def is_audio_file(filepath: str) -> bool:
    """Check if a file is a supported audio file by extension."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in AUDIO_EXTENSIONS


def read_tags(file_path: str) -> dict[str, str | None]:
    """Read audio tags from a file using mutagen.

    Returns a normalized dict with keys:
    title, author, album, year, track, narrator, genre
    """
    result: dict[str, str | None] = {
        "title": None,
        "author": None,
        "album": None,
        "year": None,
        "track": None,
        "narrator": None,
        "genre": None,
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

        # Some audiobooks store narrator in composer field
        result["narrator"] = _get_tag(audio, "composer")

    except Exception:
        pass

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
        result["narrator"] = _get_mp4_tag(tags, "\xa9wrt")  # composer/writer

        track = tags.get("trkn")
        if track and isinstance(track, list) and len(track) > 0:
            result["track"] = str(track[0][0]) if isinstance(track[0], tuple) else str(track[0])

    except Exception:
        pass

    return result


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
