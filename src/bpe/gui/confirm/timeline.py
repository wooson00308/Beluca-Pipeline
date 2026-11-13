"""컨펌 창의 눈금 시간 막대 — 프레임 눈금, 메모리에 올라온 구간, 그림 남긴 프레임 표시."""

from __future__ import annotations

from typing import List, Optional, Set

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from bpe.gui.confirm import style

_MARGIN = 10
_FLAG_W = 42
_MARK_R = 4
_HEIGHT = 46
_BASE_Y = 30
_LABEL_MIN_GAP = 46
_TICK_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000)


def _mono_font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(list(style.MONO_FAMILIES))
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class ConfirmTimeline(QWidget):
    """프레임을 고르는 눈금 막대. 번호는 화면 프레임 번호(예: 1001~1074)로 보여 준다."""

    frame_picked = Signal(int)  # 0부터 세는 번호

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start = 1001
        self._count = 0
        self._current = 0
        self._cached: Set[int] = set()
        self._marks: List[int] = []

    def set_range(self, frame_start: int, count: int) -> None:
        self._start, self._count = int(frame_start), max(0, int(count))
        self._current = min(self._current, max(0, self._count - 1))
        self._cached = set()
        self.update()

    def set_current(self, index: int) -> None:
        if index != self._current:
            self._current = index
            self.update()

    def add_cached(self, index: int) -> None:
        self._cached.add(index)
        self.update()

    def set_marks(self, frames: List[int]) -> None:
        """그림을 남긴 화면 프레임 번호들."""
        self._marks = list(frames)
        self.update()

    def marks(self) -> List[int]:
        return list(self._marks)

    def count(self) -> int:
        return self._count

    # ── 좌표 ─────────────────────────────────────────────────────

    def _x_of(self, index: float) -> float:
        span = max(1, self._count)
        return _MARGIN + (self.width() - 2 * _MARGIN) * (index + 0.5) / span

    def index_at(self, x: float) -> int:
        span = max(1, self._count)
        t = (x - _MARGIN) / max(1.0, self.width() - 2 * _MARGIN)
        return max(0, min(span - 1, int(t * span)))

    def _label_step(self) -> int:
        per_frame = (self.width() - 2 * _MARGIN) / max(1, self._count)
        for step in _TICK_STEPS:
            if step * per_frame >= _LABEL_MIN_GAP:
                return step
        return _TICK_STEPS[-1]

    # ── 그리기 ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(style.PANEL))
        if self._count <= 0:
            p.end()
            return
        per = (self.width() - 2 * _MARGIN) / self._count

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(style.CURRENT_CELL))
        p.drawRect(QRectF(_MARGIN + per * self._current, 2, max(per, 2.0), _HEIGHT - 2))
        p.setBrush(QColor(style.CELL_EDGE))
        p.drawRect(QRectF(_MARGIN, 0, self.width() - 2 * _MARGIN, 2))
        p.setBrush(QColor(style.CACHE))
        for i in self._cached:
            p.drawRect(QRectF(_MARGIN + per * i, 0, per + 0.6, 2))

        dim = QColor(style.TICK)
        p.setPen(QPen(dim, 1))
        p.drawLine(QPointF(_MARGIN, _BASE_Y), QPointF(self.width() - _MARGIN, _BASE_Y))
        step = self._label_step()
        p.setFont(_mono_font(style.FONT_SMALL_PX))
        draw_minor = per >= 4
        for i in range(self._count):
            frame = self._start + i
            major = frame % step == 0
            if not major and not draw_minor:
                continue
            x = self._x_of(i)
            p.setPen(QPen(QColor(style.DIM) if major else dim, 1))
            p.drawLine(QPointF(x, _BASE_Y - (7 if major else 3)), QPointF(x, _BASE_Y))
            if major:
                p.drawText(
                    QRectF(x - 30, _BASE_Y + 1, 60, 14), Qt.AlignmentFlag.AlignCenter, str(frame)
                )

        x = self._x_of(self._current)
        accent = QColor(style.ACCENT)
        p.setPen(QPen(accent, 2))
        p.drawLine(QPointF(x, 6), QPointF(x, _BASE_Y + 1))
        flag_x = max(0.0, min(self.width() - _FLAG_W, x - _FLAG_W / 2))
        flag = QRectF(flag_x, 5, _FLAG_W, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRect(flag)
        p.setFont(_mono_font(style.FONT_SMALL_PX, bold=True))
        p.setPen(QColor(style.ON_ACCENT))
        p.drawText(flag, Qt.AlignmentFlag.AlignCenter, str(self._start + self._current))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(style.MARK))
        for frame in self._marks:
            i = frame - self._start
            if 0 <= i < self._count:
                mx = self._x_of(i)
                p.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(mx, _BASE_Y - 5 - _MARK_R),
                            QPointF(mx + _MARK_R, _BASE_Y - 5),
                            QPointF(mx, _BASE_Y - 5 + _MARK_R),
                            QPointF(mx - _MARK_R, _BASE_Y - 5),
                        ]
                    )
                )
        p.end()

    # ── 마우스 ───────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._count > 0:
            self.frame_picked.emit(self.index_at(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._count > 0:
            self.frame_picked.emit(self.index_at(event.position().x()))
