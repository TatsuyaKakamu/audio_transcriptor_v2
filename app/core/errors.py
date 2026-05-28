"""Error taxonomy for the backend-abstraction pipeline."""

from __future__ import annotations


class BackendUnavailableError(RuntimeError):
    """A backend was explicitly requested but its requirements are not met."""


class NoTranscriptionBackendError(RuntimeError):
    """No usable transcription backend could be selected for this environment."""


class TranscriptionFailedError(RuntimeError):
    """Transcription was attempted but failed (after any fallbacks)."""


class SummaryFailedError(RuntimeError):
    """Summarization was attempted but failed (after any fallbacks)."""


class HelperProtocolError(RuntimeError):
    """A Swift helper returned malformed output or signalled an error."""
