import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.config import AppConfig, load_full_config
from app.core.errors import NoTranscriptionBackendError
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
        mode: str | None = None,
    ) -> None:
        super().__init__()
        self._files = files
        self._language = language
        self._model = model
        self._cfg = cfg
        self._mode = mode

    def _build_config(self):
        """v2 config with the UI's mode/language/model and the legacy minutes toggle."""
        config = load_full_config()
        advanced = config.advanced
        # Preserve the legacy "[minutes].enabled = false" behaviour.
        if not self._cfg.minutes.enabled:
            advanced = replace(advanced, summary_backend="none")
        # The UI can pick the processing mode (auto / apple_native / legacy)
        # explicitly; fall back to the configured mode when not provided.
        app = replace(
            config.app,
            language=_TRANSCRIBE_LOCALE.get(self._language, config.app.language),
        )
        if self._mode:
            app = replace(app, mode=self._mode)
        return replace(
            config,
            app=app,
            advanced=advanced,
            transcription=replace(config.transcription, model=self._model),
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
        except NoTranscriptionBackendError as e:
            self.log_message.emit("ERROR", f"利用可能な文字起こしバックエンドがありません: {e}")
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

            # Map the current file's transcription fraction (0..1) onto the
            # overall bar so a single long file shows live progress instead of
            # jumping 0% -> 100%. Qt signals marshal safely across the thread.
            file_index = i - 1

            def on_file_progress(fraction: float, _base: int = file_index) -> None:
                self.progress.emit((_base + fraction) / total_files * 100)

            try:
                result = pipeline.run(path, options, on_file_progress)
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
