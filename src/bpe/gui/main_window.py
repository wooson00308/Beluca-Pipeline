"""Main window — sidebar navigation + stacked tab pages."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.gui import theme


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
        self.setWindowTitle("BPE v0.2.0")
        self.setMinimumSize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
        self.resize(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT)

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
            btn.clicked.connect(
                lambda checked=False, k=tab_def["key"]: self._switch_tab(k)
            )
            sb.addWidget(btn)
            self._tab_buttons[tab_def["key"]] = btn

        sb.addStretch()

        # Version at bottom
        ver = QLabel("BPE v0.2.0")
        ver.setObjectName("sidebar_version")
        ver.setContentsMargins(20, 0, 0, 16)
        sb.addWidget(ver)

        root.addWidget(sidebar)

        # ── Content area ──
        self._stack = QStackedWidget()
        self._tab_pages: Dict[str, QWidget] = {}
        self._build_tabs()
        root.addWidget(self._stack, 1)

        self._switch_tab("presets")

    def _build_tabs(self) -> None:
        from bpe.gui.tabs.preset_tab import PresetTab
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab
        from bpe.gui.tabs.my_tasks_tab import MyTasksTab
        from bpe.gui.tabs.publish_tab import PublishTab
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
