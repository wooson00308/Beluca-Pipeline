"""Small pixmap icons for Feedback tab annotation toolbar (PySide6, gui-only)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def _pen_like(color: QColor, px: int) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(1.25, px / 14.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def make_move_pan_icon(px: int, color: QColor) -> QIcon:
    """Four-way move / pan (cross with arrowheads)."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = _pen_like(color, px)
    p.setPen(pen)
    cx, cy = px // 2, px // 2
    arm = px * 5 // 16
    ah = max(2, px // 10)
    # vertical
    p.drawLine(cx, cy - arm, cx, cy + arm)
    p.drawLine(cx, cy - arm, cx - ah, cy - arm + ah)
    p.drawLine(cx, cy - arm, cx + ah, cy - arm + ah)
    p.drawLine(cx, cy + arm, cx - ah, cy + arm - ah)
    p.drawLine(cx, cy + arm, cx + ah, cy + arm - ah)
    # horizontal
    p.drawLine(cx - arm, cy, cx + arm, cy)
    p.drawLine(cx - arm, cy, cx - arm + ah, cy - ah)
    p.drawLine(cx - arm, cy, cx - arm + ah, cy + ah)
    p.drawLine(cx + arm, cy, cx + arm - ah, cy - ah)
    p.drawLine(cx + arm, cy, cx + arm - ah, cy + ah)
    p.end()
    return QIcon(pm)


def make_select_cursor_icon(px: int, color: QColor) -> QIcon:
    """Alias for move/pan (backward compat)."""
    return make_move_pan_icon(px, color)


def make_pen_icon(px: int, color: QColor) -> QIcon:
    """Diagonal pencil silhouette (reference: flat gray pencil)."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    body = QColor(color)
    body.setAlpha(230)
    dim = QColor(color)
    dim.setAlpha(140)
    tip = QPointF(px * 4 / 16, px * 13 / 16)
    eraser = QPointF(px * 12 / 16, px * 3 / 16)
    mid = QPointF(px * 7 / 16, px * 10 / 16)
    p.setPen(_pen_like(body, px))
    p.drawLine(eraser, mid)
    p.setPen(_pen_like(dim, px))
    p.drawLine(mid, tip)
    p.end()
    return QIcon(pm)


def make_arrow_tool_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(_pen_like(color, px))
    p.drawLine(px * 3 // 16, px * 13 // 16, px * 12 // 16, px * 4 // 16)
    p.drawLine(px * 12 // 16, px * 4 // 16, px * 9 // 16, px * 4 // 16)
    p.drawLine(px * 12 // 16, px * 4 // 16, px * 12 // 16, px * 7 // 16)
    p.end()
    return QIcon(pm)


def make_rect_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = _pen_like(color, px)
    p.setPen(pen)
    inset = max(3, px // 5)
    p.drawRect(inset, inset, px - 2 * inset, px - 2 * inset)
    p.end()
    return QIcon(pm)


def make_ellipse_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(_pen_like(color, px))
    inset = max(3, px // 5)
    p.drawEllipse(inset, inset, px - 2 * inset, px - 2 * inset)
    p.end()
    return QIcon(pm)


def make_text_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(_pen_like(color, px))
    p.drawLine(px * 6 // 16, px * 3 // 16, px * 6 // 16, px * 13 // 16)
    p.drawLine(px * 4 // 16, px * 3 // 16, px * 10 // 16, px * 3 // 16)
    p.drawLine(px * 4 // 16, px * 8 // 16, px * 9 // 16, px * 8 // 16)
    p.end()
    return QIcon(pm)


def make_loop_icon(px: int, color: QColor) -> QIcon:
    """Rounded rectangle with two arrows (loop)."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(_pen_like(color, px))
    inset = max(2, px // 8)
    rw = px - 2 * inset
    rh = px - 2 * inset
    p.drawRoundedRect(inset, inset, rw, rh, px // 6, px // 6)
    # top arrow head → right
    p.drawLine(px * 11 // 16, inset + 1, px * 13 // 16, inset + rh // 3)
    p.drawLine(px * 11 // 16, inset + 1, px * 9 // 16, inset + rh // 3)
    # bottom arrow head ← left
    p.drawLine(px * 5 // 16, inset + rh - 1, px * 3 // 16, inset + rh * 2 // 3)
    p.drawLine(px * 5 // 16, inset + rh - 1, px * 7 // 16, inset + rh * 2 // 3)
    p.end()
    return QIcon(pm)


def make_media_play_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    ax, ay = px // 4, px // 4
    bw, bh = px - 2 * ax, px - 2 * ay
    p.drawPolygon(
        [
            QPointF(ax, ay),
            QPointF(ax + bw, ay + bh / 2),
            QPointF(ax, ay + bh),
        ]
    )
    p.end()
    return QIcon(pm)


def make_media_pause_icon(px: int, color: QColor) -> QIcon:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    gap = max(2, px // 10)
    bar = max(3, px // 5)
    x0 = px // 2 - gap // 2 - bar
    p.drawRect(x0, px * 3 // 10, bar, px * 4 // 10)
    p.drawRect(x0 + bar + gap, px * 3 // 10, bar, px * 4 // 10)
    p.end()
    return QIcon(pm)
