"""Preset Manager 잠금 오버레이 — 비밀번호 입력, 흔들기, 3회 실패 시 1분 쿨다운."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bpe.core.access import verify_preset_password
from bpe.gui import theme

_MAX_FAILS = 3
_COOLDOWN_SEC = 60
_SHAKE_OFFSETS = (0, 8, -8, 6, -6, 4, -4, 2, -2, 0)


class LockOverlay(QWidget):
    """Preset Manager 진입 전 비밀번호 잠금."""

    unlocked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("lock_overlay")
        self._fail_count = 0
        self._cooldown_remaining = 0
        self._cooldown_timer: Optional[QTimer] = None
        self._shake_timer: Optional[QTimer] = None
        self._shake_i = 0
        self._shake_row: QWidget
        self._pw: QLineEdit
        self._confirm_btn: QPushButton
        self._eye_btn: QPushButton
        self._error_lbl: QLabel
        self._cooldown_lbl: QLabel
        self._build_ui()

    def _build_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.CONTENT_MARGIN, 32, theme.CONTENT_MARGIN, 32)
        outer.addStretch(1)

        box = QWidget()
        box.setMaximumWidth(420)
        col = QVBoxLayout(box)
        col.setSpacing(12)
        col.setContentsMargins(0, 0, 0, 0)

        icon = QLabel("\U0001f512")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 32px; background: transparent; color: {theme.TEXT_DIM};")
        col.addWidget(icon)

        title = QLabel("Preset Manager")
        title.setObjectName("lock_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(title)

        hint = QLabel("관리자 전용 기능입니다.")
        hint.setObjectName("lock_hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        col.addWidget(hint)

        self._shake_row = QWidget()
        row = QHBoxLayout(self._shake_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._pw = QLineEdit()
        self._pw.setObjectName("lock_pw")
        self._pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw.setPlaceholderText("비밀번호")
        self._pw.returnPressed.connect(self._try_unlock)
        row.addWidget(self._pw, 1)

        self._eye_btn = QPushButton("표시")
        self._eye_btn.setFixedWidth(48)
        self._eye_btn.setToolTip("비밀번호 표시/숨김")
        self._eye_btn.setCheckable(True)
        self._eye_btn.toggled.connect(self._on_eye_toggled)
        row.addWidget(self._eye_btn)

        col.addWidget(self._shake_row)

        self._confirm_btn = QPushButton("확인")
        self._confirm_btn.setProperty("primary", True)
        self._confirm_btn.setFixedHeight(theme.BUTTON_HEIGHT)
        self._confirm_btn.clicked.connect(self._try_unlock)
        col.addWidget(self._confirm_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._error_lbl = QLabel("")
        self._error_lbl.setObjectName("lock_error")
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.setWordWrap(True)
        self._error_lbl.hide()
        col.addWidget(self._error_lbl)

        self._cooldown_lbl = QLabel("")
        self._cooldown_lbl.setObjectName("lock_cooldown")
        self._cooldown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cooldown_lbl.setWordWrap(True)
        self._cooldown_lbl.hide()
        col.addWidget(self._cooldown_lbl)

        outer.addWidget(box, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def _on_eye_toggled(self, checked: bool) -> None:
        if checked:
            self._pw.setEchoMode(QLineEdit.EchoMode.Normal)
            self._eye_btn.setText("숨김")
        else:
            self._pw.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye_btn.setText("표시")

    def _try_unlock(self) -> None:
        if self._cooldown_remaining > 0:
            return
        pw = self._pw.text()
        if verify_preset_password(pw):
            self._fail_count = 0
            self._error_lbl.hide()
            self._pw.clear()
            self.unlocked.emit()
            return

        self._fail_count += 1
        self._error_lbl.setText("비밀번호가 올바르지 않습니다.")
        self._error_lbl.show()
        self._pw.selectAll()
        self._shake()

        if self._fail_count >= _MAX_FAILS:
            self._start_cooldown()

    def _shake(self) -> None:
        self._shake_i = 0
        if self._shake_timer is None:
            self._shake_timer = QTimer(self)
            self._shake_timer.timeout.connect(self._shake_step)
        self._shake_timer.start(42)

    def _shake_step(self) -> None:
        if self._shake_i >= len(_SHAKE_OFFSETS):
            if self._shake_timer:
                self._shake_timer.stop()
            self._shake_row.setStyleSheet("background: transparent;")
            return
        px = _SHAKE_OFFSETS[self._shake_i]
        self._shake_row.setStyleSheet(f"background: transparent; margin-left: {px}px;")
        self._shake_i += 1

    def _start_cooldown(self) -> None:
        self._cooldown_remaining = _COOLDOWN_SEC
        self._pw.setEnabled(False)
        self._confirm_btn.setEnabled(False)
        self._eye_btn.setEnabled(False)
        self._error_lbl.hide()
        self._update_cooldown_label()
        self._cooldown_lbl.show()

        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.timeout.connect(self._on_cooldown_tick)
        self._cooldown_timer.start(1000)

    def _on_cooldown_tick(self) -> None:
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            if self._cooldown_timer is not None:
                self._cooldown_timer.stop()
                self._cooldown_timer = None
            self._fail_count = 0
            self._pw.setEnabled(True)
            self._confirm_btn.setEnabled(True)
            self._eye_btn.setEnabled(True)
            self._cooldown_lbl.hide()
            self._pw.clear()
            return
        self._update_cooldown_label()

    def _update_cooldown_label(self) -> None:
        m = self._cooldown_remaining // 60
        s = self._cooldown_remaining % 60
        self._cooldown_lbl.setText(f"잠시 후 다시 시도하세요 ({m:02d}:{s:02d} 남음)")
