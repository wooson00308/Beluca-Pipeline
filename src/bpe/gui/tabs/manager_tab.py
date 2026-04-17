"""Manager tab — Preset + Feedback sub-pages behind the lock overlay."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.gui import theme


class ManagerTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from bpe.gui.tabs.feedback_tab import FeedbackTab
        from bpe.gui.tabs.preset_tab import PresetTab

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QHBoxLayout()
        nav.setContentsMargins(16, 12, 16, 8)
        nav.setSpacing(8)
        self._btn_preset = QPushButton("Preset")
        self._btn_feedback = QPushButton("Feedback")
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._btn_preset.setCheckable(True)
        self._btn_feedback.setCheckable(True)
        self._nav_group.addButton(self._btn_preset, 0)
        self._nav_group.addButton(self._btn_feedback, 1)
        for b in (self._btn_preset, self._btn_feedback):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(36)
        self._btn_preset.setChecked(True)
        self._nav_group.idClicked.connect(self._switch)
        nav.addWidget(self._btn_preset)
        nav.addWidget(self._btn_feedback)
        nav.addStretch()
        root.addLayout(nav)

        self._stack = QStackedWidget()
        self._stack.addWidget(PresetTab())
        self._stack.addWidget(FeedbackTab())
        root.addWidget(self._stack, 1)

        self._apply_nav_style()

    def _switch(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._btn_preset.setChecked(index == 0)
        self._btn_feedback.setChecked(index == 1)
        self._apply_nav_style()

    def _apply_nav_style(self) -> None:
        sel = f"background: {theme.ACCENT}; color: #fff; border-radius: 6px; padding: 8px 16px;"
        unsel = (
            f"background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px 16px;"
        )
        self._btn_preset.setStyleSheet(sel if self._btn_preset.isChecked() else unsel)
        self._btn_feedback.setStyleSheet(sel if self._btn_feedback.isChecked() else unsel)
