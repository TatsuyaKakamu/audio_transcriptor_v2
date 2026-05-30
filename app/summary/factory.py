"""Construct summary backends, including auto-mode fallback chains."""

from __future__ import annotations

import logging

from app.config import Config
from app.core.errors import SummaryFailedError
from app.core.models import MeetingMinutes, Transcript
from app.summary.apple_foundation import AppleFoundationSummaryBackend
from app.summary.base import SummaryBackend, SummaryOptions
from app.summary.none import NoneSummaryBackend
from app.summary.ollama import OllamaSummaryBackend

logger = logging.getLogger(__name__)


def create_summary_backend(name: str, config: Config) -> SummaryBackend:
    if name == "apple_foundation":
        return AppleFoundationSummaryBackend(config)
    if name == "ollama":
        return OllamaSummaryBackend(config)
    if name == "none":
        return NoneSummaryBackend()
    raise ValueError(f"Unknown summary backend: {name}")


class ChainedSummaryBackend(SummaryBackend):
    """Try each summary backend in order; degrade to a transcript-only result.

    When every real backend fails, `summarize` returns None — the pipeline then
    writes the transcript only, matching the "fall back to none" rule for auto
    mode. `name` reports "none" only when no real backend exists at all.
    """

    def __init__(self, backends: list[SummaryBackend]) -> None:
        self._backends = backends
        real = [b for b in backends if b.name != "none"]
        self.name = real[0].name if real else "none"
        self.fallback_occurred = False
        # Reasons every real backend failed, in attempt order ("name: message").
        # The pipeline surfaces these so a swallowed failure (e.g. Apple's 4096
        # token context exceeded) is visible in the UI/CLI, not just the console.
        self.failure_reasons: list[str] = []

    def is_available(self) -> bool:
        return True

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes | None:
        self.failure_reasons = []
        attempted = 0
        for backend in self._backends:
            if backend.name == "none":
                continue
            try:
                minutes = backend.summarize(transcript, options)
                self.fallback_occurred = attempted > 0
                if attempted > 0:
                    logger.info("summary fell back to %s", backend.name)
                return minutes
            except SummaryFailedError as e:
                attempted += 1
                self.failure_reasons.append(f"{backend.name}: {e}")
                logger.warning("summary backend %s failed: %s", backend.name, e)
        if self.failure_reasons:
            logger.warning("all summary backends failed; producing transcript only")
            self.fallback_occurred = True
        return None
