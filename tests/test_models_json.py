from __future__ import annotations

from pathlib import Path

from app.core.models import (
    ActionItem,
    MeetingMinutes,
    Transcript,
    TranscriptSegment,
    minutes_from_dict,
    minutes_to_dict,
    transcript_from_dict,
    transcript_to_dict,
)


def test_transcript_round_trip() -> None:
    transcript = Transcript(
        source_audio_path=Path("/path/to/meeting.mp3"),
        language="ja-JP",
        backend="apple_speech",
        segments=[TranscriptSegment(3.2, 8.0, "おはようございます。", speaker=None, confidence=None)],
        raw_text="おはようございます。",
        metadata={"created_at": "2026-05-28T12:00:00Z"},
    )
    data = transcript_to_dict(transcript)
    assert data["source_audio_path"] == "/path/to/meeting.mp3"
    assert data["segments"][0]["start_seconds"] == 3.2

    restored = transcript_from_dict(data)
    assert restored == transcript


def test_transcript_from_dict_adds_created_at() -> None:
    restored = transcript_from_dict(
        {
            "source_audio_path": "/x.wav",
            "language": "ja-JP",
            "backend": "apple_speech",
            "segments": [],
            "raw_text": "",
            "metadata": {},
        }
    )
    assert "created_at" in restored.metadata


def test_minutes_round_trip() -> None:
    minutes = MeetingMinutes(
        title="予算会議",
        date="2026-05-28",
        summary="議論した。",
        decisions=["集約する。"],
        action_items=[ActionItem(task="集約", owner="田中", due_date="2026-06-03", evidence="お願い")],
        open_questions=["未確定。"],
        risks=[],
        topics=["予算"],
        backend="apple_foundation",
        metadata={},
    )
    data = minutes_to_dict(minutes)
    restored = minutes_from_dict(data)
    assert restored == minutes


def test_minutes_from_dict_drops_empty_action_items() -> None:
    minutes = minutes_from_dict(
        {
            "title": "x",
            "summary": "s",
            "action_items": [{"task": ""}, {"task": "real"}],
        },
        backend="ollama",
    )
    assert len(minutes.action_items) == 1
    assert minutes.action_items[0].task == "real"
    assert minutes.backend == "ollama"


def test_minutes_from_dict_defaults_title() -> None:
    minutes = minutes_from_dict({"summary": "s"}, backend="none")
    assert minutes.title == "会議"
