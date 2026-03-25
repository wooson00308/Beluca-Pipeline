"""Tools tab — toggle switches for Nuke helper tools."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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


_TOOL_DEFS = [
    {
        "key": "qc_checker",
        "title": "QC Checker — 렌더 전 자동 점검",
        "subtitle": (
            "Write 렌더 시작 직전에 FPS/해상도/OCIO/컬러스페이스/"
            "플레이트-편집본 길이 불일치를 팝업으로 알려줍니다."
        ),
        "detail": (
            "활성화 시: Nuke의 모든 Write 노드 렌더 직전에 "
            "체크리스트 팝업이 표시됩니다."
        ),
    },
    {
        "key": "post_render_viewer",
        "title": "Post-Render Viewer — 렌더 후 NK 자동 로드",
        "subtitle": (
            "렌더 완료 후 Write 노드 출력 경로의 시퀀스를 "
            "Read 노드로 자동 생성합니다."
        ),
        "detail": (
            "활성화 시: 렌더가 끝나면 'bpe_render_preview' "
            "Read 노드가 자동으로 생성됩니다."
        ),
    },
]


class ToolsTab(QWidget):
    """Tools — toggle switches for Nuke convenience hooks."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._switches: Dict[str, QCheckBox] = {}
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
        card_layout.setContentsMargins(theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN, theme.CONTENT_MARGIN)
        card_layout.setSpacing(theme.FORM_SPACING)

        tools_cfg = get_tools_settings()

        for defn in _TOOL_DEFS:
            card = self._build_tool_card(defn, tools_cfg)
            card.setMaximumWidth(600)
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            card_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignLeft)

        card_layout.addStretch()
        scroll.setWidget(card_container)
        root.addWidget(scroll, 1)

    def _build_tool_card(
        self, defn: Dict[str, str], tools_cfg: Dict[str, Any]
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Switch
        switch = QCheckBox()
        key = defn["key"]
        enabled = tools_cfg.get(key, {}).get("enabled", False)
        switch.setChecked(enabled)
        switch.toggled.connect(lambda checked, k=key: self._on_toggle(k, checked))
        self._switches[key] = switch
        layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title_lbl = QLabel(defn["title"])
        title_lbl.setStyleSheet(f"font-weight: 600; font-size: {theme.FONT_SIZE}px;")
        text_col.addWidget(title_lbl)

        sub_lbl = QLabel(defn["subtitle"])
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        text_col.addWidget(sub_lbl)

        detail_lbl = QLabel(defn["detail"])
        detail_lbl.setWordWrap(True)
        detail_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        text_col.addWidget(detail_lbl)

        layout.addLayout(text_col, 1)
        return card

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_toggle(self, key: str, checked: bool) -> None:
        tools_cfg = get_tools_settings()
        tools_cfg.setdefault(key, {})["enabled"] = checked
        save_tools_settings(tools_cfg)
