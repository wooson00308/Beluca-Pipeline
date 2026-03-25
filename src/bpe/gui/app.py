"""Application entry point — QApplication setup and main window launch."""

from __future__ import annotations

import sys
from typing import List

from PySide6.QtWidgets import QApplication

from bpe.gui.theme import build_stylesheet


def run_app(argv: List[str] | None = None) -> int:
    """Create QApplication, apply theme, show MainWindow, and exec."""
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("BPE")
    app.setApplicationVersion("0.2.0")
    app.setStyleSheet(build_stylesheet())

    from bpe.gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    return app.exec()
