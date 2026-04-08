"""Transparent overlay for drawing feedback annotations on top of video preview."""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QInputDialog, QWidget


class AnnotationTool(IntEnum):
    NONE = 0
    PEN = 1
    ARROW = 2
    RECT = 3
    ELLIPSE = 4
    TEXT = 5


class AnnotationOverlay(QWidget):
    """Mouse-driven shapes over a video frame. Disable tools to pass events through."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._tool = AnnotationTool.NONE
        self._color = QColor(255, 0, 0)
        self._pen_width = 3
        self._shapes: List[Dict[str, Any]] = []
        self._drawing = False
        self._start: Optional[QPoint] = None
        self._current_end: Optional[QPoint] = None
        self._pen_points: List[QPoint] = []
        self._set_pass_through(self._tool == AnnotationTool.NONE)

    def set_tool(self, tool: AnnotationTool) -> None:
        self._tool = tool
        self._set_pass_through(tool == AnnotationTool.NONE)
        self.update()

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def set_pen_width(self, width: int) -> None:
        self._pen_width = max(1, int(width))

    def clear_all(self) -> None:
        self._shapes.clear()
        self.changed.emit()
        self.update()

    def has_content(self) -> bool:
        return bool(self._shapes)

    def _set_pass_through(self, on: bool) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)

    def render_to_pixmap(self, size: Optional[QSize] = None) -> QPixmap:
        """Rasterize annotations at *size* (defaults to widget size)."""
        sz = size if size is not None else self.size()
        w, h = max(1, sz.width()), max(1, sz.height())
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_shapes(p, QRect(0, 0, w, h))
        p.end()
        return pm

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_shapes(p, self.rect())

        if self._drawing and self._start and self._current_end:
            pen = QPen(self._color, self._pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self._tool == AnnotationTool.PEN and self._pen_points:
                path = QPainterPath()
                path.moveTo(QPointF(self._pen_points[0]))
                for pt in self._pen_points[1:]:
                    path.lineTo(QPointF(pt))
                p.drawPath(path)
            elif self._tool == AnnotationTool.ARROW:
                self._draw_arrow(p, self._start, self._current_end)
            elif self._tool == AnnotationTool.RECT:
                r = QRect(self._start, self._current_end).normalized()
                p.drawRect(r)
            elif self._tool == AnnotationTool.ELLIPSE:
                r = QRect(self._start, self._current_end).normalized()
                p.drawEllipse(r)
        p.end()

    def _paint_shapes(self, p: QPainter, bounds: QRect) -> None:
        for sh in self._shapes:
            t = sh.get("type")
            col = sh.get("color", QColor(255, 0, 0))
            w = int(sh.get("width", 3))
            pen = QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if t == "pen":
                pts: List[QPoint] = sh.get("points") or []
                if len(pts) < 2:
                    continue
                path = QPainterPath()
                path.moveTo(QPointF(pts[0]))
                for pt in pts[1:]:
                    path.lineTo(QPointF(pt))
                p.drawPath(path)
            elif t == "arrow":
                a, b = sh.get("a"), sh.get("b")
                if isinstance(a, QPoint) and isinstance(b, QPoint):
                    self._draw_arrow(p, a, b)
            elif t == "rect":
                r = sh.get("rect")
                if isinstance(r, QRect):
                    p.drawRect(r)
            elif t == "ellipse":
                r = sh.get("rect")
                if isinstance(r, QRect):
                    p.drawEllipse(r)
            elif t == "text":
                pos = sh.get("pos")
                txt = (sh.get("text") or "").strip()
                if isinstance(pos, QPoint) and txt:
                    p.drawText(pos, txt)

    def _draw_arrow(self, p: QPainter, a: QPoint, b: QPoint) -> None:
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        head = 14.0
        spread = math.pi / 7.0
        for sign in (-1.0, 1.0):
            t = ang + math.pi + sign * spread
            hx = b.x() + head * math.cos(t)
            hy = b.y() + head * math.sin(t)
            p.drawLine(b, QPoint(int(hx), int(hy)))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._tool == AnnotationTool.NONE or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._drawing = True
        self._start = event.position().toPoint()
        self._current_end = self._start
        if self._tool == AnnotationTool.PEN:
            self._pen_points = [self._start]
        elif self._tool == AnnotationTool.TEXT:
            self._drawing = False
            txt, ok = QInputDialog.getText(self, "텍스트", "표시할 텍스트:")
            if ok and txt.strip():
                self._shapes.append(
                    {
                        "type": "text",
                        "pos": self._start,
                        "text": txt.strip(),
                        "color": QColor(self._color),
                        "width": self._pen_width,
                    }
                )
                self.changed.emit()
            self._start = None
            self.update()
            return
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._drawing or self._start is None:
            return super().mouseMoveEvent(event)
        self._current_end = event.position().toPoint()
        if self._tool == AnnotationTool.PEN and self._pen_points:
            self._pen_points.append(self._current_end)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._drawing or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        end = event.position().toPoint()
        self._drawing = False
        if self._start is None:
            return
        col = QColor(self._color)
        w = self._pen_width
        if self._tool == AnnotationTool.PEN and len(self._pen_points) > 1:
            self._shapes.append(
                {"type": "pen", "points": list(self._pen_points), "color": col, "width": w}
            )
            self.changed.emit()
        elif self._tool == AnnotationTool.ARROW:
            self._shapes.append(
                {
                    "type": "arrow",
                    "a": QPoint(self._start),
                    "b": QPoint(end),
                    "color": col,
                    "width": w,
                }
            )
            self.changed.emit()
        elif self._tool == AnnotationTool.RECT:
            r = QRect(self._start, end).normalized()
            if r.width() >= 2 or r.height() >= 2:
                self._shapes.append({"type": "rect", "rect": r, "color": col, "width": w})
                self.changed.emit()
        elif self._tool == AnnotationTool.ELLIPSE:
            r = QRect(self._start, end).normalized()
            if r.width() >= 2 or r.height() >= 2:
                self._shapes.append({"type": "ellipse", "rect": r, "color": col, "width": w})
                self.changed.emit()
        self._start = None
        self._current_end = None
        self._pen_points = []
        self.update()
