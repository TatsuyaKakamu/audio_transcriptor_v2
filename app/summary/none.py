"""No-op summary backend: produce a transcript only, no minutes."""

from __future__ import annotations

from app.core.models import MeetingMinutes, Transcript
from app.summary.base import SummaryBackend, SummaryOptions


class NoneSummaryBackend(SummaryBackend):
    name = "none"

    def is_available(self) -> bool:
        return True

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes | None:
        return None
