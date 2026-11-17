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
    QFocusEvent,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

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
    TEXT_WRAP_WIDTH,
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
_WRAP_REF_H = 1080.0  # 글씨 줄 나눔을 계산하는 기준 그림 높이
_EDIT_PAD_W = 14  # 글 칸의 테두리·안쪽 여백(좌우 합) — 글이 놓이는 폭은 칸 폭에서 이만큼 뺀 것
_EDIT_MIN_W = 120.0
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


def _ref_font(shape: Shape) -> QFont:
    """줄 나눔을 계산할 때 쓰는 글꼴 — 높이 1080 짜리 그림에 놓였을 때의 크기."""
    f = QFont()
    f.setBold(True)
    size = float(shape.get("text_size") or DEFAULT_TEXT_SIZE)
    f.setPixelSize(max(11, int(round(size * _WRAP_REF_H))))
    return f


def _wrap(text: str, font: QFont, width: float) -> List[str]:
    """글을 *width*(화소) 안에 들어가게 줄로 나눈다 — 낱말 사이에서, 긴 낱말은 글자 사이에서."""
    rows: List[str] = []
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    for para in text.split("\n"):
        if not para:
            rows.append("")
            continue
        layout = QTextLayout(para, font)
        layout.setTextOption(option)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1.0, width))
            start = line.textStart()
            rows.append(para[start : start + line.textLength()].rstrip())
        layout.endLayout()
    return rows or [""]


def _wrap_ref_width(rect: Rect) -> float:
    """한 줄 폭(기준 크기의 화소) — 영상 폭의 ``TEXT_WRAP_WIDTH``."""
    aspect = rect[2] / rect[3] if rect[2] > 0 and rect[3] > 0 else 16.0 / 9.0
    return TEXT_WRAP_WIDTH * _WRAP_REF_H * aspect


def wrap_rows(shape: Shape, rect: Rect, text: str) -> List[str]:
    """화면 글씨의 줄들. 한 줄 폭은 영상 폭의 30% 로 고정이고 넘치면 아래로 줄이 바뀐다.

    줄 나눔은 늘 같은 기준 크기에서 계산한다 — 그래서 창 크기·확대와 상관없이, 그리고
    Note 에 붙는 그림에서도 같은 자리에서 줄이 바뀐다.
    """
    return _wrap(text, _ref_font(shape), _wrap_ref_width(rect))


def text_box(shape: Shape, rect: Rect, text: str) -> Tuple[List[str], QRectF]:
    """글씨의 줄들과, 그 글이 화면에서 차지하는 네모(검은 바탕 포함)."""
    fm = QFontMetricsF(text_font(shape, rect))
    origin = text_origin(shape, rect)
    rows = wrap_rows(shape, rect, text)
    wide = max(fm.horizontalAdvance(r) for r in rows)
    tall = fm.height() + fm.lineSpacing() * (len(rows) - 1)
    return rows, QRectF(origin.x(), origin.y(), wide + 14, tall + 6)


def _paint_text(p: QPainter, shape: Shape, rect: Rect, text: str, color: QColor) -> None:
    p.setFont(text_font(shape, rect))
    rows, box = text_box(shape, rect, text)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 190))
    p.drawRect(box)
    p.setPen(color)
    flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    p.drawText(box.adjusted(7, 3, -7, -3), flags, "\n".join(rows))


class _TextEdit(QPlainTextEdit):
    """화면 글씨 칸 — Enter 는 확정, Shift+Enter·Alt+Enter 는 줄 바꿈, Esc 는 버리기."""

    committed = Signal()
    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            newline = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
            if event.modifiers() & newline:
                self.insertPlainText("\n")
            else:
                self.committed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.committed.emit()


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
        # 지금 보고 있는 영상(Annotation: 원본 / edit). 빈 글이면 영상을 가리지 않는다(Confirm).
        self._source = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._edit = _TextEdit(self)
        self._edit.setPlaceholderText("피드백을 쓰고 Enter · 줄 바꿈은 Shift+Enter")
        # 칸 폭은 고정이고(영상 폭의 30%) 넘치는 글은 아래로 줄이 바뀐다 — 옆으로 커지지 않는다
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setTabChangesFocus(True)
        self._edit.document().setDocumentMargin(3)
        self._edit.hide()
        self._edit.committed.connect(self._commit_edit)
        self._edit.cancelled.connect(self.cancel_text_edit)
        self._edit.textChanged.connect(self._place_edit)
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

    def source(self) -> str:
        return self._source

    def set_source(self, source: str) -> None:
        """그림을 그릴 영상을 정한다 — 새 그림에 적히고, 그 영상에서 그린 그림만 보인다."""
        source = str(source or "")
        if source == self._source:
            return
        if self._edit.isVisible():
            self._commit_edit()
        self._source = source
        if self._selected is not None:
            self._selected = None
            self.selection_changed.emit()
        self.update()

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

    def _text_extent(self, shape: Shape) -> Tuple[float, float]:
        """글씨 도형이 화면에서 차지하는 (폭, 높이)를 영상 기준 0~1 로 — 눌러서 고를 범위."""
        rect = self._rect()
        text = (shape.get("text") or "").strip()
        if rect is None or rect[2] <= 0 or rect[3] <= 0 or not text:
            return (0.0, 0.0)
        _rows, box = text_box(shape, rect, text)
        return (box.width() / rect[2], box.height() / rect[3])

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
            self._doc.shapes_at(self._frame, self._source or None),
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
            hit = self._doc.hit_test(
                self._frame, n[0], n[1], self._text_extent, self._source or None
            )
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
            shape = make_shape(
                KIND_TEXT,
                self._frame,
                [n],
                color=self._color,
                width=self._width,
                source=self._source,
            )
            self._begin_edit(self._doc.add(shape), is_new=True)
            self._changed()
            event.accept()
            return
        self._draft = make_shape(
            self._tool,
            self._frame,
            [n, n],
            color=self._color,
            width=self._width,
            source=self._source,
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
        self._changed()  # 도형은 그리면 끝 — 글은 글씨 도구(T)로 따로 쓴다
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        n = self._norm(event.position(), clamp=False)
        hit = (
            self._doc.hit_test(self._frame, n[0], n[1], self._text_extent, self._source or None)
            if n
            else None
        )
        if hit is not None:
            self._selected = hit
            s = self._doc.get(hit)
            # 글씨, 그리고 예전에 글을 달아 둔 도형만 글을 고친다(글 없는 도형은 고르기만)
            if s is not None and (s["kind"] == KIND_TEXT or (s.get("text") or "").strip()):
                self._begin_edit(hit, is_new=False)
            else:
                self.selection_changed.emit()
                self.update()
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
        self._edit.setPlainText(s.get("text") or "")
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
        # 글 칸의 글씨도 확정된 글과 같은 크기·굵기로 — 그래야 칸 안에서 줄이 바뀌는 자리가
        # 확정 뒤와 같다(스타일시트의 글씨 크기가 setFont 를 덮으므로 여기에도 적는다)
        self._edit.setStyleSheet(
            f"background: {style.FIELD}; color: {s.get('color') or DEFAULT_COLOR}; "
            f"border: 1px solid {s.get('color') or DEFAULT_COLOR}; "
            f"border-radius: {style.RADIUS}px; padding: 0px 3px; "
            f"min-width: 0px; min-height: 0px; "
            f"font-size: {font.pixelSize()}px; font-weight: bold;"
        )
        self._edit.ensurePolished()
        shown_font = self._edit.font()  # 칸이 실제로 쓰는 글꼴로 잰다
        origin = text_origin(s, rect)
        fm = QFontMetricsF(shown_font)
        # 칸 폭은 글 길이와 상관없이 고정 — 확정된 글이 그려질 때와 같은 한 줄 폭
        scale = font.pixelSize() / max(1, _ref_font(s).pixelSize())
        inner = max(_EDIT_MIN_W, _wrap_ref_width(rect) * scale)
        w = min(inner + _EDIT_PAD_W, max(_EDIT_MIN_W, self.width() - 8.0))
        shown = self._edit.toPlainText() or self._edit.placeholderText()
        rows = _wrap(shown, shown_font, w - _EDIT_PAD_W)
        h = fm.height() + fm.lineSpacing() * (len(rows) - 1) + 12
        x = max(4.0, min(self.width() - w - 4.0, origin.x()))
        y = max(4.0, min(self.height() - h - 4.0, origin.y()))
        self._edit.setGeometry(int(x), int(y), int(w), int(h))

    def _commit_edit(self) -> None:
        if self._editing_id is None:
            return
        shape_id, is_new = self._editing_id, self._editing_new
        self._editing_id = None
        text = "\n".join(r.rstrip() for r in self._edit.toPlainText().split("\n")).strip()
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

    def commit_text_edit(self) -> None:
        """쓰던 글을 확정한다(Enter 를 친 것과 같다). 쓰는 중이 아니면 아무 일도 없다."""
        if self._editing_id is not None:
            self._commit_edit()

    def cancel_text_edit(self) -> None:
        """Esc — 쓰던 글을 버린다(글씨만 있는 빈 도형은 지운다)."""
        self._cancel_edit()
        self._changed()

    def _changed(self) -> None:
        self.update()
        self.doc_changed.emit()
