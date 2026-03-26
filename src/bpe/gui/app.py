"""Application entry point — QApplication setup and main window launch."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from bpe.gui.theme import build_stylesheet


def _find_icon() -> str:
    """번들 또는 소스 트리에서 아이콘 경로를 찾는다."""
    # PyInstaller 번들
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "icon.png"
        if p.exists():
            return str(p)

    # 소스 트리
    p = Path(__file__).resolve().parent.parent.parent.parent / "installer" / "icon.png"
    if p.exists():
        return str(p)

    return ""


def run_app(argv: List[str] | None = None) -> int:
    """Create QApplication, show splash, then main window."""
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("BPE")
    app.setStyleSheet(build_stylesheet())

    # 아이콘 설정
    icon_path = _find_icon()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # 스플래시 먼저 띄우기
    from bpe.gui.splash import SplashScreen

    splash = SplashScreen()
    splash.show()
    app.processEvents()

    # 스플래시 애니메이션 중 메인 윈도우 생성 (백그라운드)
    window = None

    def _init_main() -> None:
        nonlocal window
        from bpe.gui.main_window import MainWindow

        window = MainWindow()

    # 스플래시 뜨고 300ms 후 메인윈도우 초기화 시작
    QTimer.singleShot(300, _init_main)

    def _show_main() -> None:
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()

    splash.on_finished(_show_main)

    return app.exec()
