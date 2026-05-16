"""Audio file integrity check.

Quick "is this file truncated/corrupt?" check using mutagen. The
expensive option would be a full ffprobe pass, but mutagen already
opens the file to read tags and exposes a `.info.length` (duration in
seconds) for most formats. Comparing that to file size + bitrate
catches the most common failure mode — a download that stopped
partway, leaving a file with intact headers but missing the back half.

This is deliberately fast and approximate. Calling it during the scan
adds ~0.05s per file, so on a 5000-file library it's a few minutes
extra. It's surfaced via a per-book `integrity_status` field that the
UI can badge red so the user knows to re-download before organizing.
"""

import logging
import os

from mutagen import File as MutagenFile

logger = logging.getLogger(__name__)


# If mutagen reports a duration that's < this fraction of what the
# file size would imply at a typical audiobook bitrate, we flag the
# file as "short" (likely truncated).
_TRUNCATION_THRESHOLD = 0.5
# Lower bound on how many bytes a healthy minute of audio occupies at
# the LOWEST realistic audiobook bitrate (~32 kbps for spoken-word).
# Used as the divisor below — if file_size_per_minute_actual is much
# less than this, the file is suspiciously small for its duration.
_MIN_BYTES_PER_MINUTE = 32 * 1024 * 60 // 8  # ≈ 240 KB/min @ 32 kbps


def check_file(path: str) -> tuple[str, str | None]:
    """Return (status, detail) for one audio file.

    status:
      - 'ok': file opens and reports a duration consistent with its size.
      - 'unreadable': mutagen returns None — no parseable headers.
      - 'short': duration is suspiciously small for the byte size.
                 Almost always means the download was truncated.
      - 'unchecked': size/duration data was missing; can't conclude.
    detail: free-form message, only set for non-ok statuses.
    """
    if not os.path.isfile(path):
        return "unreadable", f"File not found: {path}"

    try:
        size = os.path.getsize(path)
    except OSError as e:
        return "unreadable", f"stat failed: {e}"

    try:
        audio = MutagenFile(path)
    except Exception as e:
        return "unreadable", f"mutagen failed: {type(e).__name__}: {e}"

    if audio is None or not hasattr(audio, "info"):
        return "unreadable", "mutagen returned no parseable info"

    duration = getattr(audio.info, "length", None)
    if duration is None or duration <= 0:
        return "unchecked", "duration unknown"

    # Bytes per minute the file actually has on disk.
    minutes = duration / 60.0
    if minutes <= 0:
        return "unchecked", "duration zero"
    bytes_per_minute = size / minutes

    if bytes_per_minute < _MIN_BYTES_PER_MINUTE * _TRUNCATION_THRESHOLD:
        return (
            "short",
            f"~{duration:.0f}s declared but only {size} bytes "
            f"(~{int(bytes_per_minute)} B/min, far below typical "
            f"audiobook bitrate). Likely truncated download.",
        )

    return "ok", None
