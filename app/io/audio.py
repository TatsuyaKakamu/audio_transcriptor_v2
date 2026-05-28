"""Audio file helpers."""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".caf"}
)


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
