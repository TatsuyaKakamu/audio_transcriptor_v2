from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AdvancedSection, ApiSummaryConfig, Config, SummarySection
from app.core.errors import SummaryFailedError
from app.core.models import MeetingMinutes, Transcript, TranscriptSegment
from app.summary import api as api_mod
from app.summary import ollama as ollama_mod
from app.summary.api import ApiSummaryBackend
from app.summary.apple_foundation import AppleFoundationSummaryBackend
from app.summary.base import SummaryOptions
from app.summary.none import NoneSummaryBackend
from app.summary.ollama import OllamaSummaryBackend

_MINUTES_PAYLOAD = {
    "title": "予算会議",
    "date": "2026-05-28",
    "summary": "予算配分を議論した。",
    "decisions": ["見積もりを集約する。"],
    "action_items": [
        {"task": "集約する", "owner": "田中", "due_date": "2026-06-03", "evidence": "お願いします"}
    ],
    "open_questions": ["承認フローは未確定。"],
    "risks": [],
    "topics": ["予算"],
}


def _transcript() -> Transcript:
    return Transcript(
        source_audio_path=Path("/tmp/meeting.wav"),
        language="ja-JP",
        backend="apple_speech",
        segments=[TranscriptSegment(0.0, 3.0, "おはようございます。")],
        raw_text="おはようございます。",
        metadata={},
    )


def _options() -> SummaryOptions:
    return SummaryOptions(timeout_seconds=5.0)


def test_ollama_backend_returns_minutes(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_mod,
        "_http_post_json",
        lambda url, payload, timeout: {"response": json.dumps(_MINUTES_PAYLOAD)},
    )
    minutes = OllamaSummaryBackend(Config()).summarize(_transcript(), _options())
    assert isinstance(minutes, MeetingMinutes)
    assert minutes.title == "予算会議"
    assert minutes.backend == "ollama"
    assert minutes.action_items[0].owner == "田中"


def test_ollama_backend_failure_raises(monkeypatch) -> None:
    def boom(*a, **k):
        import urllib.error

        raise urllib.error.URLError("refused")

    monkeypatch.setattr(ollama_mod, "_http_post_json", boom)
    with pytest.raises(SummaryFailedError):
        OllamaSummaryBackend(Config()).summarize(_transcript(), _options())


def test_api_backend_returns_minutes(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        api_mod,
        "_http_post_json",
        lambda url, payload, headers, timeout: {
            "choices": [{"message": {"content": json.dumps(_MINUTES_PAYLOAD)}}]
        },
    )
    minutes = ApiSummaryBackend(Config()).summarize(_transcript(), _options())
    assert isinstance(minutes, MeetingMinutes)
    assert minutes.backend == "api"


def test_api_backend_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = ApiSummaryBackend(Config())
    assert backend.is_available() is False
    with pytest.raises(SummaryFailedError):
        backend.summarize(_transcript(), _options())


def test_apple_foundation_backend_returns_minutes(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True, "backend": "apple_foundation", "version": "0.1.0"},
        main={"ok": True, "minutes": {**_MINUTES_PAYLOAD, "backend": "apple_foundation"}},
    )
    cfg = Config(advanced=AdvancedSection(apple_summarize_path=str(helper)))
    backend = AppleFoundationSummaryBackend(cfg)
    assert backend.is_available() is True
    minutes = backend.summarize(_transcript(), _options())
    assert isinstance(minutes, MeetingMinutes)
    assert minutes.backend == "apple_foundation"


def test_apple_foundation_backend_helper_error_raises(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True, "backend": "apple_foundation", "version": "0.1.0"},
        main={"ok": False, "error": {"code": "MODEL_UNAVAILABLE", "message": "nope"}},
    )
    cfg = Config(advanced=AdvancedSection(apple_summarize_path=str(helper)))
    with pytest.raises(SummaryFailedError):
        AppleFoundationSummaryBackend(cfg).summarize(_transcript(), _options())


def test_none_backend_returns_none() -> None:
    backend = NoneSummaryBackend()
    assert backend.name == "none"
    assert backend.is_available() is True
    assert backend.summarize(_transcript(), _options()) is None
