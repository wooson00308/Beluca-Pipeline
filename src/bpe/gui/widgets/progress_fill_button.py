"""Push button with left-to-right fill ratio (ShotGrid publish–style progress)."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from bpe.gui import theme


class ProgressFillButton(QPushButton):
    """Flat button: dark track + teal fill; label centered on top."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fill_ratio = 0.0
        self.setFlat(True)

    def set_fill_ratio(self, ratio: float) -> None:
        self._fill_ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def fill_ratio(self) -> float:
        return self._fill_ratio

    def reset_progress_visual(self) -> None:
        self._fill_ratio = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        track = QColor(theme.INPUT_BG)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 6, 6)
        if self._fill_ratio > 0.001:
            fw = int(round(float(r.width()) * self._fill_ratio))
            fw = max(0, min(fw, r.width()))
            if fw > 0:
                fill_rect = QRect(r.left(), r.top(), fw, r.height())
                p.setBrush(QColor(theme.ACCENT))
                p.drawRoundedRect(fill_rect, 6, 6)
        p.setPen(QPen(QColor(theme.TEXT)))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()
