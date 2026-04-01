"""Drag-and-drop zone — accepts file drops and emits the path."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from bpe.core.nuke_render_paths import normalize_path_str


class DropZone(QLabel):
    """A label that accepts file drops and emits *file_dropped(path)*."""

    file_dropped = Signal(str)
    paste_text = Signal(str)

    def __init__(
        self,
        placeholder: str = "파일을 여기에 드래그하세요",
        parent: Optional[QWidget] = None,
        allowed_extensions: Optional[List[str]] = None,
    ) -> None:
        super().__init__(placeholder, parent)
        self._allowed_extensions = [e.lower() for e in (allowed_extensions or [])]
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setWordWrap(True)
        self.setObjectName("drop_zone")
        self.setProperty("class", "card")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _path_allowed(self, path: str) -> bool:
        if not self._allowed_extensions:
            return True
        lower = path.lower()
        return any(lower.endswith(ext) for ext in self._allowed_extensions)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Paste):
            clip = QApplication.clipboard()
            if clip is not None and clip.mimeData().hasText():
                text = clip.mimeData().text()
                if text.strip():
                    self.paste_text.emit(text)
                    event.accept()
                    return
        super().keyPressEvent(event)

    # --- drag / drop ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        path = urls[0].toLocalFile()
        if self._path_allowed(path):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if not self._path_allowed(path):
            event.ignore()
            return
        path_n = normalize_path_str(path)
        self.setText(path_n)
        self.setProperty("has_file", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.file_dropped.emit(path_n)
