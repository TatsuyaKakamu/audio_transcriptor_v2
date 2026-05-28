from __future__ import annotations

import pytest

from app.config import AdvancedSection, AppSection, Config
from app.core.capabilities import Capabilities
from app.core.errors import (
    BackendUnavailableError,
    NoTranscriptionBackendError,
)
from app.core.pipeline import (
    choose_summary_backend,
    choose_transcription_backend,
    summary_backend_order,
    transcription_backend_order,
)


def _caps(**overrides) -> Capabilities:
    base = dict(
        macos_version="26.0",
        apple_silicon=True,
        apple_speech_available=False,
        apple_foundation_available=False,
        mlx_whisper_available=False,
        ollama_available=False,
        ffmpeg_available=False,
        api_key_available=False,
    )
    base.update(overrides)
    return Capabilities(**base)


def _config(mode="auto", transcription_backend="auto", summary_backend="auto") -> Config:
    return Config(
        app=AppSection(mode=mode),
        advanced=AdvancedSection(
            transcription_backend=transcription_backend,
            summary_backend=summary_backend,
        ),
    )


# -- transcription auto priority ------------------------------------------- #


def test_transcription_prefers_apple_speech() -> None:
    caps = _caps(apple_speech_available=True, mlx_whisper_available=True, ffmpeg_available=True)
    assert choose_transcription_backend(_config(), caps) == "apple_speech"


def test_transcription_falls_to_mlx_when_no_apple() -> None:
    caps = _caps(mlx_whisper_available=True, ffmpeg_available=True)
    assert choose_transcription_backend(_config(), caps) == "mlx_whisper"


def test_transcription_requires_ffmpeg_for_mlx() -> None:
    caps = _caps(mlx_whisper_available=True, ffmpeg_available=False)
    with pytest.raises(NoTranscriptionBackendError):
        choose_transcription_backend(_config(), caps)


def test_transcription_none_raises() -> None:
    with pytest.raises(NoTranscriptionBackendError):
        choose_transcription_backend(_config(), _caps())


def test_transcription_explicit_unavailable_raises() -> None:
    with pytest.raises(BackendUnavailableError):
        choose_transcription_backend(
            _config(transcription_backend="apple_speech"), _caps()
        )


# -- summary auto priority -------------------------------------------------- #


def test_summary_prefers_apple_foundation() -> None:
    caps = _caps(apple_foundation_available=True, ollama_available=True, api_key_available=True)
    assert choose_summary_backend(_config(), caps) == "apple_foundation"


def test_summary_falls_to_ollama() -> None:
    caps = _caps(ollama_available=True, api_key_available=True)
    assert choose_summary_backend(_config(), caps) == "ollama"


def test_summary_falls_to_api() -> None:
    caps = _caps(api_key_available=True)
    assert choose_summary_backend(_config(), caps) == "api"


def test_summary_falls_to_none() -> None:
    assert choose_summary_backend(_config(), _caps()) == "none"


def test_summary_explicit_unavailable_raises() -> None:
    with pytest.raises(BackendUnavailableError):
        choose_summary_backend(_config(summary_backend="ollama"), _caps())


# -- fallback ordering ------------------------------------------------------ #


def test_transcription_order_auto_lists_both() -> None:
    caps = _caps(apple_speech_available=True, mlx_whisper_available=True, ffmpeg_available=True)
    assert transcription_backend_order(_config(), caps) == ["apple_speech", "mlx_whisper"]


def test_summary_order_auto_lists_all_then_none() -> None:
    caps = _caps(apple_foundation_available=True, ollama_available=True, api_key_available=True)
    assert summary_backend_order(_config(), caps) == [
        "apple_foundation",
        "ollama",
        "api",
        "none",
    ]


def test_summary_order_always_ends_with_none() -> None:
    assert summary_backend_order(_config(), _caps()) == ["none"]


# -- modes ------------------------------------------------------------------ #


def test_legacy_mode_prefers_mlx_and_ollama() -> None:
    caps = _caps(
        apple_speech_available=True,
        mlx_whisper_available=True,
        ffmpeg_available=True,
        apple_foundation_available=True,
        ollama_available=True,
    )
    assert transcription_backend_order(_config(mode="legacy"), caps)[0] == "mlx_whisper"
    assert summary_backend_order(_config(mode="legacy"), caps)[0] == "ollama"


def test_apple_native_mode_requires_apple() -> None:
    caps = _caps(mlx_whisper_available=True, ffmpeg_available=True, ollama_available=True)
    with pytest.raises(NoTranscriptionBackendError):
        transcription_backend_order(_config(mode="apple_native"), caps)
    with pytest.raises(BackendUnavailableError):
        summary_backend_order(_config(mode="apple_native"), caps)


def test_apple_native_mode_success() -> None:
    caps = _caps(apple_speech_available=True, apple_foundation_available=True)
    assert transcription_backend_order(_config(mode="apple_native"), caps) == ["apple_speech"]
    assert summary_backend_order(_config(mode="apple_native"), caps) == ["apple_foundation"]
