"""Application entry point — QApplication setup and main window launch."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from bpe.core.windows_app_id import apply_explicit_app_user_model_id
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


def _ensure_pyinstaller_qt_plugins() -> None:
    """onefile 번들에서 Qt 멀티미디어 등 플러그인 경로를 잡는다."""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    import os

    plug = os.path.join(meipass, "PySide6", "plugins")
    if os.path.isdir(plug):
        QCoreApplication.addLibraryPath(plug)


def run_app(argv: List[str] | None = None) -> int:
    """Create QApplication, show splash, then main window."""
    if argv is None:
        argv = sys.argv

    _ensure_pyinstaller_qt_plugins()

    # Qt가 부팅 시 AppUserModelID를 다시 잡는 경우가 있어, 인스턴스 생성 직후 셸 ID를 재적용한다.
    QCoreApplication.setOrganizationName("Beluca")
    QCoreApplication.setApplicationName("BPE")
    app = QApplication(argv)
    apply_explicit_app_user_model_id()
    app.setStyleSheet(build_stylesheet())

    # 아이콘 설정
    icon_path = _find_icon()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    from bpe.core.logging import get_logger

    logger = get_logger("app")
    logger.info("BPE 부팅 시작")

    # 스플래시 먼저 띄우기
    from bpe.gui.splash import SplashScreen

    splash = SplashScreen()
    splash.show()
    app.processEvents()
    logger.info("스플래시 표시 완료")

    def _normalize_nuke_plugin() -> None:
        """기동 시 Nuke 를 순정 상태로 되돌린다 (BPE 설치물만 제거).

        Nuke 쪽 훅(onSave/onLoad Write 경로 재계산)이 렌더 절대경로를 깨뜨려 온
        이력이 있어, BPE 는 더 이상 Nuke 에 아무것도 설치하지 않는다. 이미 설치된
        PC 도 BPE 를 한 번 실행하면 자동으로 정리된다. 멱등 — 없으면 no-op.
        """
        try:
            from bpe.core.nuke_plugin_install import remove_nuke_plugin

            result = remove_nuke_plugin()
            if result.get("removed_dir") or result.get("menu_cleaned"):
                logger.info(
                    "Nuke 플러그인 정상화 완료 (dir=%s, menu=%s) — Nuke 재시작 후 반영",
                    result.get("removed_dir"),
                    result.get("menu_cleaned"),
                )
            if result.get("error"):
                logger.warning("Nuke 플러그인 정상화 일부 실패: %s", result["error"])
        except Exception:
            logger.warning("Nuke 플러그인 정상화 실패", exc_info=True)

    QTimer.singleShot(0, _normalize_nuke_plugin)

    # 스플래시 애니메이션 중 메인 윈도우 생성 (백그라운드)
    window = None

    def _init_main() -> None:
        nonlocal window
        logger.info("MainWindow 생성 시작")
        try:
            from bpe.gui.main_window import MainWindow

            window = MainWindow()
            logger.info("MainWindow 생성 완료")
        except Exception:
            logger.critical("MainWindow 생성 실패", exc_info=True)

    # 스플래시 뜨고 300ms 후 메인윈도우 초기화 시작
    QTimer.singleShot(300, _init_main)

    def _show_main() -> None:
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()
            logger.info("메인 윈도우 표시 완료")
        else:
            logger.critical("메인 윈도우가 None — 생성 실패 또는 타이밍 경합")

    splash.on_finished(_show_main)

    return app.exec()
