from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import load_config, load_full_config
from app.services import notifier
from app.ui.drop_area import SUPPORTED_EXTENSIONS, DropArea
from app.workers.transcription_worker import TranscriptionWorker

_LANGUAGES = [("Japanese (ja)", "ja"), ("English (en)", "en")]
# Processing mode (overall preset). The transcription/summary dropdowns below can
# override each axis independently; "auto" on those means "follow the mode".
_MODES = [
    ("自動 (auto)", "auto"),
    ("Apple ネイティブ", "apple_native"),
    ("レガシー (mlx-whisper)", "legacy"),
]
# Per-axis backend selection (independent of each other). "auto" follows the mode.
_TRANSCRIPTION_BACKENDS = [
    ("自動 (auto)", "auto"),
    ("Apple SpeechAnalyzer", "apple_speech"),
    ("mlx-whisper", "mlx_whisper"),
]
_SUMMARY_BACKENDS = [
    ("自動 (auto)", "auto"),
    ("Apple Foundation", "apple_foundation"),
    ("Ollama", "ollama"),
    ("なし (none)", "none"),
]
# Legacy mlx-whisper model sizes. Ignored by the Apple SpeechAnalyzer backend.
_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
_APP_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "app_icon.svg"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Audio Transcript Tool")
        if _APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(_APP_ICON_PATH)))
        self._worker: TranscriptionWorker | None = None
        self._processing = False
        self._config = load_config()
        full = load_full_config()
        self._default_mode = full.app.mode
        self._default_tx_backend = full.advanced.transcription_backend
        self._default_sm_backend = full.advanced.summary_backend
        self._setup_ui()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        self._drop_area = DropArea()
        self._drop_area.setMinimumHeight(150)
        self._drop_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._drop_area.files_dropped.connect(self._on_files_dropped)
        root.addWidget(self._drop_area)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("処理方式:"))
        self._mode_combo = QComboBox()
        for label, value in _MODES:
            self._mode_combo.addItem(label, value)
        mode_idx = self._mode_combo.findData(self._default_mode)
        if mode_idx >= 0:
            self._mode_combo.setCurrentIndex(mode_idx)
        self._mode_combo.setToolTip(
            "音声を処理するバックエンド。\n"
            "auto: 利用可能な最良のものを自動選択（必要なら mlx-whisper にフォールバック）\n"
            "Apple ネイティブ: Apple SpeechAnalyzer / Foundation Models（モデル選択は不要）\n"
            "レガシー: mlx-whisper + Ollama（下のモデル選択が有効）"
        )
        self._mode_combo.currentIndexChanged.connect(self._on_settings_changed)
        settings.addWidget(self._mode_combo)
        settings.addSpacing(20)
        settings.addWidget(QLabel("言語:"))
        self._lang_combo = QComboBox()
        for label, code in _LANGUAGES:
            self._lang_combo.addItem(label, code)
        lang_idx = self._lang_combo.findData(self._config.language)
        if lang_idx >= 0:
            self._lang_combo.setCurrentIndex(lang_idx)
        settings.addWidget(self._lang_combo)
        settings.addSpacing(20)
        self._model_label = QLabel("モデル (legacy):")
        settings.addWidget(self._model_label)
        self._model_combo = QComboBox()
        for m in _MODELS:
            self._model_combo.addItem(m)
        if self._config.model in _MODELS:
            self._model_combo.setCurrentText(self._config.model)
        self._model_combo.setToolTip(
            "mlx-whisper（レガシーバックエンド）専用のモデルサイズ。\n"
            "Apple ネイティブ経路では使われません。"
        )
        settings.addWidget(self._model_combo)
        settings.addStretch()
        root.addLayout(settings)

        # Second row: independent per-axis backend selection. "auto" follows the
        # mode above, so transcription and summary can be controlled separately
        # (e.g. summary on Apple Foundation only, never Ollama).
        backends = QHBoxLayout()
        backends.addWidget(QLabel("文字起こし:"))
        self._tx_combo = QComboBox()
        for label, value in _TRANSCRIPTION_BACKENDS:
            self._tx_combo.addItem(label, value)
        tx_idx = self._tx_combo.findData(self._default_tx_backend)
        if tx_idx >= 0:
            self._tx_combo.setCurrentIndex(tx_idx)
        self._tx_combo.setToolTip(
            "文字起こしバックエンド。\n"
            "auto: 上の処理方式に従って自動選択\n"
            "Apple SpeechAnalyzer / mlx-whisper を明示指定可能"
        )
        self._tx_combo.currentIndexChanged.connect(self._on_settings_changed)
        backends.addWidget(self._tx_combo)
        backends.addSpacing(20)
        backends.addWidget(QLabel("要約:"))
        self._sm_combo = QComboBox()
        for label, value in _SUMMARY_BACKENDS:
            self._sm_combo.addItem(label, value)
        sm_idx = self._sm_combo.findData(self._default_sm_backend)
        if sm_idx >= 0:
            self._sm_combo.setCurrentIndex(sm_idx)
        self._sm_combo.setToolTip(
            "要約バックエンド。\n"
            "auto: 上の処理方式に従って自動選択\n"
            "Apple Foundation / Ollama を明示指定、none で要約を無効化"
        )
        backends.addWidget(self._sm_combo)
        backends.addStretch()
        root.addLayout(backends)

        # Apple native / explicit backends need no model selection; reflect state.
        self._on_settings_changed()

        self._status_label = QLabel("待機中")
        root.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        root.addWidget(self._progress_bar)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(200)
        root.addWidget(self._log_view)

        clear_btn = QPushButton("ログをクリア")
        clear_btn.clicked.connect(self._log_view.clear)
        root.addWidget(clear_btn, alignment=Qt.AlignRight)

        self.resize(640, 540)

    def _on_settings_changed(self, *_args: object) -> None:
        # The model dropdown only applies to the mlx-whisper backend. Disable it
        # when mlx-whisper cannot run: an explicit Apple SpeechAnalyzer choice, or
        # auto transcription under Apple-native mode. It stays enabled when mlx is
        # explicitly chosen or auto could fall back to it.
        tx = self._tx_combo.currentData()
        mode = self._mode_combo.currentData()
        if tx == "mlx_whisper":
            relevant = True
        elif tx == "apple_speech":
            relevant = False
        else:  # auto -> depends on the mode
            relevant = mode != "apple_native"
        self._model_label.setEnabled(relevant)
        self._model_combo.setEnabled(relevant)

    def _on_files_dropped(self, paths: list[Path]) -> None:
        if self._processing:
            self._append_log("WARN", "現在処理中のため新しいドロップは無視しました")
            return

        valid: list[Path] = []
        for path in paths:
            if not path.exists():
                self._append_log("WARN", f"File not found: {path}")
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                self._append_log("WARN", f"Unsupported file skipped: {path}")
                continue
            valid.append(path)

        if not valid:
            self._append_log("INFO", "有効なファイルがありませんでした")
            return

        self._append_log("INFO", f"{len(valid)} files dropped")
        language: str = self._lang_combo.currentData()
        model: str = self._model_combo.currentText()
        mode: str = self._mode_combo.currentData()
        tx_backend: str = self._tx_combo.currentData()
        sm_backend: str = self._sm_combo.currentData()
        self._start_processing(valid, language, model, mode, tx_backend, sm_backend)

    def _start_processing(
        self,
        files: list[Path],
        language: str,
        model: str,
        mode: str,
        transcription_backend: str,
        summary_backend: str,
    ) -> None:
        self._processing = True
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_label.setText(f"{len(files)}件中 1件目を処理中")
        self._worker = TranscriptionWorker(
            files,
            language,
            model,
            self._config,
            mode,
            transcription_backend,
            summary_backend,
        )
        self._worker.log_message.connect(self._append_log)
        self._worker.status_update.connect(self._status_label.setText)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, overall_percent: float) -> None:
        self._progress_bar.setValue(int(overall_percent * 10))

    def _on_finished(self, had_errors: bool, success: int, failure: int) -> None:
        self._processing = False
        self._progress_bar.setValue(1000)
        self._progress_bar.setVisible(False)
        self._status_label.setText("エラーあり" if had_errors else "完了")

        if failure == 0:
            body = f"{success}件 成功"
        elif success == 0:
            body = f"{failure}件 失敗"
        else:
            body = f"{success + failure}件中 {success}件 成功 / {failure}件 失敗"
        notifier.notify("文字起こし完了", body)

    def _append_log(self, level: str, message: str) -> None:
        self._log_view.append(f"[{level}] {message}")
