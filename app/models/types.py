from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class TranscriptionResult:
    source_path: Path
    language: str
    model: str
    segments: list[Segment]
