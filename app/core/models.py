"""Backend-agnostic intermediate data models shared by every backend.

All backends (Apple Speech, mlx-whisper, Apple Foundation, Ollama, API) read and
write these same structures so the pipeline never has to special-case a backend.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class Transcript:
    source_audio_path: Path
    language: str
    backend: str
    segments: list[TranscriptSegment]
    raw_text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ActionItem:
    task: str
    owner: str | None = None
    due_date: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class MeetingMinutes:
    title: str
    date: str | None
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
    open_questions: list[str]
    risks: list[str]
    topics: list[str]
    backend: str
    metadata: dict = field(default_factory=dict)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def transcript_to_dict(transcript: Transcript) -> dict:
    return {
        "source_audio_path": str(transcript.source_audio_path),
        "language": transcript.language,
        "backend": transcript.backend,
        "segments": [
            {
                "start_seconds": seg.start_seconds,
                "end_seconds": seg.end_seconds,
                "speaker": seg.speaker,
                "confidence": seg.confidence,
                "text": seg.text,
            }
            for seg in transcript.segments
        ],
        "raw_text": transcript.raw_text,
        "metadata": dict(transcript.metadata),
    }


def transcript_from_dict(data: dict) -> Transcript:
    segments = [
        TranscriptSegment(
            start_seconds=float(seg.get("start_seconds", 0.0)),
            end_seconds=float(seg.get("end_seconds", 0.0)),
            text=str(seg.get("text", "")),
            speaker=seg.get("speaker"),
            confidence=seg.get("confidence"),
        )
        for seg in data.get("segments", [])
    ]
    metadata = data.get("metadata") or {}
    if "created_at" not in metadata:
        metadata = {**metadata, "created_at": _utc_now_iso()}
    return Transcript(
        source_audio_path=Path(str(data.get("source_audio_path", ""))),
        language=str(data.get("language", "")),
        backend=str(data.get("backend", "")),
        segments=segments,
        raw_text=str(data.get("raw_text", "")),
        metadata=metadata,
    )


def minutes_to_dict(minutes: MeetingMinutes) -> dict:
    data = asdict(minutes)
    return data


def minutes_from_dict(data: dict, *, backend: str | None = None) -> MeetingMinutes:
    action_items = [
        ActionItem(
            task=str(item.get("task", "")),
            owner=item.get("owner"),
            due_date=item.get("due_date"),
            evidence=item.get("evidence"),
        )
        for item in data.get("action_items", [])
        if isinstance(item, dict) and str(item.get("task", "")).strip()
    ]
    resolved_backend = backend if backend is not None else str(data.get("backend", ""))
    return MeetingMinutes(
        title=str(data.get("title", "")).strip() or "会議",
        date=data.get("date"),
        summary=str(data.get("summary", "")),
        decisions=[str(x) for x in data.get("decisions", []) if str(x).strip()],
        action_items=action_items,
        open_questions=[str(x) for x in data.get("open_questions", []) if str(x).strip()],
        risks=[str(x) for x in data.get("risks", []) if str(x).strip()],
        topics=[str(x) for x in data.get("topics", []) if str(x).strip()],
        backend=resolved_backend,
        metadata=data.get("metadata") or {},
    )
