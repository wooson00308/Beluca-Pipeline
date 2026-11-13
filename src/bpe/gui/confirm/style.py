"""컨펌 창의 모양 — 색·글씨·버튼 스타일·아이콘 (시안 2판 「전문 툴 느낌」 기준).

중립 회색 바탕에 촘촘하고 각진 조작부, 숫자는 폭이 고른 글씨, 강조색은 고른 것의
밑줄과 지금 프레임 표시에만 쓴다. 창 안의 모든 위젯이 여기 값만 쓰게 한다.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
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
DRAW_COLORS: Tuple[str, ...] = ("#ff5a52", "#f2c94c", "#ffffff")  # 처음 보이는 세 색
# 더 고를 수 있는 색(두 줄) — 따뜻한 색에서 찬 색으로, 끝은 무채색
PALETTE: Tuple[str, ...] = (
    "#ff5a52", "#ff9f40", "#f2c94c", "#a6d94a", "#4cc38a", "#3ec6e0", "#4a90e2", "#6f74e8",
    "#a66be0", "#f06ac0", "#a9744f", "#ffffff", "#bdbdbd", "#808080", "#404040", "#000000",
)  # fmt: skip
PALETTE_COLUMNS = 8
RETAKE = "#ff9a90"
RETAKE_EDGE = "#a8483f"
PAST = WARN
MARK = "#ff5a52"
CACHE = "#4f9f6a"
CHECK = "#bdbdbd"
TICK = "#5b5b5b"
DISABLED = "#8c8c8c"
GHOST = "#5b5b5b"
CELL_EDGE = "#3a3a3a"
CURRENT_CELL = "#303030"

# ── 크기·글씨 ────────────────────────────────────────────────────
CONTROL_H = 26  # 조작부 한 칸의 전체 높이(테두리 포함)
_INNER_H = CONTROL_H - 2  # 스타일 글의 height 는 테두리를 뺀 안쪽 높이
_CHECKED_H = _INNER_H - 2  # 눌린 칸: 아래 강조선 2px + 위 여백 1px 만큼 줄여 전체 높이를 같게
FONT_PX = 12
FONT_SMALL_PX = 11
MONO = "Consolas, 'Cascadia Mono', 'D2Coding', 'Malgun Gothic', monospace"
MONO_FAMILIES: Tuple[str, ...] = ("Consolas", "Cascadia Mono", "D2Coding", "Malgun Gothic")
RADIUS = 3
PANEL_WIDTH = 340


_glyph_files: Dict[str, str] = {}


def _glyph_rule(name: str, width: int, height: int, d: str, color: str, *, stroke: bool) -> str:
    """스타일 글에서 쓸 작은 그림(PNG)을 임시 폴더에 한 번 만들고 ``image:`` 규칙을 돌려준다."""
    if name not in _glyph_files:
        pm = QPixmap(width, height)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if stroke:
            pen = QPen(QColor(color), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
        p.drawPath(svg_path(d))
        p.end()
        path = Path(tempfile.gettempdir()) / f"bpe_confirm_{name}.png"
        _glyph_files[name] = path.as_posix() if pm.save(str(path), "PNG") else ""
    return f"image: url({_glyph_files[name]});" if _glyph_files[name] else "image: none;"


def _combo_arrow_rule() -> str:
    return _glyph_rule("combo_arrow", 9, 6, "M0.5 0.5h8l-4 5z", DIM, stroke=False)


def _check_mark_rule() -> str:
    return _glyph_rule("check_mark", 12, 12, "M2.5 6.2l2.6 2.6 4.6-5.4", ON_ACCENT, stroke=True)


def window_stylesheet() -> str:
    """컨펌 창 전체에 거는 기본 스타일(앱 전역 스타일보다 우선)."""
    return (
        f"QWidget#confirm_root {{ background: {BG}; }}"
        f"QWidget#confirm_root QLabel {{ color: {TEXT}; font-size: {FONT_PX}px; "
        f"background: transparent; }}"
        f"QWidget#confirm_root QPushButton {{ min-width: 0px; min-height: 0px; "
        f"height: {_INNER_H}px; padding: 0px 10px; border: 1px solid {EDGE}; "
        f"border-radius: {RADIUS}px; background: {RAISED}; color: {TEXT}; "
        f"font-size: {FONT_PX}px; }}"
        f"QWidget#confirm_root QPushButton:hover {{ background: #454545; }}"
        f"QWidget#confirm_root QPushButton:disabled {{ color: {DISABLED}; background: #2c2c2c; }}"
        f"QWidget#confirm_root QLineEdit, QWidget#confirm_root QPlainTextEdit, "
        f"QWidget#confirm_root QListWidget {{ background: {FIELD}; color: {TEXT}; "
        f"border: 1px solid {EDGE}; border-radius: {RADIUS}px; font-size: {FONT_PX}px; "
        f"selection-background-color: {ON}; }}"
        f"QWidget#confirm_root QLineEdit {{ min-width: 0px; min-height: 0px; "
        f"height: {_INNER_H}px; "
        f"padding: 0px 6px; }}"
        f"QWidget#confirm_root QComboBox {{ min-width: 0px; min-height: 0px; "
        f"height: {_INNER_H}px; "
        f"padding: 0px 6px; background: {FIELD}; color: {TEXT}; border: 1px solid {EDGE}; "
        f"border-radius: {RADIUS}px; font-size: {FONT_PX}px; }}"
        f"QWidget#confirm_root QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QWidget#confirm_root QComboBox::down-arrow {{ {_combo_arrow_rule()} "
        f"border: none; width: 9px; height: 6px; margin-right: 7px; }}"
        f"QWidget#confirm_root QCheckBox {{ spacing: 0px; }}"
        f"QWidget#confirm_root QCheckBox::indicator {{ width: 12px; height: 12px; "
        f"border: 1px solid {ON}; border-radius: 2px; background: {FIELD}; }}"
        f"QWidget#confirm_root QCheckBox::indicator:checked {{ background: {CHECK}; "
        f"border: 1px solid {CHECK}; {_check_mark_rule()} }}"
        f"QWidget#confirm_root QListWidget::item {{ padding: 5px 8px; "
        f"border-bottom: 1px solid {EDGE}; }}"
        f"QWidget#confirm_root QListWidget::item:selected {{ background: {RAISED}; "
        f"color: {TEXT}; }}"
        f"QWidget#confirm_root QSlider {{ background: transparent; }}"
        f"QWidget#confirm_root QSlider::groove:horizontal {{ height: 4px; background: #4a4a4a; "
        f"border-radius: 2px; }}"
        f"QWidget#confirm_root QSlider::sub-page:horizontal {{ background: {CHECK}; "
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


def field_style(*, changed: bool = False, pad: str = "3px 6px") -> str:
    """숫자 칸(게인·감마 값, 프레임 번호)."""
    color = WARN if changed else TEXT
    edge = WARN_EDGE if changed else EDGE
    return (
        f"background: {FIELD}; color: {color}; border: 1px solid {edge}; "
        f"border-radius: {RADIUS}px; padding: {pad}; {mono()}"
    )


def segment_style(
    position: str, *, on_color: str = "", text_color: str = "", mark_color: str = ""
) -> str:
    """서로 붙은 버튼 묶음의 한 칸. *position*: first / mid / last / only.

    *mark_color* 를 주면 안 눌린 상태에서도 그 색 밑줄을 긋는다(차이 보기에서 빼는 판).
    """
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
        f"border-bottom: 2px solid {line}; padding-top: 1px; height: {_CHECKED_H}px; }}"
        f"QPushButton:disabled {{ color: {DISABLED}; }}"
    ) + (
        f"QPushButton:!checked {{ border-bottom: 2px solid {mark_color}; padding-top: 1px; "
        f"height: {_CHECKED_H}px; }}"
        if mark_color
        else ""
    )


def warn_toggle_style() -> str:
    """켜면 「평소와 다른 보기」임을 알리는 버튼(차이)."""
    return (
        f"QPushButton:checked {{ background: {WARN_BG}; color: {WARN}; "
        f"border: 1px solid {WARN_EDGE}; border-bottom: 2px solid {WARN}; padding-top: 1px; "
        f"height: {_CHECKED_H}px; }}"
    )


def lut_toggle_style(*, loaded: bool) -> str:
    """LUT 버튼. 룩업을 골라 둔 채 꺼 두면 「평소와 다른 보기」 색으로 알린다."""
    base = segment_style("first") + "QPushButton { font-weight: bold; }"
    if not loaded:
        return base
    return base + (
        f"QPushButton:!checked {{ background: {WARN_BG}; color: {WARN}; "
        f"border-bottom: 2px solid {WARN}; padding-top: 1px; height: {_CHECKED_H}px; }}"
    )


def warn_button_style() -> str:
    return (
        f"QPushButton {{ background: {WARN_BG}; color: {WARN}; border: 1px solid {WARN_EDGE}; }}"
        f"QPushButton:hover {{ background: #3a3115; }}"
    )


def icon_button_style(size: int = 30) -> str:
    return (
        f"QPushButton {{ min-width: {size}px; max-width: {size}px; height: {size}px; "
        f"padding: 0px; border: none; border-radius: {RADIUS}px; background: transparent; }}"
        f"QPushButton:hover {{ background: {RAISED}; }}"
        f"QPushButton:checked {{ background: {ON}; border-bottom: 2px solid {ACCENT}; "
        f"height: {size - 4}px; padding-top: 2px; }}"
    )


def fixed_width_style(width: int) -> str:
    """버튼의 전체 폭을 못박는다(스타일 글의 폭이 위젯의 고정 폭보다 우선하므로 여기서 건다)."""
    inner = width - 2
    return f"QPushButton {{ min-width: {inner}px; max-width: {inner}px; padding: 0px; }}"


def swatch_style(color: str, selected: bool) -> str:
    ring = TEXT if selected else PANEL
    return (
        f"QPushButton {{ min-width: 14px; max-width: 14px; height: 14px; padding: 0px; "
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
# 24×24 칸에 그린 선 그림. 경로 글은 시안 2판의 것을 그대로 옮겼다(SVG path 의 일부 명령만 쓴다).

_ICON_BOX = 24.0
_STROKE = "stroke"
_FILL = "fill"
_BOTH = "both"  # 선도 긋고 속도 채운다(화살표 머리)
_ICON_PATHS: Dict[str, Tuple[str, str]] = {
    "select": (_STROKE, "M5 3v16l4.5-4 3 6 2.5-1-3-6h6z"),
    "rect": (_STROKE, "M4 6h16v12H4z"),
    "ellipse": (
        _STROKE,
        "M12 5.5c4.4 0 8 2.9 8 6.5s-3.6 6.5-8 6.5-8-2.9-8-6.5 3.6-6.5 8-6.5z",
    ),
    "pen": (_STROKE, "M4 20l1.2-4.8L16.5 3.9l3.6 3.6L8.8 18.8zM14 6.4l3.6 3.6"),
    "arrow": (_BOTH, "M5 19L15 9M19.5 4.5l-2 9-7-7z"),
    "text": (_STROKE, "M5 6h14M12 6v13"),
    "eraser": (_STROKE, "M8 20l-5-5L13 5l7 7-8 8zM9 10l7 7"),
    "undo": (_STROKE, "M7 8h8c6.6 0 6.6 10 0 10H7M10.5 4L6.5 8l4 4"),
    "redo": (_STROKE, "M17 8H9c-6.6 0-6.6 10 0 10h8M13.5 4l4 4-4 4"),
    "range": (_STROKE, "M8 5H5v14h3M16 5h3v14h-3M9.5 12h5"),
    "list": (_STROKE, "M4 6h16M4 12h16M4 18h16"),
    "diff": (_STROKE, "M12 4v16M5 8h4M5 16h4M15 16h4"),
    "chev_left": (_STROKE, "M15 5l-7 7 7 7"),
    "chev_right": (_STROKE, "M9 5l7 7-7 7"),
    "loop": (_STROKE, "M17.5 8H8c-4.5 0-4.5 8 0 8h8c4.5 0 4.5-5 2.5-6.5M14.5 5l3.3 3-3.3 3"),
    "fullscreen": (_STROKE, "M4.5 9V4.5H9M15 4.5h4.5V9M19.5 15v4.5H15M9 19.5H4.5V15"),
    "folder": (_STROKE, "M3.5 6.5h6l2 2.5h9v9.5h-17z"),
    "help": (
        _STROKE,
        "M12 3.5c4.69 0 8.5 3.81 8.5 8.5s-3.81 8.5-8.5 8.5-8.5-3.81-8.5-8.5 3.81-8.5 8.5-8.5z"
        "M9.7 9.8c0-3 4.8-3 4.6 0-0.15 1.6-2.3 1.7-2.3 3.5M12 16.3v0.4",
    ),
    "palette": (
        _FILL,
        "M5 5h3.5v3.5H5zM10.25 5h3.5v3.5h-3.5zM15.5 5H19v3.5h-3.5z"
        "M5 10.25h3.5v3.5H5zM10.25 10.25h3.5v3.5h-3.5zM15.5 10.25H19v3.5h-3.5z"
        "M5 15.5h3.5V19H5zM10.25 15.5h3.5V19h-3.5zM15.5 15.5H19V19h-3.5z",
    ),
    "play": (_FILL, "M7 4v16l13-8z"),
    "pause": (_FILL, "M6 5h4v14H6z M14 5h4v14h-4z"),
    "first": (_FILL, "M5 5h2v14H5z M19 5v14l-10-7z"),
    "step_back": (_FILL, "M15 5v14L6 12z M17 5h2v14h-2z"),
    "step_fwd": (_FILL, "M9 5v14l9-7z M5 5h2v14H5z"),
    "last": (_FILL, "M5 5v14l10-7z M17 5h2v14h-2z"),
}
ICON_NAMES: Tuple[str, ...] = tuple(_ICON_PATHS)
_PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsZz]|-?\d*\.?\d+")
_ARG_COUNT = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "z": 0}


def svg_path(d: str) -> QPainterPath:
    """SVG path 글(M L H V C S Z, 절대·상대)을 QPainterPath 로 바꾼다."""
    path = QPainterPath()
    tokens = _PATH_TOKEN.findall(d)
    x = y = 0.0
    start = (0.0, 0.0)
    last_ctrl: Optional[Tuple[float, float]] = None
    cmd = ""
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        low, rel = cmd.lower(), cmd.islower()
        n = _ARG_COUNT[low]
        a = [float(t) for t in tokens[i : i + n]]
        i += n
        ox, oy = (x, y) if rel else (0.0, 0.0)
        ctrl: Optional[Tuple[float, float]] = None
        if low == "m":
            x, y = ox + a[0], oy + a[1]
            path.moveTo(x, y)
            start = (x, y)
            cmd = "l" if rel else "L"  # 뒤따르는 좌표는 선
        elif low == "l":
            x, y = ox + a[0], oy + a[1]
            path.lineTo(x, y)
        elif low == "h":
            x = ox + a[0]
            path.lineTo(x, y)
        elif low == "v":
            y = oy + a[0]
            path.lineTo(x, y)
        elif low in ("c", "s"):
            if low == "c":
                c1 = (ox + a[0], oy + a[1])
                a = a[2:]
            else:
                c1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl else (x, y)
            ctrl = (ox + a[0], oy + a[1])
            x, y = ox + a[2], oy + a[3]
            path.cubicTo(QPointF(*c1), QPointF(*ctrl), QPointF(x, y))
        else:  # z
            path.closeSubpath()
            x, y = start
            if i < len(tokens) and not tokens[i].isalpha():
                break  # z 뒤에 좌표가 오면 잘못된 글 — 멈춘다
        last_ctrl = ctrl
    return path


def _draw_icon(p: QPainter, name: str, color: str) -> None:
    mode, d = _ICON_PATHS[name]
    if mode == _FILL:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
    else:
        pen = QPen(QColor(color), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(QColor(color) if mode == _BOTH else Qt.BrushStyle.NoBrush)
    p.drawPath(svg_path(d))


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
