"""Main window — sidebar navigation + stacked tab pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe import __version__
from bpe.core.logging import get_logger
from bpe.gui import theme

logger = get_logger("main_window")

TAB_DEFS: List[Dict[str, str]] = [
    {"key": "presets", "label": "Preset Manager"},
    {"key": "shot_builder", "label": "Shot Builder"},
    {"key": "my_tasks", "label": "My Tasks"},
    {"key": "publish", "label": "Publish"},
    {"key": "tools", "label": "Tools"},
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BPE v{__version__}")
        self.setMinimumSize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
        self.resize(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT)
        self._workers: List[Any] = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        # Brand
        brand_box = QWidget()
        brand_box.setStyleSheet("background: transparent;")
        brand_layout = QVBoxLayout(brand_box)
        brand_layout.setContentsMargins(20, 24, 20, 4)
        brand_layout.setSpacing(0)

        brand_title = QLabel("BELUCA")
        brand_title.setObjectName("brand_title")
        brand_layout.addWidget(brand_title)

        brand_sub = QLabel("Pipeline Engine")
        brand_sub.setObjectName("brand_subtitle")
        brand_layout.addWidget(brand_sub)

        sb.addWidget(brand_box)
        sb.addSpacing(28)

        # Nav buttons
        self._tab_buttons: Dict[str, QPushButton] = {}
        for tab_def in TAB_DEFS:
            btn = QPushButton(tab_def["label"])
            btn.setProperty("selected", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=tab_def["key"]: self._switch_tab(k))
            sb.addWidget(btn)
            self._tab_buttons[tab_def["key"]] = btn

        sb.addStretch()

        # Version at bottom
        self._ver_label = QLabel(f"BPE v{__version__}")
        self._ver_label.setObjectName("sidebar_version")
        self._ver_label.setContentsMargins(20, 0, 0, 16)
        sb.addWidget(self._ver_label)

        root.addWidget(sidebar)

        # ── Content area ──
        self._stack = QStackedWidget()
        self._tab_pages: Dict[str, QWidget] = {}
        self._build_tabs()
        root.addWidget(self._stack, 1)

        self._switch_tab("presets")

        # ── Update check ──
        self._update_info: Any = None
        self._init_update_toast()
        self._start_update_check()

        # 4시간마다 재체크
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._start_update_check)
        self._update_timer.start(4 * 60 * 60 * 1000)

    def _init_update_toast(self) -> None:
        from bpe.gui.widgets.update_toast import UpdateToast

        self._toast = UpdateToast(self.centralWidget())
        self._toast.install_requested.connect(self._on_install_requested)
        self._toast.open_folder_requested.connect(self._on_open_folder)

    def _start_update_check(self) -> None:
        from bpe.gui.workers.update_worker import UpdateCheckWorker

        w = UpdateCheckWorker(__version__)
        w.update_available.connect(self._on_update_available)
        w.up_to_date.connect(self._on_up_to_date)
        w.start()
        self._workers.append(w)

    def _on_update_available(self, info: object) -> None:
        self._update_info = info
        self._toast.show_update(info.latest_version)  # type: ignore[attr-defined]

    def _on_up_to_date(self) -> None:
        self._ver_label.setText(f"BPE v{__version__} (최신)")

    def _on_install_requested(self) -> None:
        info = self._update_info
        if info is None or not info.download_url:
            return

        launcher = self._find_launcher()
        if launcher is None:
            QDesktopServices.openUrl(QUrl(info.html_url))
            return

        import subprocess

        subprocess.Popen(
            [
                str(launcher),
                "--version",
                info.latest_version,
                "--download-url",
                info.download_url,
                "--app-path",
                self._get_app_path(),
            ]
        )
        QApplication.instance().quit()

    def _find_launcher(self) -> Optional[Path]:
        """번들 내 런처 바이너리를 찾는다."""
        import sys as _sys

        if _sys.platform == "darwin":
            name = "BPELauncher"
        else:
            name = "BPELauncher.exe"

        # PyInstaller 번들
        meipass = getattr(_sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / name
            if p.exists():
                return p
            # macOS .app 번들
            p = Path(_sys.executable).parent / name
            if p.exists():
                return p

        # 개발 모드: 프로젝트 루트의 launcher-dl/
        dev_path = Path(__file__).resolve().parent.parent.parent.parent / "launcher-dl" / name
        if dev_path.exists():
            return dev_path

        return None

    def _get_app_path(self) -> str:
        """현재 앱의 실행 경로를 반환한다."""
        import sys as _sys

        if _sys.platform == "darwin":
            exe = Path(_sys.executable)
            for parent in exe.parents:
                if parent.suffix == ".app":
                    return str(parent)
            return str(exe)
        else:
            return _sys.executable

    def _on_open_folder(self, path: str) -> None:
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast.reposition()

    def _build_tabs(self) -> None:
        from bpe.gui.tabs.my_tasks_tab import MyTasksTab
        from bpe.gui.tabs.preset_tab import PresetTab
        from bpe.gui.tabs.publish_tab import PublishTab
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab
        from bpe.gui.tabs.tools_tab import ToolsTab

        for key, cls in {
            "presets": PresetTab,
            "shot_builder": ShotBuilderTab,
            "my_tasks": MyTasksTab,
            "publish": PublishTab,
            "tools": ToolsTab,
        }.items():
            page = cls()
            self._tab_pages[key] = page
            self._stack.addWidget(page)

    def _switch_tab(self, key: str) -> None:
        page = self._tab_pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        for k, btn in self._tab_buttons.items():
            btn.setProperty("selected", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
