from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AdvancedSection, Config
from app.core.errors import TranscriptionFailedError
from app.core.models import Transcript
from app.models.types import Segment, TranscriptionResult
from app.transcription.apple_speech import AppleSpeechTranscriptionBackend
from app.transcription.base import TranscriptionOptions
from app.transcription.mlx_whisper import MlxWhisperTranscriptionBackend

_TRANSCRIPT_PAYLOAD = {
    "source_audio_path": "/tmp/meeting.wav",
    "language": "ja-JP",
    "backend": "apple_speech",
    "segments": [
        {"start_seconds": 0.0, "end_seconds": 5.2, "text": "おはようございます。"},
        {"start_seconds": 5.2, "end_seconds": 8.0, "text": "本日の議題は予算です。"},
    ],
    "raw_text": "おはようございます。\n本日の議題は予算です。",
    "metadata": {},
}


def _options() -> TranscriptionOptions:
    return TranscriptionOptions(language="ja-JP", timeout_seconds=5.0)


def test_apple_speech_backend_returns_transcript(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True, "backend": "apple_speech", "version": "0.1.0"},
        main={"ok": True, "transcript": _TRANSCRIPT_PAYLOAD},
    )
    cfg = Config(advanced=AdvancedSection(apple_transcribe_path=str(helper)))
    backend = AppleSpeechTranscriptionBackend(cfg)
    assert backend.is_available() is True
    transcript = backend.transcribe(Path("/tmp/meeting.wav"), _options())
    assert isinstance(transcript, Transcript)
    assert transcript.backend == "apple_speech"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "おはようございます。"


def test_apple_speech_backend_helper_error_raises(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True, "backend": "apple_speech", "version": "0.1.0"},
        main={"ok": False, "error": {"code": "UNAVAILABLE", "message": "no"}},
    )
    cfg = Config(advanced=AdvancedSection(apple_transcribe_path=str(helper)))
    with pytest.raises(TranscriptionFailedError):
        AppleSpeechTranscriptionBackend(cfg).transcribe(Path("/tmp/meeting.wav"), _options())


def test_mlx_whisper_backend_returns_transcript(monkeypatch) -> None:
    from app.services import transcriber

    def fake_transcribe(source_path, model, language, use_vad=True, **kwargs):
        return TranscriptionResult(
            source_path=source_path,
            language=language,
            model=model,
            segments=[
                Segment(0.0, 2.0, "おはようございます。"),
                Segment(2.0, 4.0, "予算の話です。"),
            ],
        )

    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)
    backend = MlxWhisperTranscriptionBackend(Config())
    transcript = backend.transcribe(Path("/tmp/meeting.wav"), _options())
    assert isinstance(transcript, Transcript)
    assert transcript.backend == "mlx_whisper"
    assert transcript.segments[0].start_seconds == 0.0
    assert "おはようございます。" in transcript.raw_text
    assert transcript.metadata["model"] == "medium"


def test_mlx_whisper_backend_failure_raises(monkeypatch) -> None:
    from app.services import transcriber

    def boom(*a, **k):
        raise RuntimeError("mlx exploded")

    monkeypatch.setattr(transcriber, "transcribe", boom)
    with pytest.raises(TranscriptionFailedError):
        MlxWhisperTranscriptionBackend(Config()).transcribe(Path("/x.wav"), _options())


def test_mlx_whisper_backend_forwards_progress_as_fraction(monkeypatch) -> None:
    from app.services import transcriber

    def fake_transcribe(source_path, model, language, progress_callback=None, use_vad=True):
        if progress_callback is not None:
            progress_callback(1, 4, 0.0)  # 25%
            progress_callback(4, 4, 0.0)  # 100%
        return TranscriptionResult(
            source_path=source_path, language=language, model=model, segments=[]
        )

    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)
    fractions: list[float] = []
    MlxWhisperTranscriptionBackend(Config()).transcribe(
        Path("/tmp/meeting.wav"), _options(), fractions.append
    )
    assert fractions == [0.25, 1.0]


def test_apple_speech_backend_forwards_progress_fraction(tmp_path) -> None:
    import json as _json
    import stat

    # A helper stub that streams one progress notice then the final envelope.
    payload = _json.dumps({"ok": True, "transcript": _TRANSCRIPT_PAYLOAD})
    script = tmp_path / "apple-transcribe"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'if "--check" in sys.argv:\n'
        '    sys.stdout.write(\'{"ok": true}\\n\'); sys.exit(0)\n'
        'sys.stdout.write(\'{"progress": {"fraction": 0.5}}\\n\')\n'
        f"sys.stdout.write({_json.dumps(payload)} + '\\n')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    cfg = Config(advanced=AdvancedSection(apple_transcribe_path=str(script)))
    fractions: list[float] = []
    transcript = AppleSpeechTranscriptionBackend(cfg).transcribe(
        Path("/tmp/meeting.wav"), _options(), fractions.append
    )
    assert fractions == [0.5]
    assert len(transcript.segments) == 2
