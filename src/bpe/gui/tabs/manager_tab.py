# @cursor-change: 2026-05-15, 0.8.22, F5 시 Feedback에 trigger_refresh 위임
"""Manager tab — 잠금 화면 뒤의 Preset 화면.

옛 Feedback 화면은 컨펌 전용 창으로 옮겨 가면서 메뉴에서 뺐다(2026-11-13).
``feedback_tab`` 모듈 자체는 남아 있다.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from bpe.core.logging import get_logger

logger = get_logger("gui.manager_tab")


class ManagerTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from bpe.gui.tabs.preset_tab import PresetTab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(PresetTab())
        root.addWidget(self._stack, 1)

    def trigger_refresh(self) -> None:
        """F5: 지금 보이는 화면이 새로고침을 받으면 넘긴다. Preset 에는 없다."""
        current = self._stack.currentWidget()
        rf = getattr(current, "trigger_refresh", None)
        if callable(rf):
            rf()
