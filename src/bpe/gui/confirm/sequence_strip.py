"""컨펌 창 「이어 재생」의 컷 띠 — 컷마다 한 칸(이름·경계·올라온 만큼), 지금 자리, 눌러서 옮기기."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from bpe.core.confirm_sequence import cut_starts, locate, total_frames
from bpe.gui.confirm import style

_HEIGHT = 30
_BAR_H = 3
_NAME_PAD = 6


class _Canvas(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.names: List[str] = []
        self.counts: List[int] = []
        self.cached: List[int] = []
        self.at = 0

    def _total(self) -> int:
        return total_frames(self.counts)

    def pos_at(self, x: float) -> int:
        total = self._total()
        if total <= 0 or self.width() <= 0:
            return 0
        return max(0, min(total - 1, int(x / self.width() * total)))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(style.HEADER))
        total = self._total()
        if total <= 0:
            p.end()
            return
        per = self.width() / total
        current, _frame = locate(self.counts, self.at)
        font = QFont(self.font())
        font.setPixelSize(style.FONT_SMALL_PX)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i, start in enumerate(cut_starts(self.counts)):
            n = self.counts[i]
            if n <= 0:
                continue
            box = QRectF(start * per, 0, n * per, _HEIGHT)
            if i == current:
                p.fillRect(box, QColor(style.RAISED))
            # 컷 경계
            p.fillRect(QRectF(box.left(), 0, 1, _HEIGHT), QColor("#000000"))
            # 메모리에 올라온 만큼
            done = min(n, self.cached[i] if i < len(self.cached) else 0)
            p.fillRect(
                QRectF(box.left() + 1, _HEIGHT - _BAR_H, box.width() - 1, _BAR_H),
                QColor(style.CELL_EDGE),
            )
            if done:
                p.fillRect(
                    QRectF(box.left() + 1, _HEIGHT - _BAR_H, (box.width() - 1) * done / n, _BAR_H),
                    QColor(style.CACHE),
                )
            name = self.names[i] if i < len(self.names) else ""
            room = box.width() - 2 * _NAME_PAD
            if name and room > 20:
                text = metrics.elidedText(name, Qt.TextElideMode.ElideLeft, room)
                p.setPen(QColor(style.TEXT_STRONG if i == current else style.DIM))
                p.drawText(QRectF(box.left() + _NAME_PAD, 0, room, _HEIGHT - _BAR_H), flags, text)
        # 지금 자리
        x = (self.at + 0.5) * per
        p.fillRect(QRectF(x - 1, 0, 2, _HEIGHT), QColor(style.ACCENT))
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._total() > 0:
            self.seek_requested.emit(self.pos_at(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._total() > 0:
            self.seek_requested.emit(self.pos_at(event.position().x()))


class SequenceStrip(QWidget):
    """이어 재생 중에 타임라인 위에 보이는 띠."""

    seek_requested = Signal(int)  # 한 줄 위의 자리(0부터)
    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("confirm_sequence_strip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#confirm_sequence_strip {{ background: {style.PANEL}; "
            f"border-top: 1px solid {style.EDGE}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(8)
        self._title = QLabel("이어 재생")
        self._title.setStyleSheet(f"color: {style.WARN}; font-weight: bold;")
        row.addWidget(self._title)
        self._canvas = _Canvas()
        self._canvas.seek_requested.connect(self.seek_requested)
        row.addWidget(self._canvas, 1)
        self._note = QLabel("")
        self._note.setStyleSheet(f"color: {style.DIM}; {style.mono(style.FONT_SMALL_PX)}")
        row.addWidget(self._note)
        self._close = QPushButton("닫기")
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.setToolTip("이어 재생을 끝내고 풀어 둔 그림을 내려놓습니다")
        self._close.clicked.connect(self.close_requested)
        row.addWidget(self._close)

    def set_cuts(self, names: List[str], counts: List[int]) -> None:
        self._canvas.names = list(names)
        self._canvas.counts = [max(0, int(c)) for c in counts]
        self._canvas.cached = [0] * len(counts)
        self._canvas.at = 0
        self._canvas.update()

    def set_counts(self, counts: List[int]) -> None:
        self._canvas.counts = [max(0, int(c)) for c in counts]
        self._canvas.update()

    def set_cached(self, cut: int, count: int) -> None:
        if 0 <= cut < len(self._canvas.cached):
            self._canvas.cached[cut] = int(count)
            self._canvas.update()

    def set_position(self, pos: int) -> None:
        if pos != self._canvas.at:
            self._canvas.at = int(pos)
            self._canvas.update()

    def position(self) -> int:
        return self._canvas.at

    def set_note(self, text: str) -> None:
        self._note.setText(text)

    def note(self) -> str:
        return self._note.text()

    def pos_at(self, x: float) -> int:
        return self._canvas.pos_at(x)

    def cut_names(self) -> List[str]:
        return list(self._canvas.names)
