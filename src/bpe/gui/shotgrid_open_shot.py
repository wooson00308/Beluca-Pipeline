"""ShotGrid에서 샷 페이지를 여는 공용 버튼 (My Tasks, Feedback 등)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import QPushButton

from bpe.core.logging import get_logger
from bpe.core.shotgrid_browser import build_shot_canvas_url, try_launch_chrome_app_url
from bpe.core.shotgrid_settings import get_shotgrid_settings
from bpe.gui import theme

logger = get_logger("gui.shotgrid_open_shot")

SHOTGRID_OPEN_BTN_PX = 27
SHOTGRID_OPEN_ICON_PX = 22
COPY_SHOT_NAME_FLASH_MS = 2000


def shotgrid_open_shot_icon_png_path() -> Path:
    """소스 실행 또는 PyInstaller 번들에서 ShotGrid 열기 버튼 PNG 경로."""
    name = "shotgrid_open.png"
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "bpe" / "gui" / "resources" / name)
    candidates.append(Path(__file__).resolve().parent / "resources" / name)
    for p in candidates:
        if p.is_file():
            return p
    return candidates[-1]


def open_shot_canvas_in_browser(shot_id: Optional[int]) -> None:
    """Chrome 앱 모드 또는 기본 브라우저로 ShotGrid 샷 캔버스 URL을 연다."""
    if shot_id is None:
        return
    sgset = get_shotgrid_settings()
    base_u = (sgset.get("base_url") or "").strip()
    page_raw = sgset.get("shot_browser_page_id", 14100)
    page_id: Any = page_raw if page_raw is not None else 14100
    chrome_ex = ""
    cx = sgset.get("chrome_executable")
    if isinstance(cx, str):
        chrome_ex = cx.strip()
    try:
        url = build_shot_canvas_url(base_u, page_id, int(shot_id))
    except ValueError as e:
        logger.warning("ShotGrid URL 생성 실패: %s", e)
        return
    if not try_launch_chrome_app_url(url, chrome_executable=chrome_ex):
        QDesktopServices.openUrl(QUrl(url))


def setup_shotgrid_open_shot_button(btn: QPushButton, shot_id: Optional[int]) -> None:
    """아이콘·스타일·툴팁·클릭을 설정한다."""
    sid: Optional[int] = None
    try:
        if shot_id is not None:
            sid = int(shot_id)
    except (TypeError, ValueError):
        sid = None
    if sid is not None and sid <= 0:
        sid = None

    btn.setFixedSize(SHOTGRID_OPEN_BTN_PX, SHOTGRID_OPEN_BTN_PX)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    _sg_style = (
        f"QPushButton {{ color: {theme.ACCENT}; background: transparent; "
        f"border: 1px solid {theme.ACCENT}; border-radius: 5px; padding: 0; "
        f"min-width: {SHOTGRID_OPEN_BTN_PX}px; min-height: {SHOTGRID_OPEN_BTN_PX}px; }}"
        f"QPushButton:hover {{ background: {theme.ACCENT}; color: {theme.BG}; }}"
        f"QPushButton:disabled {{ color: {theme.BORDER}; border-color: {theme.BORDER}; }}"
    )
    btn.setStyleSheet(_sg_style)
    _icon_png = shotgrid_open_shot_icon_png_path()
    if _icon_png.is_file():
        btn.setIcon(QIcon(str(_icon_png)))
        btn.setIconSize(QSize(SHOTGRID_OPEN_ICON_PX, SHOTGRID_OPEN_ICON_PX))
    else:
        btn.setText("SG")

    if sid is None:
        btn.setEnabled(False)
        btn.setToolTip("ShotGrid 샷 ID가 없어 웹에서 열 수 없습니다")
    else:
        btn.setToolTip("ShotGrid에서 이 샷 열기")

    btn.clicked.connect(lambda _checked=False, s=sid: open_shot_canvas_in_browser(s))


def setup_copy_shot_name_button(btn: QPushButton, shot_code: Optional[str]) -> None:
    """ShotGrid 열기와 동일 크기 — 샷 코드 복사, 클릭 시 잠시 초록 피드백 후 복귀."""
    code = (shot_code or "").strip()
    btn.setFixedSize(SHOTGRID_OPEN_BTN_PX, SHOTGRID_OPEN_BTN_PX)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    normal_ss = (
        f"QPushButton {{ color: {theme.ACCENT}; background: transparent; "
        f"border: 1px solid {theme.ACCENT}; border-radius: 5px; padding: 0; "
        f"min-width: {SHOTGRID_OPEN_BTN_PX}px; min-height: {SHOTGRID_OPEN_BTN_PX}px; "
        f"font-size: 15px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: {theme.ACCENT}; color: {theme.BG}; }}"
        f"QPushButton:disabled {{ color: {theme.BORDER}; border-color: {theme.BORDER}; }}"
    )
    flash_ss = (
        f"QPushButton {{ color: #ffffff; background: {theme.SUCCESS}; "
        f"border: 1px solid {theme.SUCCESS}; border-radius: 5px; padding: 0; "
        f"min-width: {SHOTGRID_OPEN_BTN_PX}px; min-height: {SHOTGRID_OPEN_BTN_PX}px; "
        f"font-size: 15px; font-weight: 600; }}"
    )
    btn.setStyleSheet(normal_ss)
    # ⧉ (two joined squares) — 참고 UI와 유사한 복사 느낌
    btn.setText("\u29c9")
    btn.setToolTip("샷 이름 복사")

    def _restore() -> None:
        btn.setStyleSheet(normal_ss)

    def _on_click() -> None:
        if not code:
            return
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(code)
        btn.setStyleSheet(flash_ss)
        QTimer.singleShot(COPY_SHOT_NAME_FLASH_MS, _restore)

    btn.clicked.connect(_on_click)
    if not code:
        btn.setEnabled(False)
        btn.setToolTip("복사할 샷 코드가 없습니다")
