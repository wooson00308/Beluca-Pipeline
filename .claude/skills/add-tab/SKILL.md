---
name: add-tab
description: BPE에 새 GUI 탭을 추가할 때 사용. 탭 파일 생성, main_window 등록, 체크리스트까지 안내.
---

# 새 탭 추가하기

BPE에 새 탭을 추가할 때 따라야 할 절차.

## 1. 탭 파일 생성

`src/bpe/gui/tabs/새이름_tab.py`:

```python
from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.gui import theme


def _form_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setObjectName("form_label")
    lbl.setFixedWidth(theme.FORM_LABEL_WIDTH)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


class NewTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._workers: List[Any] = []
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(
            theme.CONTENT_MARGIN, theme.CONTENT_MARGIN,
            theme.CONTENT_MARGIN, theme.CONTENT_MARGIN,
        )
        lay.setSpacing(theme.FORM_SPACING)

        # 페이지 헤더
        hdr = QHBoxLayout()
        title = QLabel("탭 제목")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        sub = QLabel("탭 설명")
        sub.setObjectName("page_subtitle")
        hdr.addWidget(sub)
        hdr.addStretch()
        lay.addLayout(hdr)

        # 여기에 UI 구성...

        lay.addStretch()
        scroll.setWidget(container)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
```

## 2. main_window.py에 등록

`src/bpe/gui/main_window.py`:

```python
# TAB_DEFS 리스트에 추가
{"key": "new_tab", "label": "New Tab"},

# _build_tabs()에 import 추가
from bpe.gui.tabs.new_tab import NewTab

# tab_classes dict에 추가
"new_tab": NewTab,
```

## 3. 체크리스트

- [ ] QScrollArea로 감쌈
- [ ] _workers 리스트 있음
- [ ] objectName 사용 (page_title, page_subtitle, form_label 등)
- [ ] SG 호출은 ShotGridWorker 사용
- [ ] ruff check 통과
- [ ] 앱 실행해서 탭 전환 확인
