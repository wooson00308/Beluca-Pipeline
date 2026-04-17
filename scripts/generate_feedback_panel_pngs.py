"""개발용: feedback 패널 PNG 플레이스홀더 생성 (흰색·투명 배경).

디자인 PNG로 교체해도 파일명은 동일하게 유지한다."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "bpe" / "gui" / "resources" / "feedback"
PX = 64
PEN_W = 3.0
COL = QColor(232, 232, 235, 255)
# theme.ACCENT (#2D8B7A) 기반 — 벡터 전용 도구(이동·화살표 등)와 시각적으로 구분되게 한다
_BG = QColor(45, 139, 122, 52)


def _base() -> QImage:
    img = QImage(PX, PX, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    return img


def _pill_background(p: QPainter) -> None:
    """PNG 아이콘만 살짝 틴트된 라운드 배경(벡터 아이콘과 구분)."""
    m = max(2, PX // 12)
    r = PX // 4
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_BG)
    p.drawRoundedRect(QRectF(float(m), float(m), float(PX - 2 * m), float(PX - 2 * m)), r, r)


def _pen_like(p: QPainter) -> None:
    pen = QPen(COL)
    pen.setWidthF(PEN_W)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)


def draw_text() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    m = PX // 8
    p.drawLine(m, m * 2, m, PX - m)
    p.drawLine(m // 2, m * 2, PX // 2 + m, m * 2)
    p.drawLine(m // 2, PX // 2, PX * 5 // 8, PX // 2)
    p.end()
    img.save(str(OUT / "feedback_text.png"), "PNG")


def draw_pen() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    p.drawLine(PX * 14 // 16, PX * 2 // 16, PX * 5 // 16, PX * 11 // 16)
    p.drawLine(PX * 5 // 16, PX * 11 // 16, PX * 3 // 16, PX * 14 // 16)
    p.end()
    img.save(str(OUT / "feedback_pen.png"), "PNG")


def draw_loop() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    inset = PX // 5
    r = PX - 2 * inset
    p.drawRoundedRect(inset, inset, r, r, PX // 8, PX // 8)
    p.drawLine(PX * 11 // 16, inset + 1, PX * 13 // 16, inset + r // 3)
    p.drawLine(PX * 11 // 16, inset + 1, PX * 9 // 16, inset + r // 3)
    p.drawLine(PX * 5 // 16, inset + r - 1, PX * 3 // 16, inset + r * 2 // 3)
    p.drawLine(PX * 5 // 16, inset + r - 1, PX * 7 // 16, inset + r * 2 // 3)
    p.end()
    img.save(str(OUT / "feedback_loop.png"), "PNG")


def draw_clear() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    c = PX // 2
    rad = PX * 6 // 16
    p.drawEllipse(QPointF(float(c), float(c)), float(rad), float(rad))
    d = rad * 0.55
    p.drawLine(int(c - d), int(c - d), int(c + d), int(c + d))
    p.drawLine(int(c - d), int(c + d), int(c + d), int(c - d))
    p.end()
    img.save(str(OUT / "feedback_clear.png"), "PNG")


def draw_undo() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    rect = QRectF(PX * 0.28, PX * 0.32, PX * 0.5, PX * 0.38)
    p.drawArc(rect, 45 * 16, 200 * 16)
    ax, ay = PX * 0.28, PX * 0.38
    p.drawLine(int(ax), int(ay), int(ax + PX * 0.12), int(ay))
    p.drawLine(int(ax), int(ay), int(ax + PX * 0.06), int(ay - PX * 0.1))
    p.end()
    img.save(str(OUT / "feedback_undo.png"), "PNG")


def draw_fit() -> None:
    img = _base()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pill_background(p)
    _pen_like(p)
    inset = PX // 5
    w = PX - 2 * inset
    p.drawRect(inset, inset, w, w)
    corner = PX // 10
    for dx, dy in ((0, 0), (w - corner, 0), (0, w - corner), (w - corner, w - corner)):
        x0, y0 = inset + dx, inset + dy
        if dx == 0 and dy == 0:
            p.drawLine(x0, y0 + corner, x0, y0)
            p.drawLine(x0, y0, x0 + corner, y0)
        elif dx > 0 and dy == 0:
            p.drawLine(x0 + corner, y0, x0 + corner, y0)
            p.drawLine(x0, y0, x0 + corner, y0)
        elif dx == 0:
            p.drawLine(x0, y0, x0, y0 + corner)
            p.drawLine(x0, y0 + corner, x0 + corner, y0 + corner)
        else:
            p.drawLine(x0 + corner, y0 + corner, x0 + corner, y0)
            p.drawLine(x0 + corner, y0 + corner, x0, y0 + corner)
    p.end()
    img.save(str(OUT / "feedback_fit.png"), "PNG")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_text()
    draw_pen()
    draw_loop()
    draw_clear()
    draw_undo()
    draw_fit()
    print("Wrote PNGs to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
