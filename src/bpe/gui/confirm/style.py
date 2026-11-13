"""컨펌 창의 모양 — 색·글씨·버튼 스타일·아이콘 (시안 2판 「전문 툴 느낌」 기준).

중립 회색 바탕에 촘촘하고 각진 조작부, 숫자는 폭이 고른 글씨, 강조색은 고른 것의
밑줄과 지금 프레임 표시에만 쓴다. 창 안의 모든 위젯이 여기 값만 쓰게 한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QPushButton, QWidget

from bpe.gui import theme

# ── 색 ───────────────────────────────────────────────────────────
BG = "#1b1b1b"
HEADER = "#2e2e2e"
PANEL = "#262626"
RAISED = "#3a3a3a"
ON = "#5b5b5b"
FIELD = "#1a1a1a"
EDGE = "#111111"
VIEWER_BG = "#141414"
INFO_BG = "#1f1f1f"
TEXT = "#d6d6d6"
TEXT_STRONG = "#ffffff"
DIM = "#8c8c8c"
LABEL = "#a8a8a8"
ACCENT = theme.ACCENT
ON_ACCENT = "#0e0e0e"
WARN = "#f0c060"
WARN_BG = "#2b2410"
WARN_EDGE = "#6b5518"
OK = "#7fcf9a"
FAIL = "#ff7b7b"
STATUS_DOT = "#e8a33d"
CHANNEL_COLORS: Dict[str, str] = {"R": "#ff7b7b", "G": "#7fcf7f", "B": "#7fb0ff"}
DRAW_COLORS: Tuple[str, ...] = ("#ff5a52", "#f2c94c", "#ffffff")
RETAKE = "#ff9a90"
RETAKE_EDGE = "#a8483f"
PAST = WARN
MARK = "#ff5a52"
CACHE = "#4f9f6a"

# ── 크기·글씨 ────────────────────────────────────────────────────
CONTROL_H = 26
FONT_PX = 12
FONT_SMALL_PX = 11
MONO = "Consolas, 'Cascadia Mono', 'D2Coding', monospace"
RADIUS = 3
PANEL_WIDTH = 340


_arrow_file = ""


def _combo_arrow_rule() -> str:
    """고르기 칸의 아래 화살표 그림(작은 PNG 를 임시 폴더에 한 번 만든다)."""
    global _arrow_file
    if not _arrow_file:
        pm = QPixmap(16, 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _fill(p, DIM)
        p.drawPolygon(_poly([(1, 2), (15, 2), (8, 11)]))
        p.end()
        path = Path(tempfile.gettempdir()) / "bpe_confirm_combo_arrow.png"
        if pm.save(str(path), "PNG"):
            _arrow_file = path.as_posix()
    return f"image: url({_arrow_file});" if _arrow_file else "image: none;"


def window_stylesheet() -> str:
    """컨펌 창 전체에 거는 기본 스타일(앱 전역 스타일보다 우선)."""
    return (
        f"QWidget#confirm_root {{ background: {BG}; }}"
        f"QWidget#confirm_root QLabel {{ color: {TEXT}; font-size: {FONT_PX}px; "
        f"background: transparent; }}"
        f"QWidget#confirm_root QPushButton {{ min-width: 0px; min-height: 0px; "
        f"height: {CONTROL_H}px; padding: 0px 10px; border: 1px solid {EDGE}; "
        f"border-radius: {RADIUS}px; background: {RAISED}; color: {TEXT}; "
        f"font-size: {FONT_PX}px; }}"
        f"QWidget#confirm_root QPushButton:hover {{ background: #454545; }}"
        f"QWidget#confirm_root QPushButton:disabled {{ color: #6a6a6a; background: #2c2c2c; }}"
        f"QWidget#confirm_root QLineEdit, QWidget#confirm_root QPlainTextEdit, "
        f"QWidget#confirm_root QListWidget {{ background: {FIELD}; color: {TEXT}; "
        f"border: 1px solid {EDGE}; border-radius: {RADIUS}px; font-size: {FONT_PX}px; "
        f"selection-background-color: {ON}; }}"
        f"QWidget#confirm_root QLineEdit {{ min-width: 0px; height: {CONTROL_H - 2}px; "
        f"padding: 0px 6px; }}"
        f"QWidget#confirm_root QComboBox {{ min-width: 0px; height: {CONTROL_H - 2}px; "
        f"padding: 0px 6px; background: {FIELD}; color: {TEXT}; border: 1px solid {EDGE}; "
        f"border-radius: {RADIUS}px; font-size: {FONT_PX}px; }}"
        f"QWidget#confirm_root QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QWidget#confirm_root QComboBox::down-arrow {{ {_combo_arrow_rule()} "
        f"width: 8px; height: 6px; margin-right: 7px; }}"
        f"QWidget#confirm_root QCheckBox {{ spacing: 7px; }}"
        f"QWidget#confirm_root QCheckBox::indicator {{ width: 12px; height: 12px; "
        f"border: 1px solid {ON}; border-radius: 2px; background: {FIELD}; }}"
        f"QWidget#confirm_root QCheckBox::indicator:checked {{ background: {ACCENT}; "
        f"border: 1px solid {ACCENT}; }}"
        f"QWidget#confirm_root QListWidget::item {{ padding: 5px 8px; "
        f"border-bottom: 1px solid {EDGE}; }}"
        f"QWidget#confirm_root QListWidget::item:selected {{ background: {RAISED}; "
        f"color: {TEXT}; }}"
        f"QWidget#confirm_root QSlider::groove:horizontal {{ height: 4px; background: #4a4a4a; "
        f"border-radius: 2px; }}"
        f"QWidget#confirm_root QSlider::sub-page:horizontal {{ background: #9a9a9a; "
        f"border-radius: 2px; }}"
        f"QWidget#confirm_root QSlider::handle:horizontal {{ width: 12px; margin: -5px 0; "
        f"border-radius: 6px; background: #e6e6e6; border: 1px solid {EDGE}; }}"
        f"QWidget#confirm_root QToolTip {{ background: {PANEL}; color: {TEXT}; "
        f"border: 1px solid {EDGE}; }}"
    )


def bar_style(bg: str = PANEL, *, bottom: bool = True, top: bool = False) -> str:
    edge = ""
    if bottom:
        edge += f"border-bottom: 1px solid {EDGE};"
    if top:
        edge += f"border-top: 1px solid {EDGE};"
    return f"background: {bg}; {edge}"


def section_header_style() -> str:
    return (
        f"background: {HEADER}; color: {LABEL}; font-size: {FONT_SMALL_PX}px; font-weight: bold; "
        f"padding: 6px 10px; border-bottom: 1px solid {EDGE};"
    )


def mono(px: int = FONT_PX, *, bold: bool = False) -> str:
    return f"font-family: {MONO}; font-size: {px}px;" + (" font-weight: bold;" if bold else "")


def field_style(*, changed: bool = False) -> str:
    """숫자 칸(게인·감마 값, 프레임 번호)."""
    color = WARN if changed else TEXT
    edge = WARN_EDGE if changed else EDGE
    return (
        f"background: {FIELD}; color: {color}; border: 1px solid {edge}; "
        f"border-radius: {RADIUS}px; padding: 3px 6px; {mono()}"
    )


def segment_style(position: str, *, on_color: str = "", text_color: str = "") -> str:
    """서로 붙은 버튼 묶음의 한 칸. *position*: first / mid / last / only."""
    left = RADIUS if position in ("first", "only") else 0
    right = RADIUS if position in ("last", "only") else 0
    border_left = "" if position in ("first", "only") else "border-left: none;"
    line = on_color or ACCENT
    color = text_color or TEXT
    return (
        f"QPushButton {{ border-top-left-radius: {left}px; border-bottom-left-radius: {left}px; "
        f"border-top-right-radius: {right}px; border-bottom-right-radius: {right}px; "
        f"{border_left} color: {color}; }}"
        f"QPushButton:checked {{ background: {ON}; color: {TEXT_STRONG}; "
        f"border-bottom: 2px solid {line}; }}"
        f"QPushButton:disabled {{ color: #6a6a6a; }}"
    )


def warn_toggle_style() -> str:
    """켜면 「평소와 다른 보기」임을 알리는 버튼(차이)."""
    return (
        f"QPushButton:checked {{ background: {WARN_BG}; color: {WARN}; "
        f"border: 1px solid {WARN_EDGE}; border-bottom: 2px solid {WARN}; }}"
    )


def warn_button_style() -> str:
    return (
        f"QPushButton {{ background: {WARN_BG}; color: {WARN}; border: 1px solid {WARN_EDGE}; }}"
        f"QPushButton:hover {{ background: #3a3115; }}"
    )


def icon_button_style(size: int = 30) -> str:
    return (
        f"QPushButton {{ min-width: {size}px; max-width: {size}px; height: {size}px; "
        f"padding: 0px; border: none; background: transparent; }}"
        f"QPushButton:hover {{ background: {RAISED}; }}"
        f"QPushButton:checked {{ background: {ON}; border-bottom: 2px solid {ACCENT}; }}"
    )


def swatch_style(color: str, selected: bool) -> str:
    ring = TEXT if selected else PANEL
    return (
        f"QPushButton {{ min-width: 16px; max-width: 16px; height: 16px; padding: 0px; "
        f"border: 2px solid {ring}; border-radius: 2px; background: {color}; }}"
        f"QPushButton:hover {{ background: {color}; border-color: {TEXT}; }}"
    )


def make_segments(buttons: List[QPushButton], **kwargs: str) -> None:
    """버튼들을 붙은 묶음으로 보이게 스타일을 건다(레이아웃 간격은 0 으로 둘 것)."""
    n = len(buttons)
    for i, b in enumerate(buttons):
        pos = "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid"
        b.setStyleSheet(segment_style(pos, **kwargs))


# ── 아이콘 ───────────────────────────────────────────────────────

_ICON_BOX = 24.0


def _stroke(p: QPainter, color: str, width: float = 2.0) -> None:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill(p: QPainter, color: str) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))


def _poly(points: List[Tuple[float, float]]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _draw_icon(p: QPainter, name: str, color: str) -> None:  # noqa: C901 - 아이콘 표
    if name == "select":
        _stroke(p, color, 1.8)
        p.drawPolygon(
            _poly([(6, 3), (6, 19), (10.2, 15.2), (13, 21), (15.6, 19.8), (12.8, 14), (18.5, 14)])
        )
    elif name == "rect":
        _stroke(p, color)
        p.drawRect(QRectF(4, 6.5, 16, 11))
    elif name == "pen":
        _stroke(p, color)
        path = QPainterPath(QPointF(3.5, 16.5))
        path.cubicTo(QPointF(7, 5), QPointF(10, 19), QPointF(13.5, 11))
        path.cubicTo(QPointF(15.5, 6.5), QPointF(18.5, 8), QPointF(20.5, 5.5))
        p.drawPath(path)
    elif name == "arrow":
        _stroke(p, color)
        p.drawLine(QPointF(5, 19), QPointF(18.5, 5.5))
        p.drawPolyline(_poly([(11, 5.5), (18.5, 5.5), (18.5, 13)]))
    elif name == "text":
        _stroke(p, color, 2.2)
        p.drawLine(QPointF(5.5, 6), QPointF(18.5, 6))
        p.drawLine(QPointF(12, 6), QPointF(12, 19))
    elif name == "eraser":
        _stroke(p, color, 1.8)
        p.drawPolygon(_poly([(8.5, 20), (3.5, 15), (13.5, 5), (20.5, 12), (12.5, 20)]))
        p.drawLine(QPointF(9, 10), QPointF(16, 17))
    elif name == "undo":
        _stroke(p, color)
        path = QPainterPath(QPointF(8, 9))
        path.lineTo(QPointF(14.5, 9))
        path.cubicTo(QPointF(19, 9), QPointF(19, 17), QPointF(14.5, 17))
        path.lineTo(QPointF(8, 17))
        p.drawPath(path)
        p.drawPolyline(_poly([(11, 5.5), (7.5, 9), (11, 12.5)]))
    elif name == "redo":
        _stroke(p, color)
        path = QPainterPath(QPointF(16, 9))
        path.lineTo(QPointF(9.5, 9))
        path.cubicTo(QPointF(5, 9), QPointF(5, 17), QPointF(9.5, 17))
        path.lineTo(QPointF(16, 17))
        p.drawPath(path)
        p.drawPolyline(_poly([(13, 5.5), (16.5, 9), (13, 12.5)]))
    elif name == "trash":
        _stroke(p, color, 1.8)
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawPolyline(_poly([(7, 7), (8, 20), (16, 20), (17, 7)]))
        p.drawPolyline(_poly([(9.5, 7), (10, 4), (14, 4), (14.5, 7)]))
    elif name == "range":
        _stroke(p, color, 1.8)
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
        p.drawLine(QPointF(4, 7), QPointF(4, 17))
        p.drawLine(QPointF(20, 7), QPointF(20, 17))
    elif name == "list":
        _stroke(p, color)
        for y in (6.5, 12.0, 17.5):
            p.drawLine(QPointF(4.5, y), QPointF(19.5, y))
    elif name == "diff":
        _stroke(p, color, 1.8)
        p.drawLine(QPointF(12, 4), QPointF(12, 20))
        p.drawLine(QPointF(5, 8), QPointF(9, 8))
        p.drawLine(QPointF(5, 16), QPointF(9, 16))
        p.drawLine(QPointF(15, 16), QPointF(19, 16))
    elif name == "chev_left":
        _stroke(p, color)
        p.drawPolyline(_poly([(14.5, 5.5), (8, 12), (14.5, 18.5)]))
    elif name == "chev_right":
        _stroke(p, color)
        p.drawPolyline(_poly([(9.5, 5.5), (16, 12), (9.5, 18.5)]))
    elif name == "play":
        _fill(p, color)
        p.drawPolygon(_poly([(8, 4.5), (8, 19.5), (20, 12)]))
    elif name == "pause":
        _fill(p, color)
        p.drawRect(QRectF(6.5, 5, 4, 14))
        p.drawRect(QRectF(13.5, 5, 4, 14))
    elif name == "first":
        _fill(p, color)
        p.drawRect(QRectF(5, 5, 2.2, 14))
        p.drawPolygon(_poly([(19, 5), (19, 19), (9, 12)]))
    elif name == "last":
        _fill(p, color)
        p.drawRect(QRectF(16.8, 5, 2.2, 14))
        p.drawPolygon(_poly([(5, 5), (5, 19), (15, 12)]))
    elif name == "step_back":
        _fill(p, color)
        p.drawPolygon(_poly([(15, 5), (15, 19), (6, 12)]))
        p.drawRect(QRectF(16.8, 5, 2.2, 14))
    elif name == "step_fwd":
        _fill(p, color)
        p.drawPolygon(_poly([(9, 5), (9, 19), (18, 12)]))
        p.drawRect(QRectF(5, 5, 2.2, 14))
    elif name == "loop":
        _stroke(p, color, 1.8)
        path = QPainterPath(QPointF(17.5, 8))
        path.lineTo(QPointF(8, 8))
        path.cubicTo(QPointF(3.5, 8), QPointF(3.5, 16), QPointF(8, 16))
        path.lineTo(QPointF(16, 16))
        path.cubicTo(QPointF(20.5, 16), QPointF(20.5, 11), QPointF(18.5, 9.5))
        p.drawPath(path)
        p.drawPolyline(_poly([(14.5, 5), (17.8, 8), (14.5, 11)]))
    elif name == "fullscreen":
        _stroke(p, color, 1.8)
        p.drawPolyline(_poly([(4.5, 9), (4.5, 4.5), (9, 4.5)]))
        p.drawPolyline(_poly([(15, 4.5), (19.5, 4.5), (19.5, 9)]))
        p.drawPolyline(_poly([(19.5, 15), (19.5, 19.5), (15, 19.5)]))
        p.drawPolyline(_poly([(9, 19.5), (4.5, 19.5), (4.5, 15)]))
    elif name == "folder":
        _stroke(p, color, 1.8)
        p.drawPolygon(
            _poly([(3.5, 6.5), (9.5, 6.5), (11.5, 9), (20.5, 9), (20.5, 18.5), (3.5, 18.5)])
        )
    elif name == "help":
        _stroke(p, color, 1.8)
        p.drawEllipse(QRectF(4, 4, 16, 16))
        path = QPainterPath(QPointF(9.5, 9.8))
        path.cubicTo(QPointF(9.5, 6.5), QPointF(14.8, 6.5), QPointF(14.5, 9.8))
        path.cubicTo(QPointF(14.3, 11.5), QPointF(12, 11.6), QPointF(12, 13.6))
        p.drawPath(path)
        _fill(p, color)
        p.drawEllipse(QRectF(11.1, 15.4, 1.9, 1.9))


ICON_NAMES: Tuple[str, ...] = (
    "select", "rect", "pen", "arrow", "text", "eraser", "undo", "redo", "trash", "range",
    "list", "diff", "chev_left", "chev_right", "play", "pause", "first", "last", "step_back",
    "step_fwd", "loop", "fullscreen", "folder", "help",
)  # fmt: skip


def make_icon(name: str, color: str = TEXT, size: int = 16, on_color: str = TEXT_STRONG) -> QIcon:
    """선으로 그린 아이콘. 고른 상태(checked)에서는 *on_color* 로 보인다."""
    icon = QIcon()
    for mode_color, state in ((color, QIcon.State.Off), (on_color, QIcon.State.On)):
        scale = 2  # 고해상도 화면에서도 또렷하게
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(size * scale / _ICON_BOX, size * scale / _ICON_BOX)
        _draw_icon(p, name, mode_color)
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm, QIcon.Mode.Normal, state)
    return icon


def set_icon(button: QPushButton, name: str, *, size: int = 16, color: str = TEXT) -> None:
    button.setIcon(make_icon(name, color, size))
    button.setIconSize(QSize(size, size))


def apply_root(widget: QWidget) -> None:
    """창 뿌리에 이름과 기본 스타일을 건다."""
    widget.setObjectName("confirm_root")
    widget.setStyleSheet(window_stylesheet())
