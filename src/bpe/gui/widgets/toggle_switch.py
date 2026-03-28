"""클릭형 iOS 스타일 온/오프 토글 — paintEvent로 그려 플랫폼별 QSS 차이 없음."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from bpe.gui import theme

_W = 52
_H = 28
_HANDLE_R = 10
_MARGIN = 4


class ToggleSwitch(QAbstractButton):
    """체크 가능한 버튼; 클릭만으로 on/off. 드래그 슬라이더 아님."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(_W, _H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_W, _H)

    def paintEvent(self, event: object) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        track = QRectF(0.0, 0.0, w, h)
        track_color = QColor(theme.ACCENT) if self.isChecked() else QColor(theme.INPUT_BG)
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.setBrush(track_color)
        p.drawRoundedRect(track, h / 2.0, h / 2.0)

        cx = w - _MARGIN - _HANDLE_R if self.isChecked() else _MARGIN + _HANDLE_R
        cy = h / 2.0
        handle = QRectF(cx - _HANDLE_R, cy - _HANDLE_R, 2.0 * _HANDLE_R, 2.0 * _HANDLE_R)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawEllipse(handle)
