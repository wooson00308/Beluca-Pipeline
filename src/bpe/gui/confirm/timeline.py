"""컨펌 창의 눈금 시간 막대 — 프레임 눈금, 메모리에 올라온 구간, 그림 남긴 프레임 표시."""

from __future__ import annotations

from typing import List, Optional, Set

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from bpe.gui import theme

_MARGIN = 26
_HEIGHT = 50
_BASE_Y = 30
_LABEL_MIN_GAP = 46
_CACHE_COLOR = "#4f9f6a"
_MARK_COLOR = "#ff5a52"
_TICK_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000)


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
        self._past_marks: List[int] = []

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

    def clear_cached(self) -> None:
        self._cached.clear()
        self.update()

    def set_marks(self, frames: List[int]) -> None:
        """그림을 남긴 화면 프레임 번호들."""
        self._marks = list(frames)
        self.update()

    def set_past_marks(self, frames: List[int]) -> None:
        self._past_marks = list(frames)
        self.update()

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
        p.fillRect(self.rect(), QColor(theme.PANEL_BG))
        if self._count <= 0:
            p.end()
            return
        per = (self.width() - 2 * _MARGIN) / self._count

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_CACHE_COLOR))
        for i in self._cached:
            x = _MARGIN + per * i
            p.drawRect(QRectF(x, 3, per + 0.6, 3))

        dim = QColor(theme.TEXT_DIM)
        p.setPen(QPen(dim, 1))
        p.drawLine(QPointF(_MARGIN, _BASE_Y), QPointF(self.width() - _MARGIN, _BASE_Y))
        step = self._label_step()
        font = QFont(self.font())
        font.setPixelSize(theme.FONT_SIZE_SMALL)
        p.setFont(font)
        draw_minor = per >= 4
        for i in range(self._count):
            frame = self._start + i
            major = frame % step == 0
            if not major and not draw_minor:
                continue
            x = self._x_of(i)
            p.setPen(QPen(QColor(theme.TEXT_LABEL) if major else dim, 1))
            p.drawLine(QPointF(x, _BASE_Y - (7 if major else 3)), QPointF(x, _BASE_Y))
            if major:
                p.drawText(
                    QRectF(x - 30, _BASE_Y + 2, 60, 14), Qt.AlignmentFlag.AlignCenter, str(frame)
                )

        p.setPen(Qt.PenStyle.NoPen)
        for frames, color in ((self._past_marks, "#f0c060"), (self._marks, _MARK_COLOR)):
            p.setBrush(QColor(color))
            for frame in frames:
                i = frame - self._start
                if 0 <= i < self._count:
                    x = self._x_of(i)
                    p.drawPolygon(
                        QPolygonF(
                            [
                                QPointF(x, _BASE_Y - 15),
                                QPointF(x + 5.5, _BASE_Y - 9.5),
                                QPointF(x, _BASE_Y - 4),
                                QPointF(x - 5.5, _BASE_Y - 9.5),
                            ]
                        )
                    )

        x = self._x_of(self._current)
        accent = QColor(theme.ACCENT)
        p.setPen(QPen(accent, 2))
        p.drawLine(QPointF(x, 8), QPointF(x, _BASE_Y + 1))
        label = str(self._start + self._current)
        flag = QRectF(x - 22, 8, 44, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRect(flag)
        bold = QFont(font)
        bold.setBold(True)
        p.setFont(bold)
        p.setPen(QColor("#ffffff"))
        p.drawText(flag, Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    # ── 마우스 ───────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._count > 0:
            self.frame_picked.emit(self.index_at(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._count > 0:
            self.frame_picked.emit(self.index_at(event.position().x()))
