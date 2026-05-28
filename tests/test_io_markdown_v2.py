from __future__ import annotations

from pathlib import Path

from app.core.models import ActionItem, MeetingMinutes, Transcript, TranscriptSegment
from app.io.files import Writers
from app.io.markdown import build_minutes_markdown, build_transcript_markdown, format_time


def _transcript(tmp_path: Path) -> Transcript:
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"\x00")
    return Transcript(
        source_audio_path=audio,
        language="ja-JP",
        backend="apple_speech",
        segments=[
            TranscriptSegment(3.2, 8.0, "おはようございます。"),
            TranscriptSegment(8.0, 12.0, "予算の話です。"),
        ],
        raw_text="おはようございます。\n予算の話です。",
        metadata={"created_at": "2026-05-28T12:00:00Z"},
    )


def _minutes() -> MeetingMinutes:
    return MeetingMinutes(
        title="予算会議",
        date="2026-05-28",
        summary="予算配分を議論した。",
        decisions=["見積もりを集約する。"],
        action_items=[ActionItem(task="集約する", owner="田中", due_date="2026-06-03")],
        open_questions=["承認フローは未確定。"],
        risks=[],
        topics=["予算"],
        backend="apple_foundation",
        metadata={},
    )


def test_format_time() -> None:
    assert format_time(3.2) == "00:03.200"
    assert format_time(8.0) == "00:08.000"
    assert format_time(3661.5) == "01:01:01.500"


def test_transcript_markdown_has_frontmatter_and_segments(tmp_path) -> None:
    md = build_transcript_markdown(_transcript(tmp_path))
    assert "source_audio: meeting.wav" in md
    assert "transcription_backend: apple_speech" in md
    assert "created_at: 2026-05-28T12:00:00Z" in md
    assert "# Transcript" in md
    assert "- [00:03.200 - 00:08.000] おはようございます。" in md


def test_minutes_markdown_schema(tmp_path) -> None:
    md = build_minutes_markdown(_minutes(), _transcript(tmp_path), "meeting.transcript.md")
    assert "title: 予算会議" in md
    assert "summary_backend: apple_foundation" in md
    assert "## 概要" in md
    assert "## 決定事項" in md
    assert "## アクションアイテム" in md
    assert "| 担当 | タスク | 期限 |" in md
    assert "| 田中 | 集約する | 2026-06-03 |" in md
    assert "## リスク" in md
    assert "- なし" in md  # empty risks renders as なし
    assert "原文書き起こし: [meeting.transcript.md](meeting.transcript.md)" in md


def test_writers_emit_markdown_only(tmp_path) -> None:
    writers = Writers()
    transcript = _transcript(tmp_path)
    tm = writers.write_transcript_markdown(transcript)
    mm = writers.write_minutes_markdown(_minutes(), tm)

    assert tm.name == "meeting.transcript.md"
    assert mm.name == "meeting.minutes.md"
    for p in (tm, mm):
        assert p.exists() and p.read_text(encoding="utf-8")
    # No JSON side-car files are produced.
    assert not list(tmp_path.glob("*.json"))
