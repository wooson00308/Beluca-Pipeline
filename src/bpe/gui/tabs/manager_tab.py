# @cursor-change: 2026-05-15, 0.8.22, F5 시 Feedback에 trigger_refresh 위임
"""Manager tab — Preset + Feedback sub-pages behind the lock overlay."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.gui import theme

logger = get_logger("gui.manager_tab")


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
        # 새 컨펌 창(1단계: 화면 계산 시험). 기존 Feedback 페이지는 그대로 둔다.
        self._confirm_probe: Optional[Any] = None
        self._btn_confirm_probe = QPushButton("컨펌 창 (시험)")
        self._btn_confirm_probe.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_confirm_probe.setMinimumHeight(36)
        self._btn_confirm_probe.setToolTip("새 컨펌 창의 화면 계산이 이 PC 에서 되는지 확인합니다")
        self._btn_confirm_probe.clicked.connect(self._open_confirm_probe)
        nav.addWidget(self._btn_confirm_probe)
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
        self._btn_confirm_probe.setStyleSheet(unsel)

    def _open_confirm_probe(self) -> None:
        """컨펌 창 화면 계산 시험 창 — 독립 창. 이미 열려 있으면 앞으로 가져온다."""
        win = self._confirm_probe
        if win is not None and not win.is_closed() and win.isVisible():
            if win.isMinimized():
                win.setWindowState(
                    (win.windowState() & ~Qt.WindowState.WindowMinimized)
                    | Qt.WindowState.WindowActive
                )
            win.raise_()
            win.activateWindow()
            return
        try:
            # 화면 계산 부품(QtOpenGL)이 없는 환경에서도 BPE 자체는 뜨도록 여기서 import 한다.
            from bpe.gui.confirm.gl_probe_window import ConfirmGLProbeWindow

            win = ConfirmGLProbeWindow(None)
        except Exception as e:
            logger.exception("confirm probe window open failed")
            QMessageBox.warning(
                self,
                "컨펌 창 (시험)",
                f"화면 계산 시험 창을 열지 못했습니다.\n{type(e).__name__}: {e}",
            )
            return
        win.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        # 이 창이 남아 있어도 BPE 메인 창을 닫으면 앱이 종료되게 한다.
        win.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._confirm_probe = win
        win.show()

    def trigger_refresh(self) -> None:
        """F5: 활성 서브탭(피드백) 새로고침. Preset에는 위임 없음."""
        current = self._stack.currentWidget()
        rf = getattr(current, "trigger_refresh", None)
        if callable(rf):
            rf()
