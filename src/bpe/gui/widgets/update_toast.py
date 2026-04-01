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
    READY = auto()
    ERROR = auto()
    DONE = auto()


class UpdateToast(QWidget):
    """MainWindow 우측 하단 오버레이 토스트."""

    install_requested = Signal()
    restart_requested = Signal()
    retry_requested = Signal()
    open_folder_requested = Signal(str)
    open_release_page_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("update_toast")
        self.setFixedWidth(320)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._download_path = ""
        self._html_url = ""

        # --- widgets ---
        self._msg_label = QLabel()
        self._msg_label.setWordWrap(True)

        self._notes_label = QLabel()
        self._notes_label.setWordWrap(True)
        self._notes_label.setObjectName("status_msg")
        self._notes_label.setVisible(False)

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
        root.addWidget(self._notes_label)
        root.addWidget(self._progress_bar)
        root.addWidget(self._pct_label)
        root.addLayout(btn_row)

        # --- connections ---
        self._btn_primary.clicked.connect(self._on_primary)
        self._btn_secondary.clicked.connect(self._on_secondary)

        self._state: Optional[_State] = None
        self.hide()

    # ── public API ──

    def show_update(self, version: str, release_notes: str = "") -> None:
        self._msg_label.setText(f"v{version} 업데이트 가능")
        if release_notes:
            lines = release_notes.strip().splitlines()[:2]
            self._notes_label.setText("\n".join(lines))
            self._notes_label.setVisible(True)
        else:
            self._notes_label.setVisible(False)
        self._btn_primary.setText("Install")
        self._btn_secondary.setText("Later")
        self._set_state(_State.NOTIFY)

    def show_progress(self, value: int) -> None:
        if self._state != _State.DOWNLOADING:
            self._msg_label.setText("다운로드 중...")
            self._notes_label.setVisible(False)
            self._set_state(_State.DOWNLOADING)
        clamped = max(0, min(100, value))
        self._progress_bar.setValue(clamped)
        self._pct_label.setText(f"{clamped} %")

    def show_ready(self, version: str) -> None:
        """다운로드+추출 성공 후 재시작 확인 상태."""
        self._msg_label.setText(f"v{version} 설치 준비 완료!\n재시작하면 새 버전이 적용됩니다.")
        self._notes_label.setVisible(False)
        self._btn_primary.setText("재시작")
        self._btn_secondary.setText("나중에")
        self._set_state(_State.READY)

    def show_error(self, msg: str, html_url: str = "") -> None:
        """다운로드/설치 실패 시 에러 표시."""
        self._html_url = html_url
        self._msg_label.setText(f"업데이트 실패\n{msg}")
        self._notes_label.setVisible(False)
        self._btn_primary.setText("다시 시도")
        if html_url:
            self._btn_secondary.setText("Release 페이지")
        else:
            self._btn_secondary.setText("닫기")
        self._set_state(_State.ERROR)

    def show_done(self, download_path: str) -> None:
        """macOS: DMG 다운로드 완료 후 폴더 열기."""
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
        is_downloading = state == _State.DOWNLOADING

        self._progress_bar.setVisible(is_downloading)
        self._pct_label.setVisible(is_downloading)
        self._btn_primary.setVisible(not is_downloading)
        self._btn_secondary.setVisible(not is_downloading)

        self.show()
        self.raise_()
        self.adjustSize()
        self.reposition()

    def _on_primary(self) -> None:
        if self._state == _State.NOTIFY:
            self.install_requested.emit()
        elif self._state == _State.READY:
            self.restart_requested.emit()
        elif self._state == _State.ERROR:
            self.retry_requested.emit()
        elif self._state == _State.DONE:
            self.open_folder_requested.emit(self._download_path)

    def _on_secondary(self) -> None:
        if self._state == _State.ERROR and self._html_url:
            self.open_release_page_requested.emit()
        else:
            self.hide()
