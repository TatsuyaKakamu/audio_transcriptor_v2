import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.config import AppConfig, load_full_config, override_config
from app.core.errors import PipelineError
from app.core.pipeline import PipelineOptions, build_pipeline, describe_selection
from app.summary.base import SummaryOptions
from app.transcription.base import TranscriptionOptions

# UI language codes ("ja" / "en") -> transcription locale identifiers.
_TRANSCRIBE_LOCALE = {"ja": "ja-JP", "en": "en-US"}


class TranscriptionWorker(QThread):
    log_message = Signal(str, str)             # level, message
    status_update = Signal(str)
    progress = Signal(float)                   # overall_percent 0-100
    finished = Signal(bool, int, int)          # had_errors, success_count, failure_count

    def __init__(
        self,
        files: list[Path],
        language: str,
        model: str,
        cfg: AppConfig,
        transcription_backend: str | None = None,
        summary_backend: str | None = None,
    ) -> None:
        super().__init__()
        self._files = files
        self._language = language
        self._model = model
        self._cfg = cfg
        # Independent per-axis backend overrides. "auto" / None picks the best
        # available backend (with runtime fallback), so the two stages are
        # controlled separately.
        self._transcription_backend = transcription_backend
        self._summary_backend = summary_backend

    def _build_config(self):
        """v2 config with the UI's language/model and per-axis backend overrides."""
        config = load_full_config()
        summary_backend = self._summary_backend
        # Honor the legacy "[minutes].enabled = false" kill switch. CLAUDE.md
        # documents that it maps to summary_backend = "none" in the GUI flow, so
        # it must win over the configured/selected backend too — not just the
        # "auto" default. Otherwise a config that pins an explicit summary
        # backend (apple_foundation / ollama) would silently re-enable minutes.
        if not self._cfg.minutes.enabled:
            summary_backend = "none"
        return override_config(
            config,
            transcription_backend=self._transcription_backend or None,
            summary_backend=summary_backend or None,
            language=_TRANSCRIBE_LOCALE.get(self._language, config.app.language),
            model=self._model,
        )

    def run(self) -> None:
        total_files = len(self._files)
        had_errors = False
        success_count = 0
        failure_count = 0

        config = self._build_config()
        self.status_update.emit(
            "バックエンドを準備中…（初回は Apple helper のビルドに時間がかかる場合があります）"
        )
        try:
            pipeline, selection = build_pipeline(config)
        except PipelineError as e:
            # Covers both a missing transcription backend and an explicitly
            # requested backend that is unavailable on this machine
            # (BackendUnavailableError). Emit finished so the UI does not stay
            # stuck in the processing state.
            self.log_message.emit("ERROR", f"バックエンドを準備できませんでした: {e}")
            self.finished.emit(True, 0, 0)
            return

        # Log the auto-selected route so the user can see which backend runs.
        for line in describe_selection(config, selection).splitlines():
            self.log_message.emit("INFO", line)

        options = PipelineOptions(
            transcription=TranscriptionOptions(
                language=config.app.language,
                model=self._model,
                vad_enabled=config.transcription.vad_enabled,
            ),
            summary=SummaryOptions(
                language=self._language,
                max_input_chars=config.summary.max_input_chars,
                include_evidence=config.summary.include_evidence,
                timeout_seconds=config.summary.request_timeout_seconds,
            ),
        )

        for i, path in enumerate(self._files, 1):
            self.progress.emit((i - 1) / total_files * 100)
            self.status_update.emit(f"{total_files}件中 {i}件目を処理中…")
            self.log_message.emit("INFO", f"Start: {path}")
            file_start = time.monotonic()

            try:
                result = pipeline.run(path, options)
            except Exception as e:
                had_errors = True
                failure_count += 1
                self.log_message.emit("ERROR", f"Failed: {path} — {e}")
                continue

            elapsed = time.monotonic() - file_start
            route = f"文字起こし={result.transcription_backend} / 議事録={result.summary_backend}"
            if result.fallback_occurred:
                route += "（フォールバック発生）"
            self.log_message.emit("INFO", f"経路: {route}")
            self.log_message.emit("INFO", f"Saved: {result.transcript_md_path}")
            if result.minutes_md_path is not None:
                self.log_message.emit("INFO", f"議事録: {result.minutes_md_path}")
            self.log_message.emit("INFO", f"完了: {path.name}（{elapsed:.1f}s）")
            success_count += 1
            self.progress.emit(i / total_files * 100)

        self.finished.emit(had_errors, success_count, failure_count)
