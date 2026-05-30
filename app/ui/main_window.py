from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
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

_LANGUAGES = [("日本語 (ja)", "ja"), ("English (en)", "en")]
# Transcription backend. "自動" = pick the best available and fall back as needed.
_TRANSCRIPTION_BACKENDS = [
    ("自動", "auto"),
    ("Apple SpeechAnalyzer", "apple_speech"),
    ("mlx-whisper", "mlx_whisper"),
]
# Summary backend. "自動" = best available; "なし" disables summaries entirely.
_SUMMARY_BACKENDS = [
    ("自動", "auto"),
    ("Apple Foundation", "apple_foundation"),
    ("Ollama", "ollama"),
    ("なし（要約しない）", "none"),
]
# mlx-whisper model sizes. Only relevant when mlx-whisper is the transcription
# backend; the Apple SpeechAnalyzer backend ignores this.
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

        # Common: language.
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("言語:"))
        self._lang_combo = QComboBox()
        for label, code in _LANGUAGES:
            self._lang_combo.addItem(label, code)
        lang_idx = self._lang_combo.findData(self._config.language)
        if lang_idx >= 0:
            self._lang_combo.setCurrentIndex(lang_idx)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        root.addLayout(lang_row)

        # Two independent stages, each in its own group so it's obvious that the
        # transcription and summary backends are chosen separately.
        root.addWidget(self._build_transcription_group())
        root.addWidget(self._build_summary_group())

        # Warns about backend combinations that contend for Apple's on-device
        # models (hidden unless a problematic pairing is selected).
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #b35900;")
        self._warning_label.setVisible(False)
        root.addWidget(self._warning_label)

        # Reflect the initial backend choice on the model control and warning.
        self._on_transcription_changed()

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

        self.resize(640, 560)

    def _build_transcription_group(self) -> QGroupBox:
        group = QGroupBox("文字起こし")
        form = QFormLayout(group)

        self._tx_combo = QComboBox()
        for label, value in _TRANSCRIPTION_BACKENDS:
            self._tx_combo.addItem(label, value)
        tx_idx = self._tx_combo.findData(self._default_tx_backend)
        if tx_idx >= 0:
            self._tx_combo.setCurrentIndex(tx_idx)
        self._tx_combo.setToolTip(
            "文字起こしに使うエンジン。\n"
            "自動: 利用可能な最良のものを選択（必要なら mlx-whisper にフォールバック）\n"
            "Apple SpeechAnalyzer / mlx-whisper を明示指定することもできる。"
        )
        self._tx_combo.currentIndexChanged.connect(self._on_transcription_changed)
        form.addRow("エンジン:", self._tx_combo)

        self._model_combo = QComboBox()
        for m in _MODELS:
            self._model_combo.addItem(m)
        if self._config.model in _MODELS:
            self._model_combo.setCurrentText(self._config.model)
        self._model_combo.setToolTip(
            "mlx-whisper のモデルサイズ。\n"
            "Apple SpeechAnalyzer では使われないため、その場合は無効化される。"
        )
        self._model_label = QLabel("モデル:")
        form.addRow(self._model_label, self._model_combo)
        return group

    def _build_summary_group(self) -> QGroupBox:
        group = QGroupBox("要約")
        form = QFormLayout(group)

        self._sm_combo = QComboBox()
        for label, value in _SUMMARY_BACKENDS:
            self._sm_combo.addItem(label, value)
        sm_idx = self._sm_combo.findData(self._default_sm_backend)
        if sm_idx >= 0:
            self._sm_combo.setCurrentIndex(sm_idx)
        self._sm_combo.setToolTip(
            "要約（議事録）に使うエンジン。\n"
            "自動: 利用可能な最良のものを選択（必要なら Ollama にフォールバック）\n"
            "Apple Foundation / Ollama を明示指定、または「なし」で要約を無効化。"
        )
        self._sm_combo.currentIndexChanged.connect(self._update_warning)
        form.addRow("エンジン:", self._sm_combo)
        return group

    def _on_transcription_changed(self, *_args: object) -> None:
        # The model dropdown only applies to mlx-whisper. Disable it for an
        # explicit Apple SpeechAnalyzer choice; keep it enabled for mlx-whisper
        # and for "自動" (which may fall back to mlx-whisper).
        tx = self._tx_combo.currentData()
        relevant = tx != "apple_speech"
        self._model_label.setEnabled(relevant)
        self._model_combo.setEnabled(relevant)
        self._update_warning()

    def _update_warning(self, *_args: object) -> None:
        # mlx-whisper and Apple Foundation Models both load heavy on-device
        # models and can contend with each other, slowing the run. Warn only on
        # the explicit pairing; "自動" is left out to avoid false alarms since it
        # may resolve to a non-conflicting backend.
        tx = self._tx_combo.currentData()
        sm = self._sm_combo.currentData()
        conflict = tx == "mlx_whisper" and sm == "apple_foundation"
        if conflict:
            self._warning_label.setText(
                "⚠️ 文字起こし「mlx-whisper」と要約「Apple Foundation」の組み合わせは、"
                "Apple のモデルロードと競合して処理が遅くなることがあります。"
            )
        self._warning_label.setVisible(conflict)

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
        tx_backend: str = self._tx_combo.currentData()
        sm_backend: str = self._sm_combo.currentData()
        self._start_processing(valid, language, model, tx_backend, sm_backend)

    def _start_processing(
        self,
        files: list[Path],
        language: str,
        model: str,
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
            transcription_backend=transcription_backend,
            summary_backend=summary_backend,
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
