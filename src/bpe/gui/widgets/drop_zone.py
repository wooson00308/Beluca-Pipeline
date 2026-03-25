"""Drag-and-drop zone — accepts file drops and emits the path."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget


class DropZone(QLabel):
    """A label that accepts file drops and emits *file_dropped(path)*."""

    file_dropped = Signal(str)

    def __init__(
        self,
        placeholder: str = "파일을 여기에 드래그하세요",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(placeholder, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setProperty("class", "card")

    # --- drag / drop ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.setText(path)
            self.file_dropped.emit(path)
