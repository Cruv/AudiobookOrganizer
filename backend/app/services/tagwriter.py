"""Write corrected metadata back into audio file tags via mutagen.

Off by default. When enabled via the `write_tags_on_organize` user
setting, organize copies the file as usual and then patches the
destination file's tags to match the Book row (title, author, album,
year, narrator, series, series_position).

We deliberately write the DESTINATION only, never the source — the
source file is the user's authoritative copy. If they want to roll
back, they still have the untouched original.

Supports MP3 (ID3v2), MP4/M4B (iTunes-style atoms), FLAC/OGG (Vorbis
comments). Best-effort: a tag-write failure on one file logs a
warning but doesn't fail the organize.
"""

import logging
import os

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)


def write_book_tags(
    file_path: str,
    *,
    title: str | None = None,
    author: str | None = None,
    album: str | None = None,
    year: str | None = None,
    narrator: str | None = None,
    series: str | None = None,
    series_position: str | None = None,
) -> tuple[bool, str | None]:
    """Patch a single audio file's tags. Returns (ok, error_message).

    Only writes fields that are non-None — empty / missing book fields
    leave the existing tag alone.
    """
    if not os.path.isfile(file_path):
        return False, f"File not found: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".mp3":
            return _write_mp3(
                file_path, title=title, author=author, album=album,
                year=year, narrator=narrator, series=series,
                series_position=series_position,
            )
        if ext in (".m4b", ".m4a", ".mp4"):
            return _write_mp4(
                file_path, title=title, author=author, album=album,
                year=year, narrator=narrator, series=series,
                series_position=series_position,
            )
        if ext == ".flac":
            return _write_vorbis(
                FLAC(file_path), title=title, author=author, album=album,
                year=year, narrator=narrator, series=series,
                series_position=series_position,
            )
        if ext in (".ogg", ".opus"):
            return _write_vorbis(
                OggVorbis(file_path), title=title, author=author, album=album,
                year=year, narrator=narrator, series=series,
                series_position=series_position,
            )
        return False, f"Unsupported format for tag write: {ext}"
    except Exception as e:
        logger.warning(
            "Tag write failed for %s: %s", file_path, type(e).__name__,
            exc_info=True,
        )
        return False, f"{type(e).__name__}: {e}"


def _write_mp3(
    file_path: str, *,
    title: str | None, author: str | None, album: str | None,
    year: str | None, narrator: str | None, series: str | None,
    series_position: str | None,
) -> tuple[bool, str | None]:
    # Try to use Easy mode (key -> simple string). Falls back to creating
    # an empty ID3 tag block on files that don't have one yet.
    try:
        audio = EasyID3(file_path)
    except Exception:
        # File has no ID3 — create one.
        mp3 = MP3(file_path)
        try:
            mp3.add_tags()
        except Exception:
            pass
        mp3.save()
        audio = EasyID3(file_path)

    if title is not None:
        audio["title"] = title
    if author is not None:
        audio["artist"] = author
        audio["albumartist"] = author
    if album is not None:
        audio["album"] = album
    if year is not None:
        audio["date"] = year
    if narrator is not None:
        # Common audiobook convention: composer = narrator.
        audio["composer"] = narrator
    if series is not None:
        audio["grouping"] = (
            f"{series} #{series_position}" if series_position else series
        )

    audio.save()
    return True, None


_MP4_NARRATOR_KEY = "----:com.apple.iTunes:NARRATOR"
_MP4_SERIES_KEY = "----:com.apple.iTunes:SERIES"
_MP4_SERIES_POS_KEY = "----:com.apple.iTunes:SERIES-PART"


def _write_mp4(
    file_path: str, *,
    title: str | None, author: str | None, album: str | None,
    year: str | None, narrator: str | None, series: str | None,
    series_position: str | None,
) -> tuple[bool, str | None]:
    mp4 = MP4(file_path)
    if mp4.tags is None:
        mp4.add_tags()

    if title is not None:
        mp4["\xa9nam"] = title
    if author is not None:
        mp4["\xa9ART"] = author
        mp4["aART"] = author
    if album is not None:
        mp4["\xa9alb"] = album
    if year is not None:
        mp4["\xa9day"] = year
    if narrator is not None:
        # Composer atom + freeform iTunes NARRATOR for compatibility.
        mp4["\xa9wrt"] = narrator
        mp4[_MP4_NARRATOR_KEY] = narrator.encode("utf-8")
    if series is not None:
        mp4[_MP4_SERIES_KEY] = series.encode("utf-8")
    if series_position is not None:
        mp4[_MP4_SERIES_POS_KEY] = series_position.encode("utf-8")

    mp4.save()
    return True, None


def _write_vorbis(
    audio,  # FLAC or OggVorbis — both expose dict-like tag access
    *,
    title: str | None, author: str | None, album: str | None,
    year: str | None, narrator: str | None, series: str | None,
    series_position: str | None,
) -> tuple[bool, str | None]:
    if title is not None:
        audio["title"] = title
    if author is not None:
        audio["artist"] = author
        audio["albumartist"] = author
    if album is not None:
        audio["album"] = album
    if year is not None:
        audio["date"] = year
    if narrator is not None:
        audio["composer"] = narrator
        audio["narrator"] = narrator
    if series is not None:
        audio["series"] = series
    if series_position is not None:
        audio["seriespart"] = series_position
    audio.save()
    return True, None


# Referenced to keep the import alive — mutagen's File() returns one
# of the format-specific classes already, but having the alias around
# documents the entry point.
_ = MutagenFile
