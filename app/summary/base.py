from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.models import MeetingMinutes, Transcript


@dataclass(frozen=True)
class SummaryOptions:
    language: str = "ja"
    output_style: str = "meeting_minutes"
    max_input_chars: int = 30000
    include_evidence: bool = True
    timeout_seconds: float = 600.0


class SummaryBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes | None:
        ...
