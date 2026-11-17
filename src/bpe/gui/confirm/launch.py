"""컨펌 창 여는 길 — BPE 안에서 열기, 그리고 시작 옵션으로 바로 열기.

시작 옵션(잠금 화면을 거치지 않음, 시험용):
  ``--confirm [영상 경로]``      컨펌 창만 띄운다
  ``--confirm-probe``            화면 계산 시험 창만 띄운다
  ``--confirm-capture <png>``    몇 초 뒤 창을 그림으로 저장하고 끝낸다(빌드 확인용)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from bpe.core.logging import get_logger

logger = get_logger("gui.confirm.launch")

FLAG_CONFIRM = "--confirm"
FLAG_PROBE = "--confirm-probe"
FLAG_CAPTURE = "--confirm-capture"
_CAPTURE_DELAY_MS = 6000

_open_windows: List[Any] = []


def wants_standalone(argv: List[str]) -> bool:
    return FLAG_CONFIRM in argv or FLAG_PROBE in argv


def _as_independent_window(win: QWidget) -> None:
    win.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    # 이 창이 남아 있어도 BPE 메인 창을 닫으면 앱이 종료되게 한다.
    win.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)


def open_confirm_window(movie: Optional[str] = None, task: Optional[Dict[str, Any]] = None) -> Any:
    """컨펌 창을 연다. 이미 열려 있으면 그 창을 앞으로 가져와 새 영상을 올린다."""
    from bpe.gui.confirm.confirm_window import ConfirmWindow

    _open_windows[:] = [w for w in _open_windows if not w.is_closed()]
    win = _open_windows[0] if _open_windows else None
    if win is None:
        win = ConfirmWindow(None)
        _as_independent_window(win)
        _open_windows.append(win)
        win.show()
    else:
        if win.isMinimized():
            win.setWindowState(
                (win.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
            )
        win.raise_()
        win.activateWindow()
    if movie:
        win.open_movie(movie, task)
    return win


def _arg_after(argv: List[str], flag: str) -> str:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            return argv[i + 1]
    return ""


def run_standalone(argv: List[str]) -> int:
    """시작 옵션으로 컨펌 창(또는 시험 창)만 띄운다."""
    from bpe.gui.app import _ensure_pyinstaller_qt_plugins, _find_icon
    from bpe.gui.theme import build_stylesheet

    _ensure_pyinstaller_qt_plugins()
    app = QApplication(argv)
    app.setStyleSheet(build_stylesheet())
    icon_path = _find_icon()
    if icon_path:
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(icon_path))

    if FLAG_PROBE in argv:
        from bpe.gui.confirm.gl_probe_window import ConfirmGLProbeWindow

        win: Any = ConfirmGLProbeWindow(None)
        win.show()
    else:
        from bpe.gui.confirm.confirm_window import ConfirmWindow

        win = ConfirmWindow(None)
        win.show()
        movie = _arg_after(argv, FLAG_CONFIRM)
        if movie:
            win.open_movie(movie)

    capture = _arg_after(argv, FLAG_CAPTURE)
    if capture:

        def _shoot() -> None:
            ok = win.grab().save(capture)
            logger.info("confirm capture saved=%s path=%s", ok, capture)
            app.quit()

        QTimer.singleShot(_CAPTURE_DELAY_MS, _shoot)
    return int(app.exec())
