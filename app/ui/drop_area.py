from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QLabel

SUPPORTED_EXTENSIONS = frozenset({".wav", ".mp3"})


class DropArea(QLabel):
    files_dropped = Signal(list)  # list[Path]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setText("ここに wav / mp3 ファイルをドラッグ&ドロップ\n複数ファイル対応")
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #aaaaaa;
                border-radius: 8px;
                font-size: 15px;
                color: #555555;
                background: #f5f5f5;
                padding: 30px;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        seen: set[Path] = set()
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
        self.files_dropped.emit(paths)
