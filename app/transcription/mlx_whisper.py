"""Transcription via the existing mlx-whisper + VAD pipeline."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from app.config import Config
from app.core.errors import TranscriptionFailedError
from app.core.models import Transcript, TranscriptSegment
from app.transcription.base import TranscriptionBackend, TranscriptionOptions


class MlxWhisperTranscriptionBackend(TranscriptionBackend):
    name = "mlx_whisper"

    def __init__(self, config: Config) -> None:
        self._config = config

    def is_available(self) -> bool:
        return (
            importlib.util.find_spec("mlx_whisper") is not None
            and shutil.which("ffmpeg") is not None
        )

    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        # Imported lazily: mlx_whisper is a heavy, Apple-Silicon-only dependency.
        from app.services import transcriber

        model = options.model or self._config.transcription.model
        try:
            result = transcriber.transcribe(
                audio_path,
                model=model,
                language=options.language,
                use_vad=options.vad_enabled,
            )
        except Exception as e:  # noqa: BLE001 — surface as a typed pipeline error
            raise TranscriptionFailedError(f"mlx_whisper transcription failed: {e}") from e

        segments = [
            TranscriptSegment(
                start_seconds=seg.start_sec,
                end_seconds=seg.end_sec,
                text=seg.text,
            )
            for seg in result.segments
        ]
        raw_text = "\n".join(seg.text for seg in segments if seg.text)
        return Transcript(
            source_audio_path=audio_path,
            language=options.language,
            backend=self.name,
            segments=segments,
            raw_text=raw_text,
            metadata={"model": model},
        )
