"""Overlay toast widget for app update notifications."""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _State(Enum):
    NOTIFY = auto()
    DOWNLOADING = auto()
    DONE = auto()


class UpdateToast(QWidget):
    """MainWindow 우측 하단 오버레이 토스트."""

    install_requested = Signal()
    open_folder_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("update_toast")
        self.setFixedWidth(320)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._download_path = ""

        # --- widgets ---
        self._msg_label = QLabel()
        self._msg_label.setWordWrap(True)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)

        self._pct_label = QLabel("0 %")
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self._btn_primary = QPushButton()
        self._btn_primary.setProperty("primary", True)
        self._btn_secondary = QPushButton()

        # --- layout ---
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_secondary)
        btn_row.addWidget(self._btn_primary)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        root.addWidget(self._msg_label)
        root.addWidget(self._progress_bar)
        root.addWidget(self._pct_label)
        root.addLayout(btn_row)

        # --- connections ---
        self._btn_primary.clicked.connect(self._on_primary)
        self._btn_secondary.clicked.connect(self._on_secondary)

        self._state: Optional[_State] = None
        self.hide()

    # ── public API ──

    def show_update(self, version: str) -> None:
        self._msg_label.setText(f"v{version} 업데이트 가능")
        self._btn_primary.setText("Install")
        self._btn_secondary.setText("Later")
        self._set_state(_State.NOTIFY)

    def show_progress(self, value: int) -> None:
        if self._state != _State.DOWNLOADING:
            self._msg_label.setText("다운로드 중...")
            self._set_state(_State.DOWNLOADING)
        clamped = max(0, min(100, value))
        self._progress_bar.setValue(clamped)
        self._pct_label.setText(f"{clamped} %")

    def show_done(self, download_path: str) -> None:
        self._download_path = download_path
        self._msg_label.setText("다운로드 완료! 앱을 종료하고 새 버전을 실행하세요.")
        self._btn_primary.setText("폴더 열기")
        self._btn_secondary.setText("닫기")
        self._set_state(_State.DONE)

    def reposition(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        margin = 16
        x = p.width() - self.width() - margin
        y = p.height() - self.sizeHint().height() - margin
        self.move(x, y)

    # ── internal ──

    def _set_state(self, state: _State) -> None:
        self._state = state
        is_notify = state == _State.NOTIFY
        is_downloading = state == _State.DOWNLOADING
        is_done = state == _State.DONE

        self._progress_bar.setVisible(is_downloading)
        self._pct_label.setVisible(is_downloading)
        self._btn_primary.setVisible(is_notify or is_done)
        self._btn_secondary.setVisible(is_notify or is_done)

        self.show()
        self.raise_()
        self.adjustSize()
        self.reposition()

    def _on_primary(self) -> None:
        if self._state == _State.NOTIFY:
            self.install_requested.emit()
        elif self._state == _State.DONE:
            self.open_folder_requested.emit(self._download_path)

    def _on_secondary(self) -> None:
        self.hide()
