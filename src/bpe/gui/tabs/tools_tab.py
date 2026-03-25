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
    QVBoxLayout,
    QWidget,
)

from bpe.core.settings import get_tools_settings, save_tools_settings


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

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(28, 24, 28, 0)
        title = QLabel("Tools")
        title.setProperty("class", "title")
        subtitle = QLabel("Nuke 편의기능 온/오프 관리")
        subtitle.setProperty("dim", True)
        hdr.addWidget(title)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)

        # Banner
        banner = QLabel(
            "스위치를 켠 뒤, Nuke에서 setup_pro → BPE Tools → "
            "Reload Tool Hooks를 한 번 실행해야 적용됩니다."
        )
        banner.setProperty("dim", True)
        banner.setWordWrap(True)
        banner.setContentsMargins(28, 12, 28, 4)
        root.addWidget(banner)

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        card_container = QWidget()
        card_layout = QVBoxLayout(card_container)
        card_layout.setContentsMargins(20, 8, 20, 16)
        card_layout.setSpacing(12)

        tools_cfg = get_tools_settings()

        for defn in _TOOL_DEFS:
            card = self._build_tool_card(defn, tools_cfg)
            card_layout.addWidget(card)

        card_layout.addStretch()
        scroll.setWidget(card_container)
        root.addWidget(scroll, 1)

    def _build_tool_card(
        self, defn: Dict[str, str], tools_cfg: Dict[str, Any]
    ) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setProperty("class", "card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)

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
        title_lbl.setStyleSheet("font-weight: bold;")
        text_col.addWidget(title_lbl)

        sub_lbl = QLabel(defn["subtitle"])
        sub_lbl.setWordWrap(True)
        sub_lbl.setProperty("dim", True)
        text_col.addWidget(sub_lbl)

        detail_lbl = QLabel(defn["detail"])
        detail_lbl.setWordWrap(True)
        detail_lbl.setProperty("dim", True)
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
