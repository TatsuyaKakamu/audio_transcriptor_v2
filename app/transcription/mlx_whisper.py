"""Transcription via the existing mlx-whisper + VAD pipeline."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from app.config import Config
from app.core.errors import TranscriptionFailedError
from app.core.models import Transcript, TranscriptSegment
from app.transcription.base import ProgressCallback, TranscriptionBackend, TranscriptionOptions


class MlxWhisperTranscriptionBackend(TranscriptionBackend):
    name = "mlx_whisper"

    def __init__(self, config: Config) -> None:
        self._config = config

    def is_available(self) -> bool:
        return (
            importlib.util.find_spec("mlx_whisper") is not None
            and shutil.which("ffmpeg") is not None
        )

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> Transcript:
        # Imported lazily: mlx_whisper is a heavy, Apple-Silicon-only dependency.
        from app.services import transcriber

        model = options.model or self._config.transcription.model

        # The legacy transcriber reports (processed, total, elapsed) segment counts
        # via its tqdm hook; adapt that to the pipeline's [0.0, 1.0] fraction.
        legacy_callback = None
        if progress_callback is not None:

            def legacy_callback(processed: int, total: int, _elapsed: float) -> None:
                if total > 0:
                    progress_callback(max(0.0, min(1.0, processed / total)))

        try:
            result = transcriber.transcribe(
                audio_path,
                model=model,
                language=options.language,
                progress_callback=legacy_callback,
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
