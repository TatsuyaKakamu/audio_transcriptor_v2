from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AdvancedSection, AppSection, Config
from app.core.capabilities import Capabilities
from app.core.pipeline import build_pipeline, describe_selection
from app.models.types import Segment, TranscriptionResult
from app.summary import ollama as ollama_mod

_MINUTES_PAYLOAD = {
    "title": "予算会議",
    "date": "2026-05-28",
    "summary": "議論した。",
    "decisions": [],
    "action_items": [],
    "open_questions": [],
    "risks": [],
    "topics": [],
}

_TRANSCRIPT_PAYLOAD = {
    "source_audio_path": "/tmp/meeting.wav",
    "language": "ja-JP",
    "backend": "apple_speech",
    "segments": [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "おはよう。"}],
    "raw_text": "おはよう。",
    "metadata": {},
}


def _caps(**overrides) -> Capabilities:
    base = dict(
        macos_version="26.0",
        apple_silicon=True,
        apple_speech_available=False,
        apple_foundation_available=False,
        mlx_whisper_available=False,
        ollama_available=False,
        ffmpeg_available=False,
    )
    base.update(overrides)
    return Capabilities(**base)


def _config(tmp_path: Path, **advanced) -> Config:
    return Config(
        app=AppSection(mode="auto", output_directory=str(tmp_path)),
        advanced=AdvancedSection(**advanced),
    )


def test_pipeline_transcript_only_when_no_summary(tmp_path, monkeypatch) -> None:
    from app.services import transcriber

    monkeypatch.setattr(
        transcriber,
        "transcribe",
        lambda source_path, model, language, use_vad=True, **k: TranscriptionResult(
            source_path=source_path,
            language=language,
            model=model,
            segments=[Segment(0.0, 2.0, "テスト。")],
        ),
    )
    caps = _caps(mlx_whisper_available=True, ffmpeg_available=True)
    pipeline, selection = build_pipeline(_config(tmp_path), caps)
    assert selection.summary_backend == "none"

    result = pipeline.run(tmp_path / "meeting.wav")
    assert result.minutes is None
    assert result.summary_backend == "none"
    assert result.transcript_md_path.exists()
    assert result.transcript_json_path.exists()
    assert result.minutes_md_path is None


def test_pipeline_apple_success(tmp_path, make_fake_helper) -> None:
    transcribe_helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True, "version": "0.1.0"},
        main={"ok": True, "transcript": _TRANSCRIPT_PAYLOAD},
    )
    summarize_helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True, "version": "0.1.0"},
        main={"ok": True, "minutes": {**_MINUTES_PAYLOAD, "backend": "apple_foundation"}},
    )
    caps = _caps(apple_speech_available=True, apple_foundation_available=True)
    cfg = _config(
        tmp_path,
        apple_transcribe_path=str(transcribe_helper),
        apple_summarize_path=str(summarize_helper),
    )
    pipeline, selection = build_pipeline(cfg, caps)
    assert selection.transcription_backend == "apple_speech"
    assert selection.summary_backend == "apple_foundation"

    result = pipeline.run(tmp_path / "meeting.wav")
    assert result.transcription_backend == "apple_speech"
    assert result.minutes is not None
    assert result.summary_backend == "apple_foundation"
    assert result.minutes_md_path.exists()
    assert result.minutes_json_path.exists()
    assert not result.fallback_occurred


def test_pipeline_summary_falls_back_to_ollama(tmp_path, make_fake_helper, monkeypatch) -> None:
    transcribe_helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True},
        main={"ok": True, "transcript": _TRANSCRIPT_PAYLOAD},
    )
    summarize_helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True},
        main={"ok": False, "error": {"code": "MODEL_UNAVAILABLE", "message": "down"}},
    )
    monkeypatch.setattr(
        ollama_mod,
        "_http_post_json",
        lambda url, payload, timeout: {"response": json.dumps({**_MINUTES_PAYLOAD})},
    )
    caps = _caps(
        apple_speech_available=True, apple_foundation_available=True, ollama_available=True
    )
    cfg = _config(
        tmp_path,
        apple_transcribe_path=str(transcribe_helper),
        apple_summarize_path=str(summarize_helper),
    )
    pipeline, selection = build_pipeline(cfg, caps)
    assert selection.summary_order == ["apple_foundation", "ollama", "none"]

    result = pipeline.run(tmp_path / "meeting.wav")
    assert result.minutes is not None
    assert result.summary_backend == "ollama"
    assert result.fallback_occurred


def test_pipeline_transcription_falls_back_to_mlx(tmp_path, make_fake_helper, monkeypatch) -> None:
    from app.services import transcriber

    transcribe_helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True},
        main={"ok": False, "error": {"code": "UNAVAILABLE", "message": "no"}},
    )
    monkeypatch.setattr(
        transcriber,
        "transcribe",
        lambda source_path, model, language, use_vad=True, **k: TranscriptionResult(
            source_path=source_path,
            language=language,
            model=model,
            segments=[Segment(0.0, 2.0, "代替。")],
        ),
    )
    caps = _caps(
        apple_speech_available=True, mlx_whisper_available=True, ffmpeg_available=True
    )
    cfg = _config(tmp_path, apple_transcribe_path=str(transcribe_helper))
    pipeline, selection = build_pipeline(cfg, caps)
    assert selection.transcription_order == ["apple_speech", "mlx_whisper"]

    result = pipeline.run(tmp_path / "meeting.wav")
    assert result.transcription_backend == "mlx_whisper"
    assert result.fallback_occurred


def test_describe_selection_renders(tmp_path) -> None:
    caps = _caps(apple_speech_available=True, apple_foundation_available=True)
    cfg = _config(tmp_path)
    _, selection = build_pipeline(
        cfg,
        caps,
    )
    text = describe_selection(cfg, selection)
    assert "Processing mode: Auto" in text
    assert "Transcription: Apple SpeechAnalyzer" in text
    assert "Summary: Apple Foundation Models" in text
