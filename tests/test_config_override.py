"""Tests for per-axis backend override plumbing (CLI flags + override_config)."""

from app.cli import _build_parser
from app.config import Config, override_config
from app.config.schema import AdvancedSection, AppSection, TranscriptionSection


def _config(mode="auto", tx="auto", sm="auto", model="medium", language="ja-JP"):
    return Config(
        app=AppSection(mode=mode, language=language),
        advanced=AdvancedSection(transcription_backend=tx, summary_backend=sm),
        transcription=TranscriptionSection(model=model),
    )


def test_override_none_leaves_config_unchanged():
    cfg = _config(mode="legacy", tx="mlx_whisper", sm="ollama", model="small")
    out = override_config(cfg)
    assert out == cfg


def test_override_applies_each_axis_independently():
    cfg = _config()
    out = override_config(cfg, summary_backend="apple_foundation")
    # only the summary axis changed
    assert out.advanced.summary_backend == "apple_foundation"
    assert out.advanced.transcription_backend == "auto"
    assert out.app.mode == "auto"


def test_override_all_fields():
    cfg = _config()
    out = override_config(
        cfg,
        mode="legacy",
        transcription_backend="mlx_whisper",
        summary_backend="none",
        language="en-US",
        model="large-v3",
    )
    assert out.app.mode == "legacy"
    assert out.app.language == "en-US"
    assert out.advanced.transcription_backend == "mlx_whisper"
    assert out.advanced.summary_backend == "none"
    assert out.transcription.model == "large-v3"


def test_override_invalid_value_falls_back_to_configured():
    cfg = _config(sm="ollama")
    out = override_config(cfg, summary_backend="not-a-backend")
    # invalid choice -> keep the previously configured backend
    assert out.advanced.summary_backend == "ollama"


def test_cli_parser_accepts_backend_overrides():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "transcribe",
            "a.wav",
            "--transcription-backend",
            "mlx_whisper",
            "--summary-backend",
            "apple_foundation",
            "--mode",
            "legacy",
        ]
    )
    assert args.paths == ["a.wav"]
    assert args.transcription_backend == "mlx_whisper"
    assert args.summary_backend == "apple_foundation"
    assert args.mode == "legacy"


def test_cli_parser_backend_overrides_default_to_none():
    parser = _build_parser()
    args = parser.parse_args(["transcribe", "a.wav"])
    assert args.mode is None
    assert args.transcription_backend is None
    assert args.summary_backend is None


def test_cli_capabilities_accepts_overrides():
    parser = _build_parser()
    args = parser.parse_args(["capabilities", "--summary-backend", "none"])
    assert args.summary_backend == "none"
