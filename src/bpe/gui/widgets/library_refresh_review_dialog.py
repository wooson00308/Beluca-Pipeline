"""소스 라이브러리 「새로고침」 결과 — 새로 찾은 폴더를 보여주고 체크한 것만 추가한다.

한 줄 = 등록 폴더 바로 아래 폴더(촬영일 폴더) 하나. 판정·적용 로직은 core 에 있고
이 창은 보여주고 고르게만 한다.
"""

from __future__ import annotations

from typing import List, Sequence, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.core.source_library_refresh import (
    GROUP_EXISTING,
    GROUP_NEW,
    GROUP_UNORGANIZED,
    GroupKey,
    RefreshGroup,
)
from bpe.gui import theme

_KIND_LABEL = {GROUP_NEW: "새 폴더", GROUP_EXISTING: "기존 폴더", GROUP_UNORGANIZED: "분류 안 됨"}


def count_text(group: RefreshGroup) -> str:
    """개수 문구 — 새/분류 안 됨은 「클립 N개」, 기존은 「클립 +N · −N · 변경 N」."""
    if group.kind in (GROUP_NEW, GROUP_UNORGANIZED):
        return "클립 {:,}개".format(group.clips)
    parts: List[str] = []
    if group.added:
        parts.append("+{:,}".format(group.added))
    if group.removed:
        parts.append("−{:,}".format(group.removed))
    if group.changed:
        parts.append("변경 {:,}".format(group.changed))
    return "클립 " + " · ".join(parts) if parts else "변경"


class LibraryRefreshReviewDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        groups: Sequence[RefreshGroup],
        *,
        read_failures: int = 0,
        multi_root: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("새로 찾은 것 — 체크한 것만 추가")
        self.setMinimumSize(640, 380)
        self._rows: List[Tuple[RefreshGroup, QCheckBox]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)
        title = QLabel("새로 찾은 것 — 체크한 것만 추가")
        title.setObjectName("page_title")
        root.addWidget(title)
        hint = QLabel(
            "「새 폴더」·「분류 안 됨」은 체크하면 옆 폴더들과 같은 분류에 자동으로 들어갑니다. "
            "체크하지 않은 폴더는 손대지 않으며 다음 새로고침 때 다시 나옵니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_DIM, theme.FONT_SIZE_SMALL)
        )
        root.addWidget(hint)
        if int(read_failures) > 0:
            warn = QLabel(
                "폴더 {}개를 읽지 못했습니다 — 추가해도 팀 공유는 보류되고 "
                "이 PC에만 반영됩니다.".format(int(read_failures))
            )
            warn.setWordWrap(True)
            warn.setObjectName("log_title")
            root.addWidget(warn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for i, g in enumerate(groups):
            box = QCheckBox(g.category or "(루트 바로 아래 파일)")
            box.setChecked(True)
            box.toggled.connect(self._update_footer)
            grid.addWidget(box, i, 0)
            if multi_root:
                where = QLabel(g.root.rsplit("/", 1)[-1])
                where.setStyleSheet("color: {};".format(theme.TEXT_DIM))
                grid.addWidget(where, i, 1)
            kind = QLabel(_KIND_LABEL.get(g.kind, g.kind))
            kind.setStyleSheet("color: {};".format(theme.TEXT_LABEL))
            grid.addWidget(kind, i, 2)
            grid.addWidget(QLabel(count_text(g)), i, 3)
            self._rows.append((g, box))
        grid.setColumnStretch(4, 1)
        grid.setRowStretch(len(groups), 1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self._footer = QLabel("")
        self._footer.setObjectName("status_msg")
        bottom.addWidget(self._footer)
        bottom.addStretch()
        self._ok_btn = QPushButton("추가")
        self._ok_btn.setProperty("primary", True)
        self._ok_btn.setFixedWidth(100)
        self._ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn.clicked.connect(self.accept)
        bottom.addWidget(self._ok_btn)
        cancel = QPushButton("취소")
        cancel.setFixedWidth(80)
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        root.addLayout(bottom)
        self._update_footer()

    def _update_footer(self, *_args: object) -> None:
        n = len(self.selected_keys())
        self._footer.setText("총 {}개 폴더 선택".format(n))
        self._ok_btn.setEnabled(n > 0)

    def selected_keys(self) -> Set[GroupKey]:
        return {g.key for g, box in self._rows if box.isChecked()}
