"""Main window — sidebar navigation + stacked tab pages."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QDesktopServices, Qt, QUrl
from PySide6.QtWidgets import (
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

        from bpe.gui.workers.update_worker import UpdateDownloadWorker

        if sys.platform == "darwin":
            filename = "BPE-macOS.dmg"
        else:
            filename = "BPE-Windows.zip"
        dest = Path.home() / "Downloads" / filename

        w = UpdateDownloadWorker(info.download_url, str(dest))
        w.progress.connect(lambda v: self._toast.show_progress(int(v * 100)))
        w.finished.connect(lambda p: self._toast.show_done(p))
        w.error.connect(lambda e: logger.warning("Download error: %s", e))
        w.start()
        self._workers.append(w)

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
