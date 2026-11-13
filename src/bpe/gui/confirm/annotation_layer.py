"""컨펌 뷰어 위에 얹는 그리기 층 — 네모·펜·화살표·글씨, 고르기·옮기기·고치기·지우기.

도형 좌표는 영상 기준 0~1 (``bpe.core.confirm_annotations``). 화면에는 뷰어가 알려 주는
그림 사각형에 맞춰 그리므로, 확대·창 크기를 바꿔도 그림이 영상에 붙어 있다.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QLineEdit, QWidget

from bpe.core.confirm_annotations import (
    BOX_KINDS,
    DEFAULT_COLOR,
    DEFAULT_TEXT_SIZE,
    DEFAULT_WIDTH,
    KIND_ARROW,
    KIND_ELLIPSE,
    KIND_PEN,
    KIND_RECT,
    KIND_TEXT,
    AnnotationDoc,
    Shape,
    make_shape,
    shape_bounds,
    text_anchor,
)
from bpe.gui.confirm import style
from bpe.gui.confirm.viewer_gl import ConfirmGLView

TOOL_SELECT = "select"
TOOL_RECT = KIND_RECT
TOOL_ELLIPSE = KIND_ELLIPSE
TOOL_PEN = KIND_PEN
TOOL_ARROW = KIND_ARROW
TOOL_TEXT = KIND_TEXT
TOOLS = (TOOL_SELECT, TOOL_RECT, TOOL_ELLIPSE, TOOL_PEN, TOOL_ARROW, TOOL_TEXT)

_MIN_DRAG = 0.008
_PEN_STEP = 0.003
_GHOST_COLOR = "#f0c060"
Rect = Tuple[float, float, float, float]


def _to_px(rect: Rect, x: float, y: float) -> QPointF:
    return QPointF(rect[0] + x * rect[2], rect[1] + y * rect[3])


def paint_shapes(
    p: QPainter,
    shapes: List[Shape],
    rect: Rect,
    *,
    selected_id: Optional[int] = None,
    ghost: bool = False,
    skip_text_id: Optional[int] = None,
) -> None:
    """*rect*(그림이 놓인 사각형)에 맞춰 도형을 그린다. 화면과 노트 그림이 같이 쓴다."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = rect[3] / 1080.0 if rect[3] > 0 else 1.0
    for s in shapes:
        color = QColor(_GHOST_COLOR if ghost else s.get("color") or DEFAULT_COLOR)
        width = max(1.5, float(s.get("width") or DEFAULT_WIDTH) * max(scale, 0.6))
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if ghost:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pts = [_to_px(rect, x, y) for x, y in s.get("points") or []]
        kind = s.get("kind")
        if kind == KIND_RECT and len(pts) >= 2:
            p.drawRect(QRectF(pts[0], pts[1]).normalized())
        elif kind == KIND_ELLIPSE and len(pts) >= 2:
            p.drawEllipse(QRectF(pts[0], pts[1]).normalized())
        elif kind == KIND_PEN and len(pts) >= 2:
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            p.drawPath(path)
        elif kind == KIND_ARROW and len(pts) >= 2:
            a, b = pts[0], pts[1]
            p.drawLine(a, b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = max(10.0, width * 4.5)
            p.setBrush(color)
            p.drawPolygon(
                QPolygonF(
                    [
                        b,
                        QPointF(
                            b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45)
                        ),
                        QPointF(
                            b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45)
                        ),
                    ]
                )
            )
        text = (s.get("text") or "").strip()
        if text and s.get("id") != skip_text_id:
            _paint_text(p, s, rect, text, color)
        if selected_id is not None and s.get("id") == selected_id:
            x0, y0, x1, y1 = shape_bounds(s)
            sel = QPen(QColor("#ffffff"), 1, Qt.PenStyle.DotLine)
            p.setPen(sel)
            p.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(_to_px(rect, x0, y0), _to_px(rect, x1, y1)).normalized()
            p.drawRect(box.adjusted(-6, -6, 6, 6))


def text_font(shape: Shape, rect: Rect) -> QFont:
    f = QFont()
    f.setBold(True)
    f.setPixelSize(
        max(11, int(round(float(shape.get("text_size") or DEFAULT_TEXT_SIZE) * rect[3])))
    )
    return f


def text_origin(shape: Shape, rect: Rect) -> QPointF:
    ax, ay = text_anchor(shape)
    pt = _to_px(rect, ax, ay)
    if shape.get("kind") != KIND_TEXT:
        pt += QPointF(0, 6)
    return pt


def _paint_text(p: QPainter, shape: Shape, rect: Rect, text: str, color: QColor) -> None:
    font = text_font(shape, rect)
    p.setFont(font)
    fm = QFontMetricsF(font)
    origin = text_origin(shape, rect)
    box = QRectF(origin.x(), origin.y(), fm.horizontalAdvance(text) + 14, fm.height() + 6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 190))
    p.drawRect(box)
    p.setPen(color)
    p.drawText(box.adjusted(7, 3, -7, -3), Qt.AlignmentFlag.AlignVCenter, text)


class AnnotationLayer(QWidget):
    """뷰어를 덮는 투명한 그리기 층. 자기가 쓰지 않는 마우스 동작은 뷰어로 넘긴다."""

    doc_changed = Signal()
    selection_changed = Signal()

    def __init__(self, view: ConfirmGLView) -> None:
        super().__init__(view)
        self._view = view
        self._doc = AnnotationDoc()
        self._frame = 0
        self._tool = TOOL_SELECT
        self._color = DEFAULT_COLOR
        self._width = DEFAULT_WIDTH
        self._selected: Optional[int] = None
        self._ghosts: List[Shape] = []
        self._draft: Optional[Shape] = None
        self._drag_last: Optional[Tuple[float, float]] = None
        self._editing_id: Optional[int] = None
        self._editing_new = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("지적 내용을 쓰고 Enter")
        self._edit.hide()
        self._edit.returnPressed.connect(self._commit_edit)
        self._edit.editingFinished.connect(self._commit_edit)
        view.view_changed.connect(self._on_view_changed)
        self.setGeometry(view.rect())

    # ── 바깥에서 쓰는 것 ─────────────────────────────────────────

    def doc(self) -> AnnotationDoc:
        return self._doc

    def set_doc(self, doc: AnnotationDoc) -> None:
        self._cancel_edit()
        self._doc = doc
        self._selected = None
        self.update()

    def set_frame(self, frame: int) -> None:
        if frame != self._frame:
            self._cancel_edit()
            self._frame = frame
            if self._selected is not None:
                s = self._doc.get(self._selected)
                if s is None or not (s["frame"] <= frame <= s["frame_end"]):
                    self._selected = None
                    self.selection_changed.emit()
            self.update()

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        self._tool = tool if tool in TOOLS else TOOL_SELECT
        self._draft = None
        cross = self._tool != TOOL_SELECT
        self.setCursor(Qt.CursorShape.CrossCursor if cross else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        if self._selected is not None and self._doc.update(self._selected, color=color):
            self._changed()

    def set_ghosts(self, shapes: List[Shape]) -> None:
        """지난 지적 그림(노란 점선) — 고칠 수 없다."""
        self._ghosts = list(shapes)
        self.update()

    def selected_id(self) -> Optional[int]:
        return self._selected

    def is_editing_text(self) -> bool:
        return self._edit.isVisible()

    def delete_selected(self) -> bool:
        if self._selected is None or not self._doc.remove(self._selected):
            return False
        self._selected = None
        self.selection_changed.emit()
        self._changed()
        return True

    def undo(self) -> None:
        self._cancel_edit()
        if self._doc.undo():
            self._selected = None
            self._changed()

    def redo(self) -> None:
        self._cancel_edit()
        if self._doc.redo():
            self._selected = None
            self._changed()

    def extend_selected_to(self, frame_end: int) -> bool:
        """고른 그림을 *frame_end* 까지 이어지는 구간 지적으로 바꾼다."""
        s = self._doc.get(self._selected) if self._selected is not None else None
        if s is None or frame_end < s["frame"]:
            return False
        self._doc.update(s["id"], frame_end=int(frame_end))
        self._changed()
        return True

    # ── 좌표 ─────────────────────────────────────────────────────

    def _rect(self) -> Optional[Rect]:
        return self._view.image_rect()

    def _norm(self, pos: QPointF, clamp: bool = True) -> Optional[Tuple[float, float]]:
        rect = self._rect()
        if rect is None or rect[2] <= 0 or rect[3] <= 0:
            return None
        x, y = (pos.x() - rect[0]) / rect[2], (pos.y() - rect[1]) / rect[3]
        if clamp:
            return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))
        return (x, y) if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 else None

    def _on_view_changed(self) -> None:
        self.setGeometry(self._view.rect())
        self._place_edit()
        self.update()

    # ── 그리기 ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        rect = self._rect()
        if rect is None:
            return
        p = QPainter(self)
        if self._ghosts:
            paint_shapes(
                p, [g for g in self._ghosts if g["frame"] == self._frame], rect, ghost=True
            )
        paint_shapes(
            p,
            self._doc.shapes_at(self._frame),
            rect,
            selected_id=self._selected,
            skip_text_id=self._editing_id if self._edit.isVisible() else None,
        )
        if self._draft is not None:
            paint_shapes(p, [self._draft], rect)
        p.end()

    # ── 마우스 ───────────────────────────────────────────────────

    def _passes_to_view(self, event: QMouseEvent) -> bool:
        mods = event.modifiers()
        return event.button() == Qt.MouseButton.MiddleButton or bool(
            mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier)
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._passes_to_view(event) or event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._edit.isVisible():
            self._commit_edit()
        n = self._norm(event.position(), clamp=False)
        if n is None:
            event.ignore()
            return
        if self._tool == TOOL_SELECT:
            hit = self._doc.hit_test(self._frame, n[0], n[1])
            if hit != self._selected:
                self._selected = hit
                self.selection_changed.emit()
            if hit is not None:
                self._doc.begin_edit()
                self._drag_last = n
            self.update()
            event.accept() if hit is not None else event.ignore()
            return
        if self._tool == TOOL_TEXT:
            shape = make_shape(KIND_TEXT, self._frame, [n], color=self._color, width=self._width)
            self._begin_edit(self._doc.add(shape), is_new=True)
            self._changed()
            event.accept()
            return
        self._draft = make_shape(
            self._tool, self._frame, [n, n], color=self._color, width=self._width
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        n = self._norm(event.position())
        if n is not None and self._draft is not None:
            pts = self._draft["points"]
            if self._draft["kind"] == KIND_PEN:
                last = pts[-1]
                if abs(n[0] - last[0]) + abs(n[1] - last[1]) >= _PEN_STEP:
                    pts.append(n)
            else:
                pts[1] = n
            self.update()
            event.accept()
            return
        if n is not None and self._drag_last is not None and self._selected is not None:
            dx, dy = n[0] - self._drag_last[0], n[1] - self._drag_last[1]
            self._doc.move(self._selected, dx, dy, snapshot=False)
            self._drag_last = n
            self.update()
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_last is not None:
            self._drag_last = None
            self._changed()
            event.accept()
            return
        draft = self._draft
        if draft is None:
            event.ignore()
            return
        self._draft = None
        x0, y0, x1, y1 = shape_bounds(draft)
        if (x1 - x0) + (y1 - y0) < _MIN_DRAG:
            self.update()
            return
        if draft["kind"] in BOX_KINDS:
            draft["points"] = [(x0, y0), (x1, y1)]
        new_id = self._doc.add(draft)
        self._selected = new_id
        self.selection_changed.emit()
        self._changed()
        if draft["kind"] in BOX_KINDS or draft["kind"] == KIND_ARROW:
            self._begin_edit(new_id, is_new=False)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        n = self._norm(event.position(), clamp=False)
        hit = self._doc.hit_test(self._frame, n[0], n[1]) if n else None
        if hit is not None:
            self._selected = hit
            self._begin_edit(hit, is_new=False)
            event.accept()
            return
        event.ignore()

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        event.ignore()

    # ── 글 넣기 ──────────────────────────────────────────────────

    def _begin_edit(self, shape_id: int, *, is_new: bool) -> None:
        s = self._doc.get(shape_id)
        if s is None:
            return
        self._editing_id = shape_id
        self._editing_new = is_new
        self._edit.blockSignals(True)
        self._edit.setText(s.get("text") or "")
        self._edit.blockSignals(False)
        self._place_edit()
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()
        self.update()

    def _place_edit(self) -> None:
        rect = self._rect()
        s = self._doc.get(self._editing_id) if self._editing_id is not None else None
        if rect is None or s is None:
            return
        font = text_font(s, rect)
        self._edit.setFont(font)
        origin = text_origin(s, rect)
        w, h = 320, QFontMetricsF(font).height() + 10
        x = max(4.0, min(self.width() - w - 4.0, origin.x()))
        y = max(4.0, min(self.height() - h - 4.0, origin.y()))
        self._edit.setGeometry(int(x), int(y), int(w), int(h))
        self._edit.setStyleSheet(
            f"background: {style.FIELD}; color: {s.get('color') or DEFAULT_COLOR}; "
            f"border: 1px solid {s.get('color') or DEFAULT_COLOR}; "
            f"border-radius: {style.RADIUS}px; padding: 0 6px;"
        )

    def _commit_edit(self) -> None:
        if self._editing_id is None:
            return
        shape_id, is_new = self._editing_id, self._editing_new
        self._editing_id = None
        text = self._edit.text().strip()
        self._edit.hide()
        s = self._doc.get(shape_id)
        if s is not None:
            if not text and s["kind"] == KIND_TEXT:
                self._doc.remove(shape_id)
                if self._selected == shape_id:
                    self._selected = None
            elif text != (s.get("text") or ""):
                self._doc.update(shape_id, text=text)
        del is_new
        self.setFocus()
        self._changed()

    def _cancel_edit(self) -> None:
        if self._editing_id is None:
            return
        shape_id = self._editing_id
        self._editing_id = None
        self._edit.hide()
        s = self._doc.get(shape_id)
        if s is not None and s["kind"] == KIND_TEXT and not (s.get("text") or "").strip():
            self._doc.remove(shape_id)
        self.update()

    def cancel_text_edit(self) -> None:
        """Esc — 쓰던 글을 버린다(글씨만 있는 빈 도형은 지운다)."""
        self._cancel_edit()
        self._changed()

    def _changed(self) -> None:
        self.update()
        self.doc_changed.emit()
