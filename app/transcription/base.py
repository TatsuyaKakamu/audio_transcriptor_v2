from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.models import Transcript

# Reports transcription progress for a single file as a fraction in [0.0, 1.0].
# Backends call this as work proceeds; it is optional and best-effort (a backend
# that cannot report fine-grained progress simply never calls it).
ProgressCallback = Callable[[float], None]


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
    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> Transcript: ...
