"""Placeholder transcription backend.

Transcription has no "skip" path (you cannot produce minutes without text), so
this backend is never selected by the factory. It exists to give callers an
explicit, always-unavailable sentinel.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import NoTranscriptionBackendError
from app.core.models import Transcript
from app.transcription.base import TranscriptionBackend, TranscriptionOptions


class NoneTranscriptionBackend(TranscriptionBackend):
    name = "none"

    def is_available(self) -> bool:
        return False

    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        raise NoTranscriptionBackendError("no transcription backend is available")
