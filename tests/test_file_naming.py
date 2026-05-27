from pathlib import Path

import pytest

from app.services.file_naming import resolve_output_path


def test_no_conflict(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.touch()
    assert resolve_output_path(source) == tmp_path / "meeting.transcript.md"


def test_conflict_first(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.touch()
    (tmp_path / "meeting.transcript.md").touch()
    assert resolve_output_path(source) == tmp_path / "meeting.transcript.1.md"


def test_conflict_multiple(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.touch()
    (tmp_path / "meeting.transcript.md").touch()
    (tmp_path / "meeting.transcript.1.md").touch()
    assert resolve_output_path(source) == tmp_path / "meeting.transcript.2.md"


def test_uses_minimum_unused(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.touch()
    (tmp_path / "meeting.transcript.md").touch()
    (tmp_path / "meeting.transcript.2.md").touch()
    assert resolve_output_path(source) == tmp_path / "meeting.transcript.1.md"
