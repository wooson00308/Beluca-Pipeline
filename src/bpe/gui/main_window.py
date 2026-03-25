"""Main window — sidebar navigation + stacked tab pages."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
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
        self.setWindowTitle("BPE — Beluca Pipeline Engine")
        self.setMinimumSize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
        self.resize(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 16, 0, 16)
        sidebar_layout.setSpacing(0)

        # Version label at top
        from PySide6.QtWidgets import QLabel

        ver_label = QLabel("BPE v0.2.0")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setProperty("dim", True)
        ver_label.setStyleSheet(f"font-size: {theme.FONT_SIZE_SMALL}px; padding: 8px;")
        sidebar_layout.addWidget(ver_label)
        sidebar_layout.addSpacing(12)

        # Tab buttons
        self._tab_buttons: Dict[str, QPushButton] = {}
        self._stack = QStackedWidget()

        for tab_def in TAB_DEFS:
            btn = QPushButton(tab_def["label"])
            btn.setProperty("selected", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=tab_def["key"]: self._switch_tab(k))
            sidebar_layout.addWidget(btn)
            self._tab_buttons[tab_def["key"]] = btn

        sidebar_layout.addStretch()
        root_layout.addWidget(self._sidebar)

        # Tab content
        self._tab_pages: Dict[str, QWidget] = {}
        self._build_tabs()
        root_layout.addWidget(self._stack, 1)

        # Select first tab
        self._switch_tab("presets")

    def _build_tabs(self) -> None:
        """Lazy-import and instantiate each tab page."""
        from bpe.gui.tabs.preset_tab import PresetTab
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab
        from bpe.gui.tabs.my_tasks_tab import MyTasksTab
        from bpe.gui.tabs.publish_tab import PublishTab
        from bpe.gui.tabs.tools_tab import ToolsTab

        tab_classes = {
            "presets": PresetTab,
            "shot_builder": ShotBuilderTab,
            "my_tasks": MyTasksTab,
            "publish": PublishTab,
            "tools": ToolsTab,
        }
        for key, cls in tab_classes.items():
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
