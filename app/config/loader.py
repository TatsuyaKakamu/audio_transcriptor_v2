"""Parse TOML into the legacy ``AppConfig`` and the v2 ``Config`` trees."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from app.config.schema import (
    CONFIG_PATH,
    AdvancedSection,
    ApiSummaryConfig,
    AppConfig,
    AppSection,
    AutoPRConfig,
    Config,
    MinutesConfig,
    OllamaSummaryConfig,
    SummarySection,
    TranscriptionSection,
)

logger = logging.getLogger(__name__)

_MODES = frozenset({"auto", "apple_native", "legacy"})
_TRANSCRIPTION_BACKENDS = frozenset({"auto", "apple_speech", "mlx_whisper"})
_SUMMARY_BACKENDS = frozenset({"auto", "apple_foundation", "ollama", "api", "none"})


def _read_toml(path: Path) -> dict | None:
    """Return parsed TOML, or None when the file is missing/unreadable."""
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        logger.warning("failed to read config %s: %s — falling back to defaults", path, e)
        return None


# --------------------------------------------------------------------------- #
# Legacy loader
# --------------------------------------------------------------------------- #


def _parse_minutes(data: dict) -> MinutesConfig:
    defaults = MinutesConfig()
    return MinutesConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        ollama_host=str(data.get("ollama_host", defaults.ollama_host)),
        model=str(data.get("model", defaults.model)),
        prompt_language=str(data.get("prompt_language", defaults.prompt_language)),
        max_input_chars=int(data.get("max_input_chars", defaults.max_input_chars)),
        request_timeout_seconds=float(
            data.get("request_timeout_seconds", defaults.request_timeout_seconds)
        ),
        num_ctx=int(data.get("num_ctx", defaults.num_ctx)),
    )


def _parse_auto_pr(data: dict) -> AutoPRConfig:
    defaults = AutoPRConfig()
    repo_path_raw = data.get("repo_path")
    if repo_path_raw:
        repo_path = Path(str(repo_path_raw)).expanduser()
    else:
        repo_path = defaults.repo_path
    return AutoPRConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        repo_path=repo_path,
        transcript_subdir=str(data.get("transcript_subdir", defaults.transcript_subdir)),
        minutes_subdir=str(data.get("minutes_subdir", defaults.minutes_subdir)),
        default_branch=str(data.get("default_branch", defaults.default_branch)),
        branch_prefix=str(data.get("branch_prefix", defaults.branch_prefix)),
        commit_message_template=str(
            data.get("commit_message_template", defaults.commit_message_template)
        ),
        pr_title_template=str(data.get("pr_title_template", defaults.pr_title_template)),
        pr_body_template=str(data.get("pr_body_template", defaults.pr_body_template)),
        gh_repo=str(data.get("gh_repo", defaults.gh_repo)),
    )


def _parse(data: dict) -> AppConfig:
    defaults = AppConfig()

    language = str(data.get("language", defaults.language))
    model = str(data.get("model", defaults.model))

    watch_dir_raw = data.get("watch_dir")
    if watch_dir_raw:
        watch_dir = Path(str(watch_dir_raw)).expanduser()
    else:
        watch_dir = defaults.watch_dir

    ext_raw = data.get("extensions")
    if ext_raw:
        exts = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in ext_raw]
        extensions = frozenset(exts)
    else:
        extensions = defaults.extensions

    stability = float(data.get("file_stability_seconds", defaults.file_stability_seconds))
    trash = bool(data.get("trash_source_after_success", defaults.trash_source_after_success))

    minutes_raw = data.get("minutes")
    minutes = _parse_minutes(minutes_raw) if isinstance(minutes_raw, dict) else MinutesConfig()

    auto_pr_raw = data.get("auto_pr")
    auto_pr = _parse_auto_pr(auto_pr_raw) if isinstance(auto_pr_raw, dict) else AutoPRConfig()

    return AppConfig(
        language=language,
        model=model,
        watch_dir=watch_dir,
        extensions=extensions,
        file_stability_seconds=stability,
        trash_source_after_success=trash,
        minutes=minutes,
        auto_pr=auto_pr,
    )


def load_config(path: Path | None = None) -> AppConfig:
    data = _read_toml(path or CONFIG_PATH)
    return AppConfig() if data is None else _parse(data)


# --------------------------------------------------------------------------- #
# v2 loader
# --------------------------------------------------------------------------- #


def _validate_choice(value: str, allowed: frozenset[str], *, field_name: str, default: str) -> str:
    if value in allowed:
        return value
    logger.warning(
        "invalid %s %r; allowed=%s — falling back to %r",
        field_name,
        value,
        sorted(allowed),
        default,
    )
    return default


def _parse_app(data: dict) -> AppSection:
    d = AppSection()
    return AppSection(
        mode=_validate_choice(
            str(data.get("mode", d.mode)), _MODES, field_name="app.mode", default=d.mode
        ),
        language=str(data.get("language", d.language)),
        output_directory=str(data.get("output_directory", d.output_directory)),
    )


def _parse_advanced(data: dict) -> AdvancedSection:
    d = AdvancedSection()
    return AdvancedSection(
        transcription_backend=_validate_choice(
            str(data.get("transcription_backend", d.transcription_backend)),
            _TRANSCRIPTION_BACKENDS,
            field_name="advanced.transcription_backend",
            default=d.transcription_backend,
        ),
        summary_backend=_validate_choice(
            str(data.get("summary_backend", d.summary_backend)),
            _SUMMARY_BACKENDS,
            field_name="advanced.summary_backend",
            default=d.summary_backend,
        ),
        apple_transcribe_path=str(data.get("apple_transcribe_path", d.apple_transcribe_path)),
        apple_summarize_path=str(data.get("apple_summarize_path", d.apple_summarize_path)),
    )


def _parse_transcription(data: dict) -> TranscriptionSection:
    d = TranscriptionSection()
    return TranscriptionSection(
        model=str(data.get("model", d.model)),
        vad_enabled=bool(data.get("vad_enabled", d.vad_enabled)),
    )


def _parse_summary(data: dict) -> SummarySection:
    d = SummarySection()
    ollama_raw = data.get("ollama") if isinstance(data.get("ollama"), dict) else {}
    api_raw = data.get("api") if isinstance(data.get("api"), dict) else {}
    od = OllamaSummaryConfig()
    ad = ApiSummaryConfig()
    return SummarySection(
        output_language=str(data.get("output_language", d.output_language)),
        include_evidence=bool(data.get("include_evidence", d.include_evidence)),
        max_input_chars=int(data.get("max_input_chars", d.max_input_chars)),
        request_timeout_seconds=float(
            data.get("request_timeout_seconds", d.request_timeout_seconds)
        ),
        ollama=OllamaSummaryConfig(
            host=str(ollama_raw.get("host", od.host)),
            model=str(ollama_raw.get("model", od.model)),
            num_ctx=int(ollama_raw.get("num_ctx", od.num_ctx)),
        ),
        api=ApiSummaryConfig(
            provider=str(api_raw.get("provider", ad.provider)),
            model=str(api_raw.get("model", ad.model)),
            api_key_env=str(api_raw.get("api_key_env", ad.api_key_env)),
            base_url=str(api_raw.get("base_url", ad.base_url)),
        ),
    )


def _parse_v2(data: dict) -> Config:
    app_raw = data.get("app") if isinstance(data.get("app"), dict) else {}
    advanced_raw = data.get("advanced") if isinstance(data.get("advanced"), dict) else {}
    transcription_raw = (
        data.get("transcription") if isinstance(data.get("transcription"), dict) else {}
    )
    summary_raw = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return Config(
        app=_parse_app(app_raw),
        advanced=_parse_advanced(advanced_raw),
        transcription=_parse_transcription(transcription_raw),
        summary=_parse_summary(summary_raw),
    )


def load_full_config(path: Path | None = None) -> Config:
    """Load the v2 backend-abstraction config; falls back to defaults on any error."""
    data = _read_toml(path or CONFIG_PATH)
    return Config() if data is None else _parse_v2(data)
