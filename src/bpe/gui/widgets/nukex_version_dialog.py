# @cursor-change: 2026-07-23, 0.8.28, NukeX 버전 선택 팝업 UX 개선(버튼 스타일 통일)
"""NukeX version picker — choose which installed Nuke opens the NK file.

설치된 NukeX가 2개 이상일 때만 모달 팝업으로 버전 버튼을 띄운다.
1개면 팝업 없이 그대로 반환, 0개면 ``None``.

UX 원칙(모달 다이얼로그 베스트 프랙티스 적용):
- 한 다이얼로그 = 한 가지 작업(버전 선택)만.
- 명확한 제목 + 간결한 안내 문구.
- 액션형 버튼 라벨(버전명 그대로), 모든 버전 버튼은 동일 스타일로 통일.
- 키보드 지원: 최신 버전에 기본 포커스(Enter 즉시 실행), Esc로 취소.
- 접근성: 버튼 최소 높이 44px, 버튼 간 충분한 간격.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nk_finder import NukexLauncher
from bpe.gui import theme

# 접근성: 터치/클릭 타깃 최소 높이 (px)
_BUTTON_MIN_HEIGHT = 44


class NukexVersionDialog(QDialog):
    """설치된 NukeX 버전을 버튼으로 보여주고 하나를 고르게 하는 모달 다이얼로그."""

    def __init__(self, parent: Optional[QWidget], launchers: Sequence[NukexLauncher]) -> None:
        super().__init__(parent)
        self.selected_launcher: Optional[NukexLauncher] = None

        self.setObjectName("NukexVersionDialog")
        self.setWindowTitle("Nuke 버전 선택")
        # 물음표(도움말) 버튼 제거 — 닫기 버튼만 남긴다.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet(
            f"""
            QDialog#NukexVersionDialog {{
                background-color: {theme.BG};
                border: 1px solid {theme.BORDER};
                border-radius: 10px;
            }}
            QLabel#nukex_dialog_title {{
                background: transparent;
                color: {theme.TEXT};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#nukex_dialog_desc {{
                background: transparent;
                color: {theme.TEXT_DIM};
                font-size: {theme.FONT_SIZE}px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(6)

        title = QLabel("Nuke 버전 선택")
        title.setObjectName("nukex_dialog_title")
        layout.addWidget(title)

        desc = QLabel("실행할 Nuke 버전을 선택하세요.")
        desc.setObjectName("nukex_dialog_desc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(14)

        # 버전 버튼(내림차순 정렬됨). 모든 버튼을 동일한 스타일로 통일.
        # 첫(최신) 버전에 기본 포커스만 두어 Enter로 바로 실행 가능하게 한다.
        for index, launcher in enumerate(launchers):
            btn = QPushButton(launcher.label)
            btn.setMinimumHeight(_BUTTON_MIN_HEIGHT)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, nl=launcher: self._choose(nl))
            if index == 0:
                btn.setDefault(True)
                btn.setAutoDefault(True)
                self._default_button = btn
            layout.addWidget(btn)
            if index < len(launchers) - 1:
                layout.addSpacing(2)  # 버튼 간 추가 간격(오클릭 방지)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        btn = getattr(self, "_default_button", None)
        if btn is not None:
            btn.setFocus()

    def _choose(self, launcher: NukexLauncher) -> None:
        self.selected_launcher = launcher
        self.accept()


def choose_nukex_launcher(
    parent: Optional[QWidget], launchers: Sequence[NukexLauncher]
) -> Optional[NukexLauncher]:
    """설치 상황에 맞게 NukeX 실행 후보를 고른다.

    - 0개 → ``None``
    - 1개 → 팝업 없이 그대로 반환
    - 2개 이상 → 모달 버전 선택 팝업. 취소(Esc/닫기) 시 ``None``.
    """
    items: List[NukexLauncher] = list(launchers)
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    dlg = NukexVersionDialog(parent, items)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.selected_launcher
    return None
