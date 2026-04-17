"""Feedback 패널/플레이어용 PNG 아이콘 경로 (소스·PyInstaller 번들).

디자인 PNG는 ``src/bpe/gui/resources/feedback/*.png`` 동일 파일명으로 교체한 뒤 빌드하면 반영된다.
저장소 기본 PNG는 개발용 플레이스홀더일 수 있다."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from bpe.core.logging import get_logger

logger = get_logger("gui.feedback_panel_png")

# 피드백 UI에서 통일하는 아이콘 픽셀 (QToolButton.setIconSize)
# 기준 32px 대비 1.2배 작게(÷1.2) — 벡터·PNG 공통
FEEDBACK_PANEL_ICON_PX = max(16, round(32 / 1.2))
# 재생바 재생/일시정지 아이콘 (기존 28px 기준 동일 비율)
FEEDBACK_MEDIA_CTL_ICON_PX = max(16, round(28 / 1.2))

_STEMS = (
    "feedback_move",
    "feedback_text",
    "feedback_pen",
    "feedback_loop",
    "feedback_clear",
    "feedback_undo",
    "feedback_fit",
)


def feedback_png_path(stem: str) -> Path:
    """``stem``은 ``feedback_text`` 처럼 확장자 없음."""
    name = stem if stem.endswith(".png") else f"{stem}.png"
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "bpe" / "gui" / "resources" / "feedback" / name)
    candidates.append(Path(__file__).resolve().parent / "resources" / "feedback" / name)
    for p in candidates:
        if p.is_file():
            return p
    return candidates[-1]


def load_feedback_panel_icon(stem: str, icon_size: int = FEEDBACK_PANEL_ICON_PX) -> QIcon:
    p = feedback_png_path(stem)
    if not p.is_file():
        logger.warning("Feedback PNG 없음: %s", p)
        return QIcon()
    pm = QPixmap(str(p))
    if pm.isNull():
        logger.warning("Feedback PNG 로드 실패: %s", p)
        return QIcon()
    side = max(16, int(icon_size))
    scaled = pm.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(scaled)


def list_expected_feedback_png_stems() -> tuple[str, ...]:
    return _STEMS


def beluca_placeholder_logo_path() -> Path:
    """프로젝트 미선택 시 뷰어 중앙용 BELUCA 로고 PNG (교체 가능)."""
    return feedback_png_path("beluca_placeholder_logo")
