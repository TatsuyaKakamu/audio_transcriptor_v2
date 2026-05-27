from pathlib import Path

from app.models.types import Segment, TranscriptionResult
from app.services.markdown_writer import build_markdown, format_time, write


def test_format_time_seconds() -> None:
    assert format_time(12.345) == "00:12.345"


def test_format_time_minutes() -> None:
    assert format_time(62.5) == "01:02.500"


def test_format_time_hours() -> None:
    assert format_time(3723.456) == "01:02:03.456"


def test_format_time_zero() -> None:
    assert format_time(0.0) == "00:00.000"


def _make_result(**kwargs) -> TranscriptionResult:
    defaults = dict(
        source_path=Path("/tmp/test.wav"),
        language="ja",
        model="medium",
        segments=[],
    )
    defaults.update(kwargs)
    return TranscriptionResult(**defaults)


def test_build_markdown_frontmatter() -> None:
    md = build_markdown(_make_result())
    assert "language: ja" in md
    assert "model: medium" in md
    assert md.startswith("---\n")


def test_build_markdown_segments() -> None:
    result = _make_result(segments=[
        Segment(start_sec=0.0, end_sec=3.2, text="おはようございます。"),
        Segment(start_sec=3.2, end_sec=8.0, text="それでは会議を始めます。"),
    ])
    md = build_markdown(result)
    assert "- [00:00.000 - 00:03.200] おはようございます。" in md
    assert "- [00:03.200 - 00:08.000] それでは会議を始めます。" in md


def test_build_markdown_empty_segments() -> None:
    md = build_markdown(_make_result(segments=[]))
    assert "## Transcript" in md


def test_write(tmp_path: Path) -> None:
    result = _make_result(
        source_path=tmp_path / "test.wav",
        segments=[Segment(start_sec=0.0, end_sec=1.0, text="テスト")],
    )
    output = tmp_path / "test.transcript.md"
    write(result, output)
    content = output.read_text(encoding="utf-8")
    assert "テスト" in content
    assert content.endswith("\n")
