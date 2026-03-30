"""Splash screen — shown during app startup with progress animation."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from bpe import __version__

# ── 상수 ─────────────────────────────────────────────────────────────
W, H = 460, 280

BG = QColor("#1c1c1e")
BORDER = QColor("#3a3a3c")
ACC = QColor("#2D8B7A")
DIM = QColor("#86868b")
TEXT_LIGHT = QColor("#f5f5f7")
BAR_BG = QColor("#2c2c2e")

_STEPS: List[str] = [
    "프리셋 데이터 불러오는 중...",
    "UI 컴포넌트 초기화 중...",
    "색상 관리 설정 확인 중...",
    "BELUCA Pipeline Engine 시작 중...",
]


class SplashScreen(QWidget):
    """Frameless animated splash screen (PySide6 port of legacy tkinter version)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)

        # 화면 중앙 배치
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - W) // 2,
                geo.y() + (geo.height() - H) // 2,
            )

        # 애니메이션 상태
        self._alpha = 0.0
        self._prog = 0.0
        self._step_i = 0
        self._dot_i = 0
        self._phase = "fade_in"  # fade_in → animate → hold → fade_out → done

        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._on_finished = None

    # ── 외부 인터페이스 ─────────────────────────────────────────────
    def on_finished(self, callback) -> None:
        """스플래시 종료 후 호출할 콜백 등록."""
        self._on_finished = callback

    # ── 타이머 틱 ───────────────────────────────────────────────────
    def _tick(self) -> None:
        if self._phase == "fade_in":
            self._alpha = min(self._alpha + 0.07, 1.0)
            if self._alpha >= 1.0:
                self._phase = "animate"
                self._timer.setInterval(25)

        elif self._phase == "animate":
            self._prog = min(self._prog + 0.008, 1.0)
            step_th = min(int(self._prog * len(_STEPS)), len(_STEPS) - 1)
            if step_th != self._step_i:
                self._step_i = step_th
            self._dot_i = (self._dot_i + 1) % (4 * 4)
            if self._prog >= 1.0:
                self._phase = "hold"
                self._hold_count = 0

        elif self._phase == "hold":
            self._hold_count += 1
            if self._hold_count > 14:  # ~350ms
                self._phase = "fade_out"

        elif self._phase == "fade_out":
            self._alpha = max(self._alpha - 0.10, 0.0)
            if self._alpha <= 0.0:
                self._phase = "done"
                self._timer.stop()
                self.close()
                if self._on_finished:
                    self._on_finished()
                return

        self.setWindowOpacity(self._alpha)
        self.update()

    # ── 렌더링 ──────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 배경 + 테두리
        p.setPen(QPen(BORDER, 1))
        p.setBrush(BG)
        p.drawRoundedRect(QRect(0, 0, W - 1, H - 1), 8, 8)

        # ── 브랜드 ──────────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        brand_font = QFont(self.font())
        brand_font.setPixelSize(22)
        brand_font.setWeight(QFont.Weight.Bold)
        p.setFont(brand_font)
        p.setPen(TEXT_LIGHT)
        p.drawText(30, 42, "BELUCA")

        sub_font = QFont(self.font())
        sub_font.setPixelSize(11)
        p.setFont(sub_font)
        p.setPen(DIM)
        p.drawText(30, 64, "Pipeline Engine")

        # 버전 (오른쪽 상단)
        ver_font = QFont(self.font())
        ver_font.setPixelSize(10)
        p.setFont(ver_font)
        p.setPen(DIM)
        ver_text = f"v{__version__}"
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(ver_text)
        p.drawText(W - 20 - tw, 32, ver_text)

        # ── 구분선 ──────────────────────────────────────────────────
        p.setPen(QPen(BORDER, 1))
        p.drawLine(30, 90, W - 30, 90)

        # ── 슬로건 ──────────────────────────────────────────────────
        slogan_font = QFont(self.font())
        slogan_font.setPixelSize(11)
        p.setFont(slogan_font)
        p.setPen(DIM)
        slogan = "VFX Pipeline Preset & Shot Builder"
        stw = fm.horizontalAdvance(slogan)
        p.drawText((W - stw) // 2, 126, slogan)

        # ── 프로그레스 바 ───────────────────────────────────────────
        bar_x0, bar_y0 = 30, 168
        bar_x1, bar_y1 = W - 30, 180
        bar_w = bar_x1 - bar_x0

        # 배경
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BAR_BG)
        p.drawRoundedRect(QRect(bar_x0, bar_y0, bar_w, bar_y1 - bar_y0), 6, 6)

        # 채움
        fill_w = int(bar_w * self._prog)
        if fill_w > 0:
            p.setBrush(ACC)
            p.drawRoundedRect(QRect(bar_x0, bar_y0, fill_w, bar_y1 - bar_y0), 6, 6)

        # ── 상태 텍스트 ─────────────────────────────────────────────
        status_font = QFont(self.font())
        status_font.setPixelSize(10)
        p.setFont(status_font)
        p.setPen(DIM)
        status = "준비 완료!" if self._prog >= 1.0 else _STEPS[self._step_i]
        p.drawText(30, 204, status)

        # ── 도트 애니메이션 ─────────────────────────────────────────
        dot_y = H - 38
        active_dot = self._dot_i // 4
        for i in range(4):
            ox = W // 2 - 24 + i * 16
            color = ACC if i == active_dot else BORDER
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(ox, dot_y, 8, 8)

        # ── 저작권 ──────────────────────────────────────────────────
        copy_font = QFont(self.font())
        copy_font.setPixelSize(8)
        p.setFont(copy_font)
        p.setPen(BORDER)
        copy_text = "\u00a9 2025 BELUCA  |  All rights reserved"
        ctw = p.fontMetrics().horizontalAdvance(copy_text)
        p.drawText((W - ctw) // 2, H - 10, copy_text)

        p.end()
