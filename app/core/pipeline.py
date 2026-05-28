"""Backend selection, fallback ordering, and the end-to-end Pipeline."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Config
from app.core.capabilities import Capabilities, detect_capabilities
from app.core.errors import (
    BackendUnavailableError,
    NoTranscriptionBackendError,
)
from app.core.models import MeetingMinutes, Transcript
from app.summary.base import SummaryBackend, SummaryOptions
from app.transcription.base import TranscriptionBackend, TranscriptionOptions

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def validate_requested_transcription_backend(name: str, caps: Capabilities) -> str:
    if name == "apple_speech":
        if caps.apple_speech_available:
            return name
        raise BackendUnavailableError("apple_speech backend requested but helper unavailable")
    if name == "mlx_whisper":
        if caps.mlx_whisper_available and caps.ffmpeg_available:
            return name
        raise BackendUnavailableError(
            "mlx_whisper backend requested but mlx-whisper/ffmpeg unavailable"
        )
    raise ValueError(f"Unknown transcription backend: {name}")


def validate_requested_summary_backend(name: str, caps: Capabilities) -> str:
    if name == "apple_foundation":
        if caps.apple_foundation_available:
            return name
        raise BackendUnavailableError("apple_foundation backend requested but helper unavailable")
    if name == "ollama":
        if caps.ollama_available:
            return name
        raise BackendUnavailableError("ollama backend requested but Ollama unavailable")
    if name == "none":
        return name
    raise ValueError(f"Unknown summary backend: {name}")


def choose_transcription_backend(config: Config, caps: Capabilities) -> str:
    requested = config.advanced.transcription_backend
    if requested != "auto":
        return validate_requested_transcription_backend(requested, caps)
    if caps.apple_speech_available:
        return "apple_speech"
    if caps.mlx_whisper_available and caps.ffmpeg_available:
        return "mlx_whisper"
    raise NoTranscriptionBackendError("No usable transcription backend found.")


def choose_summary_backend(config: Config, caps: Capabilities) -> str:
    requested = config.advanced.summary_backend
    if requested != "auto":
        return validate_requested_summary_backend(requested, caps)
    if caps.apple_foundation_available:
        return "apple_foundation"
    if caps.ollama_available:
        return "ollama"
    return "none"


def transcription_backend_order(config: Config, caps: Capabilities) -> list[str]:
    """Ordered list of transcription backends to try (first = preferred)."""
    requested = config.advanced.transcription_backend
    if requested != "auto":
        return [validate_requested_transcription_backend(requested, caps)]

    mode = config.app.mode
    if mode == "apple_native":
        if caps.apple_speech_available:
            return ["apple_speech"]
        raise NoTranscriptionBackendError(
            "apple_native mode requires Apple Speech, which is unavailable"
        )

    mlx_ok = caps.mlx_whisper_available and caps.ffmpeg_available
    if mode == "legacy":
        order = (["mlx_whisper"] if mlx_ok else []) + (
            ["apple_speech"] if caps.apple_speech_available else []
        )
    else:  # auto
        order = (["apple_speech"] if caps.apple_speech_available else []) + (
            ["mlx_whisper"] if mlx_ok else []
        )
    if not order:
        raise NoTranscriptionBackendError("No usable transcription backend found.")
    return order


def summary_backend_order(config: Config, caps: Capabilities) -> list[str]:
    """Ordered list of summary backends to try; always ends with 'none'."""
    requested = config.advanced.summary_backend
    if requested != "auto":
        return [validate_requested_summary_backend(requested, caps)]

    mode = config.app.mode
    if mode == "apple_native":
        if caps.apple_foundation_available:
            return ["apple_foundation"]
        raise BackendUnavailableError(
            "apple_native mode requires Apple Foundation Models, which is unavailable"
        )

    order: list[str] = []
    if mode != "legacy" and caps.apple_foundation_available:
        order.append("apple_foundation")
    if caps.ollama_available:
        order.append("ollama")
    order.append("none")
    return order


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PipelineOptions:
    transcription: TranscriptionOptions = field(default_factory=TranscriptionOptions)
    summary: SummaryOptions = field(default_factory=SummaryOptions)


@dataclass(frozen=True)
class PipelineResult:
    transcript: Transcript
    minutes: MeetingMinutes | None
    transcript_json_path: Path | None = None
    transcript_md_path: Path | None = None
    minutes_json_path: Path | None = None
    minutes_md_path: Path | None = None
    transcription_backend: str = ""
    summary_backend: str = ""
    fallback_occurred: bool = False
    elapsed_seconds: float = 0.0


class Pipeline:
    def __init__(self, transcription_backend, summary_backend, writers, logger=logger) -> None:
        self.transcription_backend = transcription_backend
        self.summary_backend = summary_backend
        self.writers = writers
        self.logger = logger

    def run(self, audio_path: Path, options: PipelineOptions | None = None) -> PipelineResult:
        options = options or PipelineOptions()
        start = time.monotonic()

        transcript = self.transcription_backend.transcribe(audio_path, options.transcription)
        transcript_json_path = self.writers.write_transcript_json(transcript)
        transcript_md_path = self.writers.write_transcript_markdown(transcript)
        self.logger.info("Wrote transcript: %s", transcript_md_path)

        tx_fallback = getattr(self.transcription_backend, "fallback_occurred", False)

        if self.summary_backend.name == "none":
            return PipelineResult(
                transcript=transcript,
                minutes=None,
                transcript_json_path=transcript_json_path,
                transcript_md_path=transcript_md_path,
                transcription_backend=transcript.backend,
                summary_backend="none",
                fallback_occurred=tx_fallback,
                elapsed_seconds=time.monotonic() - start,
            )

        minutes = self.summary_backend.summarize(transcript, options.summary)
        sm_fallback = getattr(self.summary_backend, "fallback_occurred", False)

        if minutes is None:
            return PipelineResult(
                transcript=transcript,
                minutes=None,
                transcript_json_path=transcript_json_path,
                transcript_md_path=transcript_md_path,
                transcription_backend=transcript.backend,
                summary_backend="none",
                fallback_occurred=tx_fallback or sm_fallback,
                elapsed_seconds=time.monotonic() - start,
            )

        minutes_json_path = self.writers.write_minutes_json(minutes)
        minutes_md_path = self.writers.write_minutes_markdown(minutes, transcript_md_path)
        self.logger.info("Wrote minutes: %s", minutes_md_path)

        return PipelineResult(
            transcript=transcript,
            minutes=minutes,
            transcript_json_path=transcript_json_path,
            transcript_md_path=transcript_md_path,
            minutes_json_path=minutes_json_path,
            minutes_md_path=minutes_md_path,
            transcription_backend=transcript.backend,
            summary_backend=minutes.backend,
            fallback_occurred=tx_fallback or sm_fallback,
            elapsed_seconds=time.monotonic() - start,
        )


# --------------------------------------------------------------------------- #
# Build / describe
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SelectionInfo:
    transcription_backend: str
    summary_backend: str
    transcription_order: list[str]
    summary_order: list[str]
    capabilities: Capabilities


def build_pipeline(
    config: Config,
    caps: Capabilities | None = None,
    *,
    pipeline_logger=logger,
) -> tuple[Pipeline, SelectionInfo]:
    from app.io.files import Writers
    from app.summary.factory import ChainedSummaryBackend, create_summary_backend
    from app.transcription.factory import (
        ChainedTranscriptionBackend,
        create_transcription_backend,
    )

    caps = caps or detect_capabilities(config)

    tx_order = transcription_backend_order(config, caps)
    tx_backends: list[TranscriptionBackend] = [
        create_transcription_backend(name, config) for name in tx_order
    ]
    tx_backend = tx_backends[0] if len(tx_backends) == 1 else ChainedTranscriptionBackend(tx_backends)

    sm_order = summary_backend_order(config, caps)
    sm_backends: list[SummaryBackend] = [
        create_summary_backend(name, config) for name in sm_order
    ]
    summary_backend = (
        sm_backends[0] if len(sm_backends) == 1 else ChainedSummaryBackend(sm_backends)
    )

    writers = Writers(config.app.output_directory)
    pipeline = Pipeline(tx_backend, summary_backend, writers, pipeline_logger)

    real_summary = next((n for n in sm_order if n != "none"), "none")
    selection = SelectionInfo(
        transcription_backend=tx_order[0],
        summary_backend=real_summary,
        transcription_order=tx_order,
        summary_order=sm_order,
        capabilities=caps,
    )
    pipeline_logger.info("Selected transcription backend: %s", selection.transcription_backend)
    pipeline_logger.info("Selected summary backend: %s", selection.summary_backend)
    return pipeline, selection


_DISPLAY_NAMES = {
    "apple_speech": "Apple SpeechAnalyzer",
    "mlx_whisper": "mlx-whisper",
    "apple_foundation": "Apple Foundation Models",
    "ollama": "Ollama",
    "none": "None (transcript only)",
}


def describe_selection(config: Config, selection: SelectionInfo) -> str:
    caps = selection.capabilities
    mode_label = {"auto": "Auto", "apple_native": "Apple Native", "legacy": "Legacy"}.get(
        config.app.mode, config.app.mode
    )
    fallbacks = []
    fallbacks.append(
        "mlx-whisper available" if caps.mlx_whisper_available else "mlx-whisper unavailable"
    )
    fallbacks.append("Ollama available" if caps.ollama_available else "Ollama unavailable")
    return (
        f"Processing mode: {mode_label}\n"
        f"Transcription: {_DISPLAY_NAMES.get(selection.transcription_backend, selection.transcription_backend)}\n"
        f"Summary: {_DISPLAY_NAMES.get(selection.summary_backend, selection.summary_backend)}\n"
        f"Fallbacks: {', '.join(fallbacks)}"
    )
