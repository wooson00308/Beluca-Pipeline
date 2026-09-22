"""추석 시즌 장식 — 사이드바 왼쪽 아래(버전 표시 위) 떡방아 토끼.

평소엔 그림만 보이고, 누르면 떡방아를 두 번 찧으며 말풍선 인사가 나온다.
인사말과 말풍선 등장 방식은 누를 때마다 순서대로 바뀐다.
표시 기간·인사말·도트 그림 데이터는 ``bpe.core.seasonal`` 에 있다.

레이아웃 안에는 빈 자리(``_Slot``)만 두고, 실제 그림과 말풍선은 창 중앙 위젯 위에
겹쳐 그린다. 그래서 말풍선이 사이드바 밖으로 나가도 잘리지 않는다.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QElapsedTimer,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QBoxLayout, QSizePolicy, QWidget

from bpe.core import seasonal
from bpe.core.logging import get_logger
from bpe.gui import theme

logger = get_logger("gui.widgets.seasonal_mascot")

_SCALE = 2  # 도트 1칸 = 화면 2px
_SPRITE_W = 30 * _SCALE
_SPRITE_H = 22 * _SCALE
_SLOT_GAP = 20  # 사이드바 왼쪽 여백 (버전 글자와 같은 선)
_SLOT_H = _SPRITE_H
_SLOT_W = _SLOT_GAP + _SPRITE_W

_BUBBLE_DELAY_MS = 230
_BUBBLE_HIDE_MS = 2600
_BUBBLE_OUT_MS = 180
_PARTICLE_MS = 800
_BOB_MS = 120
_TICK_MS = 16
_DEBOUNCE_MS = 300
_BUBBLE_MAX_TEXT_W = 256
_TAIL_X = 22  # 말풍선 왼쪽에서 꼬리 시작까지
_BUBBLE_LEFT_SHIFT = 12  # 말풍선 왼쪽 = 토끼 왼쪽 - 12

# 등장 방식: (이름, 길이 ms, 키프레임[(진행률, 가로배율, 세로배율, 위아래 px, 회전°, 불투명도)])
_Frame = Tuple[float, float, float, float, float, float]
_ENTRANCES: Tuple[Tuple[str, int, Tuple[_Frame, ...]], ...] = (
    (
        "pop",
        320,
        (
            (0, 0.3, 0.3, 0, 0, 0),
            (0.6, 1.12, 1.12, 0, 0, 1),
            (0.8, 0.96, 0.96, 0, 0, 1),
            (1, 1, 1, 0, 0, 1),
        ),
    ),
    (
        "jump",
        380,
        (
            (0, 0.6, 0.6, 10, 0, 0),
            (0.35, 0.92, 1.08, -10, 0, 1),
            (0.6, 1.1, 0.9, 0, 0, 1),
            (0.8, 0.97, 1.03, -3, 0, 1),
            (1, 1, 1, 0, 0, 1),
        ),
    ),
    (
        "wobble",
        380,
        (
            (0, 0.5, 0.5, 0, -6, 0),
            (0.3, 1.05, 1.05, 0, 4, 1),
            (0.55, 1, 1, 0, -2, 1),
            (0.75, 1, 1, 0, 1, 1),
            (1, 1, 1, 0, 0, 1),
        ),
    ),
    (
        "mochi",
        360,
        (
            (0, 1.25, 0.7, 0, 0, 0),
            (0.45, 0.9, 1.12, 0, 0, 1),
            (0.75, 1.04, 0.97, 0, 0, 1),
            (1, 1, 1, 0, 0, 1),
        ),
    ),
    ("moonrise", 380, ((0, 0.85, 0.85, 14, 0, 0), (0.7, 1, 1, -2, 0, 1), (1, 1, 1, 0, 0, 1))),
)
_PARTICLES = ("pt_pink", "pt_white", "pt_green")


def _ease(t: float) -> float:
    """구간 안 부드러운 보간 (smoothstep)."""
    return t * t * (3 - 2 * t)


def _sample(frames: Tuple[_Frame, ...], p: float) -> _Frame:
    """키프레임 사이 값을 진행률 p(0~1)로 보간."""
    if p <= frames[0][0]:
        return frames[0]
    for a, b in zip(frames, frames[1:]):
        if p <= b[0]:
            t = _ease((p - a[0]) / max(1e-6, b[0] - a[0]))
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(6))  # type: ignore[return-value]
    return frames[-1]


def sprite_image(name: str) -> QImage:
    """도트 격자 하나를 1칸=1px 이미지로 만든다."""
    rows = seasonal.CHUSEOK_SPRITES[name]
    img = QImage(len(rows[0]), len(rows), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    colors: Dict[str, QColor] = {k: QColor(v) for k, v in seasonal.CHUSEOK_PALETTE.items()}
    for y, row in enumerate(rows):
        for x, key in enumerate(row):
            if key != ".":
                img.setPixelColor(x, y, colors[key])
    return img


def _sprite_pixmap(name: str, dpr: float) -> QPixmap:
    img = sprite_image(name)
    w = int(round(img.width() * _SCALE * dpr))
    h = int(round(img.height() * _SCALE * dpr))
    pm = QPixmap.fromImage(
        img.scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation
        )
    )
    pm.setDevicePixelRatio(dpr)
    return pm


class _Slot(QWidget):
    """툴바 줄 안의 빈 자리. 위치가 바뀌면 겹쳐 그린 토끼를 따라 옮긴다.

    최소 폭이 0 이라 툴바 최소 폭(=창 최소 폭)을 늘리지 않는다. 창이 좁아
    자리가 줄어들면 토끼를 숨긴다.
    """

    def __init__(self, owner: "ChuseokMascot", parent: QWidget) -> None:
        super().__init__(parent)
        self._owner = owner
        self.setMinimumSize(0, _SLOT_H)
        self.setMaximumSize(_SLOT_W, _SLOT_H)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(_SLOT_W, _SLOT_H)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(0, _SLOT_H)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        super().moveEvent(event)
        self._owner.sync_geometry()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._owner.sync_geometry()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._owner.sync_geometry()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self._owner.sync_geometry()


class _FxLayer(QWidget):
    """말풍선·송편 조각을 그리는 투명 층 (마우스 클릭은 통과)."""

    def __init__(self, owner: "ChuseokMascot", parent: QWidget) -> None:
        super().__init__(parent)
        self._owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._owner.paint_fx(p, self)
        p.end()


class ChuseokMascot(QWidget):
    """떡방아 토끼 (탭 위에 겹쳐 그리는 버튼)."""

    def __init__(self, overlay_parent: QWidget) -> None:
        super().__init__(overlay_parent)
        self._tab = overlay_parent
        self._slot = _Slot(self, overlay_parent)
        self._fx = _FxLayer(self, overlay_parent)
        self._fx.hide()

        self.setFixedSize(_SPRITE_W, _SPRITE_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("추석 인사 보기")
        self.setAccessibleName("추석 인사 보기")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._pixmaps: Dict[Tuple[str, float], QPixmap] = {}
        self._frame = "up"
        self._hover = False
        self._kbd_focus = False  # 키보드(Tab)로 선택했을 때만 테두리 표시
        self._greet_idx = 0
        self._mode_idx = 0
        self._text = ""
        self._mode = _ENTRANCES[0]
        self._particles: List[Tuple[int, str, float, float]] = []
        self._clock = QElapsedTimer()
        self._last_click = -_DEBOUNCE_MS
        self._since_start = QElapsedTimer()
        self._since_start.start()
        self._playing = False

        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._on_tick)

        # 날짜 확인: 1분마다 (자정 넘김·절전 복귀 모두 대응)
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self.refresh_visibility)
        self._day_timer.start()

        self.hide()
        self.refresh_visibility()

    # ── 배치 ───────────────────────────────────────────────────────
    @property
    def slot(self) -> QWidget:
        return self._slot

    def refresh_visibility(self, today: Optional[date] = None) -> None:
        day = today or date.today()
        active = seasonal.is_chuseok_active(day)
        if not active:
            self._stop()
        self._slot.setVisible(active)
        if day > seasonal.CHUSEOK_END:
            self._day_timer.stop()
        self.sync_geometry()

    def sync_geometry(self) -> None:
        if not self._slot.isVisible() or self._slot.width() < _SLOT_W:
            self.hide()
            self._fx.hide()
            return
        top_left = self._slot.mapTo(self._tab, QPoint(_SLOT_GAP, 0))
        y = top_left.y() + (self._slot.height() - _SPRITE_H) // 2
        self.move(top_left.x(), y)
        self.show()
        self.raise_()
        fx_left = max(0, self.x() - 40)
        fx_top = max(0, self.y() - 140)
        self._fx.setGeometry(QRect(fx_left, fx_top, 380, self.y() + _SPRITE_H + 40 - fx_top))
        if self._playing:
            self._fx.show()
            self._fx.raise_()

    # ── 그리기 ─────────────────────────────────────────────────────
    def _pix(self, name: str) -> QPixmap:
        dpr = self.devicePixelRatioF()
        key = (name, dpr)
        pm = self._pixmaps.get(key)
        if pm is None:
            pm = _sprite_pixmap(name, dpr)
            self._pixmaps[key] = pm
        return pm

    def _bob_offset(self, ms: int) -> int:
        if not self._playing:
            return -1 if self._hover else 0
        for start, name in seasonal.POUND_SEQUENCE:
            if name == "down" and start <= ms < start + _BOB_MS:
                return 1
        return 0

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        p = QPainter(self)
        ms = self._clock.elapsed() if self._playing else 0
        p.drawPixmap(0, self._bob_offset(ms), self._pix(self._frame))
        if self.hasFocus() and self._kbd_focus:
            pen = QPen(QColor(theme.ACCENT))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 6, 6)
        p.end()

    def _bubble_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(theme.FONT_SIZE)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def paint_fx(self, p: QPainter, layer: QWidget) -> None:
        ms = self._clock.elapsed()
        origin = self.pos() - layer.pos()
        # 송편 조각
        for spawn, name, dx, up in self._particles:
            t = (ms - spawn) / _PARTICLE_MS
            if not 0 <= t <= 1:
                continue
            if t < 0.45:
                k = _ease(t / 0.45)
                ox, oy, op = dx * 0.6 * k, up * k, 1.0
            else:
                k = _ease((t - 0.45) / 0.55)
                ox = dx * 0.6 + (dx - dx * 0.6) * k
                oy = up + (10 - up) * k
                op = 1.0 - k
            p.setOpacity(op)
            p.drawPixmap(QPointF(origin.x() + 32 + ox, origin.y() + 24 + oy), self._pix(name))
        p.setOpacity(1.0)
        # 말풍선
        if ms < _BUBBLE_DELAY_MS or not self._text:
            return
        if ms < _BUBBLE_HIDE_MS:
            _, dur, frames = self._mode
            sx, sy, dy, rot, op = _sample(frames, min(1.0, (ms - _BUBBLE_DELAY_MS) / dur))[1:]
        else:
            t = min(1.0, (ms - _BUBBLE_HIDE_MS) / _BUBBLE_OUT_MS)
            s = 1.0 - t * t
            sx = sy = max(0.0, s)
            dy = rot = 0.0
            op = 1.0 if t < 0.6 else 1.0 - (t - 0.6) / 0.4
        if op <= 0 or sx <= 0:
            return
        self._draw_bubble(p, origin, sx, sy, dy, rot, op)

    def _draw_bubble(
        self, p: QPainter, origin: QPoint, sx: float, sy: float, dy: float, rot: float, op: float
    ) -> None:
        font = self._bubble_font()
        fm = QFontMetrics(font)
        flags = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)
        text_rect = fm.boundingRect(QRect(0, 0, _BUBBLE_MAX_TEXT_W, 1000), flags, self._text)
        bw = text_rect.width() + 24
        bh = text_rect.height() + 14
        left = origin.x() - _BUBBLE_LEFT_SHIFT
        tail_h = 6
        below = origin.y() - 2 - tail_h - bh < 2  # 위쪽 공간이 없으면 아래로 뒤집기
        if below:
            top = origin.y() + _SPRITE_H + 2 + tail_h
            pivot = QPointF(left + _TAIL_X + 5, top - tail_h)
        else:
            top = origin.y() - 2 - tail_h - bh
            pivot = QPointF(left + _TAIL_X + 5, top + bh + tail_h)

        p.save()
        p.setOpacity(op)
        p.translate(pivot.x(), pivot.y() + dy)
        p.rotate(rot)
        p.scale(sx, sy)
        p.translate(-pivot.x(), -pivot.y())

        bg = QColor(seasonal.BUBBLE_BG)
        border = QColor(seasonal.BUBBLE_BORDER)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 그림자
        shadow = QPainterPath()
        shadow.addRoundedRect(QRectF(left + 1, top + 3, bw, bh), 12, 12)
        p.fillPath(shadow, QColor(0, 0, 0, 90))
        body = QPainterPath()
        body.addRoundedRect(QRectF(left + 1, top + 1, bw - 2, bh - 2), 11, 11)
        pen = QPen(border)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(bg)
        p.drawPath(body)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # 도트 계단 꼬리 (테두리색 10/6/2px, 안쪽 크림색)
        p.setPen(Qt.PenStyle.NoPen)
        tx = left + _TAIL_X
        if below:
            steps = ((4, 2), (2, 6), (0, 10))
            y0 = top - tail_h
        else:
            steps = ((0, 10), (2, 6), (4, 2))
            y0 = top + bh
        for i, (off, w) in enumerate(steps):
            p.fillRect(QRect(tx + off, y0 + i * 2, w, 2), border)
        cream_y = top - 2 if below else top + bh - 2
        p.fillRect(QRect(tx + 1, cream_y, 8, 2), bg)
        p.fillRect(QRect(tx + 3, cream_y + (-2 if below else 2), 4, 2), bg)
        # 글자
        p.setFont(font)
        p.setPen(QColor(seasonal.BUBBLE_TEXT))
        p.drawText(QRect(left + 12, top + 7, bw - 24, bh - 14), flags, self._text)
        p.restore()

    # ── 동작 ───────────────────────────────────────────────────────
    def play(self) -> None:
        now = self._since_start.elapsed()
        if now - self._last_click < _DEBOUNCE_MS:
            return
        self._last_click = now
        self._text = seasonal.CHUSEOK_GREETINGS[self._greet_idx]
        self._mode = _ENTRANCES[self._mode_idx]
        self._greet_idx = seasonal.next_index(self._greet_idx, len(seasonal.CHUSEOK_GREETINGS))
        self._mode_idx = seasonal.next_index(self._mode_idx, len(_ENTRANCES))
        self._particles = []
        for start, name in seasonal.POUND_SEQUENCE:
            if name == "down":
                for i, pt in enumerate(_PARTICLES):
                    dx = (i - 1) * 16 + random.uniform(-4, 4) + 6
                    up = -22 - random.uniform(0, 10)
                    self._particles.append((start, pt, dx, up))
        self._clock.start()
        self._playing = True
        self._fx.show()
        self._fx.raise_()
        self.raise_()
        self._tick.start()
        self._on_tick()

    def _stop(self) -> None:
        self._tick.stop()
        self._playing = False
        self._frame = "up"
        self._fx.hide()
        self.update()

    def _on_tick(self) -> None:
        ms = self._clock.elapsed()
        frame = "up"
        for start, name in seasonal.POUND_SEQUENCE:
            if ms >= start:
                frame = name
        self._frame = frame
        self.update()
        self._fx.update()
        end = max(_BUBBLE_HIDE_MS + _BUBBLE_OUT_MS, seasonal.POUND_SEQUENCE[-1][0] + _PARTICLE_MS)
        if ms > end + 20:
            self._stop()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.play()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.play()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self._kbd_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
        )
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self.update()
        super().focusOutEvent(event)


def add_chuseok_mascot(
    overlay_parent: QWidget, layout: QBoxLayout, index: int = -1
) -> Optional[ChuseokMascot]:
    """``layout`` 의 ``index`` 위치에 추석 토끼 자리를 넣는다. 기간 밖이면 자리는 숨겨진다.

    ``overlay_parent`` 는 그림·말풍선을 겹쳐 그릴 위젯(레이아웃이 속한 위젯의 조상)이다.
    """
    try:
        mascot = ChuseokMascot(overlay_parent)
    except Exception:  # 장식 실패가 창 전체를 막지 않도록
        logger.exception("추석 장식 생성 실패 — 건너뜀")
        return None
    layout.insertWidget(index, mascot.slot, 0, Qt.AlignmentFlag.AlignLeft)
    return mascot


__all__ = ["ChuseokMascot", "add_chuseok_mascot", "sprite_image"]
