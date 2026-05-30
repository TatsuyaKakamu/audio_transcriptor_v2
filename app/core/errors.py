"""Error taxonomy for the backend-abstraction pipeline."""

from __future__ import annotations


class PipelineError(RuntimeError):
    """Base class for all backend-abstraction pipeline errors."""


class BackendUnavailableError(PipelineError):
    """A backend was explicitly requested but its requirements are not met."""


class NoTranscriptionBackendError(PipelineError):
    """No usable transcription backend could be selected for this environment."""


class TranscriptionFailedError(PipelineError):
    """Transcription was attempted but failed (after any fallbacks)."""


class SummaryFailedError(PipelineError):
    """Summarization was attempted but failed (after any fallbacks)."""


class HelperProtocolError(PipelineError):
    """A Swift helper returned malformed output or signalled an error."""
