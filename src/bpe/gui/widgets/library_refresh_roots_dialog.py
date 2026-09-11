"""소스 라이브러리 설정 「새로고침」 — 다시 훑을 등록 폴더를 체크로 고른다.

고른 내용은 기억하지 않는다(설정 파일을 바꾸지 않음). 매번 기본값으로 뜬다:
선택 가능한 폴더는 전부 체크, Compositing Source(팩) 폴더는 회색·선택 불가.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui import theme

_PACK_NOTE = "Compositing Source — 훑는 데 약 17분·팩 방식이라 「전체 스캔」으로 갱신"


class LibraryRefreshRootsDialog(QDialog):
    """``choices`` = ``[(root, selectable), ...]`` (등록 순서)."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        choices: Sequence[Tuple[str, bool]] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("새로고침할 폴더 선택")
        self.setMinimumSize(560, 320)
        self._boxes: List[Tuple[str, QCheckBox]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)

        title = QLabel("새로고침할 폴더 선택")
        title.setObjectName("page_title")
        root.addWidget(title)

        hint = QLabel(
            "고른 폴더를 다시 훑은 뒤 새로 찾은 것을 보여주고, 체크한 것만 추가합니다 "
            "(원본은 읽기만). 새 클립이 있을 때만 팀 공유 목록을 갱신합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_DIM, theme.FONT_SIZE_SMALL)
        )
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)
        for path, selectable in choices:
            box = QCheckBox(normalize_path_str(path))
            box.setChecked(bool(selectable))
            box.setEnabled(bool(selectable))
            box.toggled.connect(self._update_ok)
            lay.addWidget(box)
            if not selectable:
                note = QLabel(_PACK_NOTE)
                note.setStyleSheet(
                    "color: {}; font-size: {}px; padding-left: 24px;".format(
                        theme.TEXT_DIM, theme.FONT_SIZE_SMALL
                    )
                )
                lay.addWidget(note)
            self._boxes.append((path, box))
        lay.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self._ok_btn = QPushButton("새로고침")
        self._ok_btn.setProperty("primary", True)
        self._ok_btn.setFixedWidth(100)
        self._ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn.clicked.connect(self.accept)
        bottom.addWidget(self._ok_btn)
        cancel_btn = QPushButton("취소")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        root.addLayout(bottom)

        self._update_ok()

    def _update_ok(self, *_args: object) -> None:
        self._ok_btn.setEnabled(bool(self.selected_roots()))

    def selected_roots(self) -> List[str]:
        """체크된(선택 가능한) 폴더 경로 — 등록 순서 유지."""
        return [path for path, box in self._boxes if box.isEnabled() and box.isChecked()]
