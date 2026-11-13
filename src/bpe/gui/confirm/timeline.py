"""컨펌 창의 눈금 시간 막대 — 프레임 눈금, 메모리에 올라온 구간, 그림 남긴 프레임 표시.

위에서부터: 지금 프레임 깃발 → 그림 남긴 프레임 마름모 → 눈금 → 밑줄(올라온 구간은 초록) → 번호.
"""

from __future__ import annotations

from typing import List, Optional, Set

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from bpe.gui.confirm import style

_MARGIN = 10
_HEIGHT = 50
_FLAG_W = 42
_FLAG_Y, _FLAG_H = 3, 14
_MARK_Y, _MARK_R = 23, 4
_BASE_Y, _BASE_H = 34, 2
_MAJOR_TICK, _MINOR_TICK = 6, 3
_LABEL_Y, _LABEL_H = 36, 14
_LABEL_MIN_GAP = 46
_END_LABEL_CLEAR = 40  # 양 끝 번호와 이만큼 가까운 눈금 번호는 건너뛴다
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

    def _span(self) -> float:
        return max(1.0, self.width() - 2.0 * _MARGIN)

    def _x_of(self, index: float) -> float:
        return _MARGIN + self._span() * (index + 0.5) / max(1, self._count)

    def index_at(self, x: float) -> int:
        n = max(1, self._count)
        return max(0, min(n - 1, int((x - _MARGIN) / self._span() * n)))

    def _label_step(self) -> int:
        per_frame = self._span() / max(1, self._count)
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
        p.fillRect(QRectF(0, 0, self.width(), 1), QColor(style.EDGE))
        if self._count <= 0:
            p.end()
            return
        per = self._span() / self._count
        last = self._count - 1
        accent = QColor(style.ACCENT)

        # 지금 프레임 칸
        p.fillRect(
            QRectF(_MARGIN + per * self._current, 1, max(per, 2.0), _HEIGHT - 1),
            QColor(style.CURRENT_CELL),
        )

        # 밑줄: 전체는 어둡게, 메모리에 올라온 구간은 초록
        p.fillRect(QRectF(_MARGIN, _BASE_Y, self._span(), _BASE_H), QColor(style.CELL_EDGE))
        cache = QColor(style.CACHE)
        for i in self._cached:
            p.fillRect(QRectF(_MARGIN + per * i, _BASE_Y, per + 0.6, _BASE_H), cache)

        # 눈금과 번호
        step = self._label_step()
        tick, label_color = QColor(style.TICK), QColor(style.DIM)
        p.setFont(_mono_font(style.FONT_SMALL_PX))
        x_first, x_last = self._x_of(0), self._x_of(last)
        draw_minor = per >= 4
        flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        for i in range(self._count):
            frame = self._start + i
            major = frame % step == 0 or i in (0, last)
            if not major and not draw_minor:
                continue
            x = self._x_of(i)
            p.setPen(QPen(label_color if major else tick, 1))
            p.drawLine(
                QPointF(x, _BASE_Y - (_MAJOR_TICK if major else _MINOR_TICK)), QPointF(x, _BASE_Y)
            )
            near_end = min(x - x_first, x_last - x) < _END_LABEL_CLEAR
            if major and i not in (0, last) and not near_end:
                p.drawText(QRectF(x - 30, _LABEL_Y, 60, _LABEL_H), flags, str(frame))
        p.setPen(label_color)
        left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.drawText(QRectF(_MARGIN, _LABEL_Y, 60, _LABEL_H), left, str(self._start))
        if last > 0:
            p.drawText(
                QRectF(self.width() - _MARGIN - 60, _LABEL_Y, 60, _LABEL_H),
                right,
                str(self._start + last),
            )

        # 지금 프레임: 깃발 + 밑줄까지 내려오는 기둥
        x = self._x_of(self._current)
        p.fillRect(
            QRectF(x - 1, _FLAG_Y + _FLAG_H, 2, _BASE_Y + _BASE_H - _FLAG_Y - _FLAG_H), accent
        )
        flag_x = max(0.0, min(self.width() - _FLAG_W, x - _FLAG_W / 2))
        flag = QRectF(flag_x, _FLAG_Y, _FLAG_W, _FLAG_H)
        p.fillRect(flag, accent)
        p.setFont(_mono_font(style.FONT_SMALL_PX, bold=True))
        p.setPen(QColor(style.ON_ACCENT))
        p.drawText(flag, int(Qt.AlignmentFlag.AlignCenter), str(self._start + self._current))

        # 그림 남긴 프레임
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(style.MARK))
        for frame in self._marks:
            i = frame - self._start
            if 0 <= i < self._count:
                mx = self._x_of(i)
                p.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(mx, _MARK_Y - _MARK_R),
                            QPointF(mx + _MARK_R, _MARK_Y),
                            QPointF(mx, _MARK_Y + _MARK_R),
                            QPointF(mx - _MARK_R, _MARK_Y),
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
