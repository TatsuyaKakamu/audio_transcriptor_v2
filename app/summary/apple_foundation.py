"""Meeting-minutes generation via the Apple Foundation Models Swift helper."""

from __future__ import annotations

from app.config import Config
from app.core.errors import HelperProtocolError, SummaryFailedError
from app.core.helper import run_helper_check, run_json_helper
from app.core.models import (
    MeetingMinutes,
    Transcript,
    minutes_from_dict,
    transcript_to_dict,
)
from app.summary.base import SummaryBackend, SummaryOptions

_HELPER = "apple-summarize"


class AppleFoundationSummaryBackend(SummaryBackend):
    name = "apple_foundation"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._explicit_path = config.advanced.apple_summarize_path or None

    def is_available(self) -> bool:
        return run_helper_check(_HELPER, self._explicit_path)

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes:
        payload = transcript_to_dict(transcript)
        try:
            envelope = run_json_helper(
                name=_HELPER,
                input_json=payload,
                args=["--stdin", "--language", options.language],
                timeout=options.timeout_seconds,
                explicit_path=self._explicit_path,
            )
        except HelperProtocolError as e:
            raise SummaryFailedError(f"apple_foundation summarization failed: {e}") from e

        minutes = envelope.get("minutes")
        if not isinstance(minutes, dict):
            raise SummaryFailedError("apple_foundation response missing 'minutes' object")
        return minutes_from_dict(minutes, backend=self.name)
