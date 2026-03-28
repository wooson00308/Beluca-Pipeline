"""Tools tab — toggle switches for Nuke helper tools."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bpe.core.settings import get_tools_settings, save_tools_settings
from bpe.gui import theme
from bpe.gui.widgets.toggle_switch import ToggleSwitch

_TOOL_DEFS = [
    {
        "key": "qc_checker",
        "title": "QC Checker — 렌더 전 자동 점검",
        "subtitle": (
            "Write 렌더 시작 직전에 FPS/해상도/OCIO/컬러스페이스/"
            "플레이트-편집본 길이 불일치를 팝업으로 알려줍니다."
        ),
        "detail": ("활성화 시: Nuke의 모든 Write 노드 렌더 직전에 체크리스트 팝업이 표시됩니다."),
    },
    {
        "key": "post_render_viewer",
        "title": "Post-Render Viewer — 렌더 후 NK 자동 로드",
        "subtitle": ("렌더 완료 후 Write 노드 출력 경로의 시퀀스를 Read 노드로 자동 생성합니다."),
        "detail": (
            "활성화 시: 렌더가 끝나면 'bpe_render_preview' Read 노드가 자동으로 생성됩니다."
        ),
    },
]


def _tools_body_font() -> QFont:
    """QSS 복합 폰트 대신 단일 패밀리+픽셀 크기로 줄바꿈 높이 안정화."""
    f = QFont()
    f.setPixelSize(theme.FONT_SIZE_SMALL)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    if sys.platform == "win32":
        f.setFamily("Segoe UI")
    else:
        first = theme.FONT_FAMILY.split(",")[0].strip().strip('"')
        f.setFamily(first or "sans-serif")
    return f


class ToolsTab(QWidget):
    """Tools — toggle switches for Nuke convenience hooks."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("tools_tab")
        self._switches: Dict[str, ToggleSwitch] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(theme.CONTENT_MARGIN, 24, theme.CONTENT_MARGIN, 0)
        hdr.setSpacing(12)
        title = QLabel("Tools")
        title.setObjectName("page_title")
        subtitle = QLabel("Nuke 렌더 도구 설정")
        subtitle.setObjectName("page_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignBottom)
        hdr.addWidget(title)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)

        # Banner
        banner = QLabel(
            "스위치를 켠 뒤, Nuke에서 setup_pro → BPE Tools → "
            "Reload Tool Hooks를 한 번 실행해야 적용됩니다."
        )
        banner.setObjectName("page_subtitle")
        banner.setWordWrap(True)
        banner.setContentsMargins(theme.CONTENT_MARGIN, 12, theme.CONTENT_MARGIN, 4)
        root.addWidget(banner)

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        card_container = QWidget()
        card_layout = QVBoxLayout(card_container)
        card_layout.setContentsMargins(
            theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN, theme.CONTENT_MARGIN
        )
        card_layout.setSpacing(theme.FORM_SPACING)

        tools_cfg = get_tools_settings()

        for defn in _TOOL_DEFS:
            card = self._build_tool_card(defn, tools_cfg)
            card.setMaximumWidth(600)
            # Vertical Fixed locks height to an early (wrong) hint for word-wrapped QLabels.
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            card_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignLeft)

        card_layout.addStretch()
        scroll.setWidget(card_container)
        root.addWidget(scroll, 1)

    def _build_tool_card(self, defn: Dict[str, str], tools_cfg: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("tools_card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 클릭형 온/오프 토글 (paintEvent; QSlider 아님)
        switch = ToggleSwitch()
        key = defn["key"]
        switch.setObjectName(f"bpe_tool_switch_{key}")
        enabled = bool(tools_cfg.get(key, {}).get("enabled", False))
        switch.setAccessibleName(defn["title"])
        switch.blockSignals(True)
        switch.setChecked(enabled)
        switch.blockSignals(False)
        switch.toggled.connect(lambda c, k=key: self._on_toggle(k, c))
        self._switches[key] = switch
        layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)

        # 텍스트 열: 상단 정렬 래퍼 + QFont로 본문 지정(QSS 복합 폰트보다 줄바꿈 높이 안정)
        text_wrap = QWidget()
        text_wrap.setMinimumWidth(280)
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)

        title_lbl = QLabel(defn["title"])
        title_lbl.setObjectName("tools_title")
        title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        text_col.addWidget(title_lbl)

        body_font = _tools_body_font()
        sub_lbl = QLabel(defn["subtitle"])
        sub_lbl.setObjectName("tools_body_text")
        sub_lbl.setFont(body_font)
        sub_lbl.setTextFormat(Qt.TextFormat.PlainText)
        sub_lbl.setWordWrap(True)
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sub_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        text_col.addWidget(sub_lbl)

        detail_lbl = QLabel(defn["detail"])
        detail_lbl.setObjectName("tools_body_text")
        detail_lbl.setFont(body_font)
        detail_lbl.setTextFormat(Qt.TextFormat.PlainText)
        detail_lbl.setWordWrap(True)
        detail_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        detail_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        text_col.addWidget(detail_lbl)

        layout.addWidget(text_wrap, 1, Qt.AlignmentFlag.AlignTop)
        return card

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_toggle(self, key: str, checked: bool) -> None:
        tools_cfg = get_tools_settings()
        tools_cfg.setdefault(key, {})["enabled"] = checked
        save_tools_settings(tools_cfg)
