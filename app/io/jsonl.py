"""JSON serialization for Transcript / MeetingMinutes intermediate files."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.models import (
    MeetingMinutes,
    Transcript,
    minutes_from_dict,
    minutes_to_dict,
    transcript_from_dict,
    transcript_to_dict,
)


def dump_transcript(transcript: Transcript) -> str:
    return json.dumps(transcript_to_dict(transcript), ensure_ascii=False, indent=2)


def dump_minutes(minutes: MeetingMinutes) -> str:
    return json.dumps(minutes_to_dict(minutes), ensure_ascii=False, indent=2)


def write_transcript_json(transcript: Transcript, path: Path) -> Path:
    path.write_text(dump_transcript(transcript), encoding="utf-8")
    return path


def write_minutes_json(minutes: MeetingMinutes, path: Path) -> Path:
    path.write_text(dump_minutes(minutes), encoding="utf-8")
    return path


def load_transcript_json(path: Path) -> Transcript:
    return transcript_from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_minutes_json(path: Path) -> MeetingMinutes:
    return minutes_from_dict(json.loads(path.read_text(encoding="utf-8")))
