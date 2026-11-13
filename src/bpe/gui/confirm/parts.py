"""컨펌 창의 작은 부품 — 번호 붙은 묶음 칸 버튼, 도구 띠의 손잡이 점."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QPushButton, QWidget

from bpe.gui.confirm import style

_PAD = 11  # 테두리 1 + 안쪽 여백 10
_KEY_GAP = 6
_DISABLED = "#6a6a6a"


class KeyButton(QPushButton):
    """「1 원본」처럼 번호(폭 고른 굵은 글씨)와 이름이 나란한 버튼.

    바탕·테두리는 평소 버튼 스타일이 그리고, 글자만 여기서 두 가지 글씨체로 그린다.
    """

    def __init__(self, key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._label = ""
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_label(self, text: str) -> None:
        if text != self._label:
            self._label = text
            self.updateGeometry()
            self.update()

    def label(self) -> str:
        return self._label

    def key(self) -> str:
        return self._key

    def _key_font(self) -> QFont:
        f = QFont()
        f.setFamilies(list(style.MONO_FAMILIES))
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(style.FONT_PX)
        f.setBold(True)
        return f

    def _label_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(style.FONT_PX)
        f.setBold(False)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        self.ensurePolished()
        key_w = QFontMetrics(self._key_font()).horizontalAdvance(self._key)
        label_w = QFontMetrics(self._label_font()).horizontalAdvance(self._label)
        return QSize(_PAD * 2 + key_w + _KEY_GAP + label_w, style.CONTROL_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        if not self.isEnabled():
            color = _DISABLED
        elif self.isChecked():
            color = style.TEXT_STRONG
        else:
            color = style.TEXT
        p.setPen(QColor(color))
        flags = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        key_font = self._key_font()
        p.setFont(key_font)
        key_w = QFontMetrics(key_font).horizontalAdvance(self._key)
        p.drawText(QRect(_PAD, 0, key_w + 2, self.height()), flags, self._key)
        p.setFont(self._label_font())
        x = _PAD + key_w + _KEY_GAP
        p.drawText(QRect(x, 0, self.width() - x, self.height()), flags, self._label)
        p.end()


class Grip(QWidget):
    """도구 띠 왼쪽의 손잡이 점(두 줄)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 18)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        color = QColor(style.TICK)
        for x in (2, 6):
            for y in range(0, 18, 4):
                p.fillRect(x, y, 2, 2, color)
        p.end()
