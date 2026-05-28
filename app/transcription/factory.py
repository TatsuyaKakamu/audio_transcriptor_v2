"""Construct transcription backends, including auto-mode fallback chains."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Config
from app.core.errors import TranscriptionFailedError
from app.core.models import Transcript
from app.transcription.apple_speech import AppleSpeechTranscriptionBackend
from app.transcription.base import TranscriptionBackend, TranscriptionOptions
from app.transcription.mlx_whisper import MlxWhisperTranscriptionBackend
from app.transcription.none import NoneTranscriptionBackend

logger = logging.getLogger(__name__)


def create_transcription_backend(name: str, config: Config) -> TranscriptionBackend:
    if name == "apple_speech":
        return AppleSpeechTranscriptionBackend(config)
    if name == "mlx_whisper":
        return MlxWhisperTranscriptionBackend(config)
    if name == "none":
        return NoneTranscriptionBackend()
    raise ValueError(f"Unknown transcription backend: {name}")


class ChainedTranscriptionBackend(TranscriptionBackend):
    """Try each backend in order; the first success wins.

    Implements the auto-mode rule "Apple Speech, then mlx-whisper once" — each
    backend is attempted exactly once per audio file.
    """

    def __init__(self, backends: list[TranscriptionBackend]) -> None:
        if not backends:
            raise ValueError("ChainedTranscriptionBackend requires at least one backend")
        self._backends = backends
        self.name = backends[0].name
        self.fallback_occurred = False

    def is_available(self) -> bool:
        return any(b.is_available() for b in self._backends)

    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        last_error: Exception | None = None
        for index, backend in enumerate(self._backends):
            try:
                transcript = backend.transcribe(audio_path, options)
                self.fallback_occurred = index > 0
                if index > 0:
                    logger.info("transcription fell back to %s", backend.name)
                return transcript
            except TranscriptionFailedError as e:
                last_error = e
                logger.warning("transcription backend %s failed: %s", backend.name, e)
        raise TranscriptionFailedError(
            f"all transcription backends failed; last error: {last_error}"
        )
