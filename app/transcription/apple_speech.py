"""Transcription via the Apple SpeechAnalyzer Swift helper (`apple-transcribe`)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.config import Config
from app.core.errors import HelperProtocolError, TranscriptionFailedError
from app.core.helper import run_helper_check, run_json_helper
from app.core.models import Transcript, transcript_from_dict
from app.core.segments import merge_segments_by_sentence
from app.transcription.base import ProgressCallback, TranscriptionBackend, TranscriptionOptions

_HELPER = "apple-transcribe"


class AppleSpeechTranscriptionBackend(TranscriptionBackend):
    name = "apple_speech"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._explicit_path = config.advanced.apple_transcribe_path or None

    def is_available(self) -> bool:
        return run_helper_check(_HELPER, self._explicit_path)

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> Transcript:
        helper_progress = None
        if progress_callback is not None:
            # The helper streams {"progress": {"fraction": f, ...}} notices as
            # the SpeechTranscriber yields timed results; forward the fraction.
            def helper_progress(progress: dict) -> None:
                fraction = progress.get("fraction")
                if fraction is not None:
                    progress_callback(max(0.0, min(1.0, float(fraction))))

        try:
            envelope = run_json_helper(
                name=_HELPER,
                args=[
                    "--input",
                    str(audio_path),
                    "--language",
                    options.language,
                ],
                timeout=options.timeout_seconds,
                explicit_path=self._explicit_path,
                progress_callback=helper_progress,
            )
        except HelperProtocolError as e:
            raise TranscriptionFailedError(f"apple_speech transcription failed: {e}") from e

        payload = envelope.get("transcript")
        if not isinstance(payload, dict):
            raise TranscriptionFailedError("apple_speech response missing 'transcript' object")
        transcript = transcript_from_dict(payload)
        if not transcript.backend:
            transcript = transcript_from_dict({**payload, "backend": self.name})
        # SpeechTranscriber finalizes results mid-sentence; re-merge the raw
        # fragments into sentence-aligned blocks so the transcript breaks at
        # punctuation rather than at arbitrary recognizer boundaries.
        merged = merge_segments_by_sentence(transcript.segments, language=options.language)
        return replace(transcript, segments=merged)
