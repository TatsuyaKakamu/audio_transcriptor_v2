from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.models import Transcript


@dataclass(frozen=True)
class TranscriptionOptions:
    language: str = "ja-JP"
    model: str | None = None
    vad_enabled: bool = True
    timestamps: bool = True
    timeout_seconds: float | None = None


class TranscriptionBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript: ...
