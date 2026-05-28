from __future__ import annotations

from app.config import AdvancedSection, Config
from app.core import capabilities
from app.core.capabilities import Capabilities, detect_capabilities


def _patch_all(monkeypatch, **overrides) -> None:
    defaults = dict(
        detect_macos_version=lambda: "26.0",
        detect_apple_silicon=lambda: True,
        detect_apple_speech=lambda cfg: True,
        detect_apple_foundation=lambda cfg: True,
        detect_mlx_whisper=lambda: True,
        detect_ffmpeg=lambda: True,
        detect_ollama=lambda cfg: True,
    )
    defaults.update(overrides)
    for name, fn in defaults.items():
        monkeypatch.setattr(capabilities, name, fn)


def test_detect_capabilities_all_available(monkeypatch) -> None:
    _patch_all(monkeypatch)
    caps = detect_capabilities(Config())
    assert isinstance(caps, Capabilities)
    assert caps.apple_speech_available
    assert caps.apple_foundation_available
    assert caps.mlx_whisper_available
    assert caps.ollama_available
    assert caps.ffmpeg_available
    assert caps.apple_silicon
    assert caps.macos_version == "26.0"


def test_detect_capabilities_nothing_available(monkeypatch) -> None:
    _patch_all(
        monkeypatch,
        detect_macos_version=lambda: None,
        detect_apple_silicon=lambda: False,
        detect_apple_speech=lambda cfg: False,
        detect_apple_foundation=lambda cfg: False,
        detect_mlx_whisper=lambda: False,
        detect_ffmpeg=lambda: False,
        detect_ollama=lambda cfg: False,
    )
    caps = detect_capabilities(Config())
    assert not any(
        [
            caps.apple_speech_available,
            caps.apple_foundation_available,
            caps.mlx_whisper_available,
            caps.ollama_available,
            caps.ffmpeg_available,
            caps.apple_silicon,
        ]
    )
    assert caps.macos_version is None


def test_detect_apple_speech_uses_helper_path(monkeypatch, make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-transcribe",
        check={"ok": True, "backend": "apple_speech", "version": "0.1.0"},
        main={"ok": True},
    )
    cfg = Config(advanced=AdvancedSection(apple_transcribe_path=str(helper)))
    assert capabilities.detect_apple_speech(cfg) is True
