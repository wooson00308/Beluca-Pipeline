"""상태(Status)별 색·아이콘 — 샷그리드에 정해 둔 것을 받아 컨펌 창 곳곳에서 같은 모양으로 쓴다.

샷그리드에서 아직 못 읽었을 때는 BPE 가 원래 쓰던 상태 색 표(``theme``)로 보여 준다.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from bpe.gui import theme
from bpe.gui.confirm import style

# 샷그리드 기본 아이콘(그림을 내려받을 수 없는 것) → 우리가 그리는 선 그림
_GLYPH_FOR_KEY = {"icon_undo": "undo", "icon_thumb_up": "thumb", "icon_star": "star"}
_DARK, _LIGHT = "#111111", "#ffffff"

_styles: Dict[str, Dict[str, Any]] = {}


def set_styles(styles: Dict[str, Dict[str, Any]]) -> None:
    """샷그리드에서 읽은 상태 정보로 바꾼다."""
    _styles.clear()
    _styles.update({str(k).strip().lower(): dict(v) for k, v in styles.items()})


def has_styles() -> bool:
    return bool(_styles)


def _key(code: str) -> str:
    return (code or "").strip().lower()


def name(code: str) -> str:
    return str(_styles.get(_key(code), {}).get("name") or "")


def _readable_on(bg: str) -> str:
    c = QColor(bg)
    luma = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return _DARK if luma > 0.5 else _LIGHT


def colors(code: str) -> Tuple[str, str]:
    """``(바탕색, 그 위 글자색)``."""
    bg = str(_styles.get(_key(code), {}).get("color") or "")
    if bg:
        return bg, _readable_on(bg)
    return theme.task_status_badge_colors(code)


def text_color(code: str) -> str:
    """어두운 패널 위에 상태 글자를 쓸 때의 색 — 상태 색이 너무 어두우면 흐린 글자색."""
    bg, _fg = colors(code)
    c = QColor(bg)
    luma = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return bg if luma > 0.28 else style.LABEL


def chip(code: str, size: int = 16) -> QPixmap:
    """상태 색 네모 위에 그 상태의 아이콘을 얹은 작은 그림."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    bg, fg = colors(code)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.scale(scale, scale)
    p.setPen(QPen(QColor(style.EDGE), 1))
    p.setBrush(QColor(bg))
    p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 3, 3)
    info = _styles.get(_key(code), {})
    png = info.get("icon_png") or b""
    glyph = _GLYPH_FOR_KEY.get(str(info.get("icon_key") or ""))
    inner = size - 4
    if png:
        icon = QPixmap()
        if icon.loadFromData(bytes(png)):
            p.drawPixmap(QRectF(2, 2, inner, inner), icon, QRectF(icon.rect()))
    elif glyph:
        p.translate(2, 2)
        p.scale(inner / 24.0, inner / 24.0)
        style.draw_icon(p, glyph, fg)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(code: str, size: int = 16) -> QIcon:
    return QIcon(chip(code, size))
