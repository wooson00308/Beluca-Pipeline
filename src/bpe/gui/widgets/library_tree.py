# @cursor-change: 2026-08-15, 0.12.x, 트리 펼침 화살표를 QPainter 직접 그리기로 교체
"""라이브러리 트리 공용 위젯 — 펼침 화살표를 QPainter 로 직접 그린다.

QSS ``::branch`` 의 border-삼각형 기법(width/height:0 포함)은 Qt 가 서브컨트롤
박스를 접어주지 않아 민트색 사각형으로 렌더링된다 (2026-08-13~14 확인,
커밋 65b6bec 의 CSS 수정으로도 해결 안 됨). 그래서 QSS 로 화살표를 그리는 걸
포기하고 ``drawBranches`` 오버라이드로 삼각형을 직접 칠한다.

소스 라이브러리 계열 트리 3곳(브라우저 분류 트리, 설정 좌/우 트리)만 사용한다 —
다른 탭(My Tasks 등)의 트리에는 영향을 주지 않는다.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QTreeWidget, QWidget

from bpe.gui import theme

# 선택된 행은 branch 영역까지 ACCENT 로 칠해지므로(ShowDecorationSelected)
# 같은 색으로 그리면 화살표가 사라진다 → item:selected 글자색과 같은 흰색으로 반전.
_ARROW_SELECTED_COLOR = "#ffffff"


class LibraryTree(QTreeWidget):
    """소스 라이브러리 계열 트리 — 테마 QSS + 강조색 펼침 화살표."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(theme.tree_stylesheet())

    def drawBranches(  # noqa: N802
        self, painter: QPainter, rect: QRect, index: QModelIndex
    ) -> None:
        """마지막 인덴트 칸 중앙에 ▶(접힘)/▼(펼침) 삼각형을 그린다.

        Qt 기본 구현(super)은 호출하지 않는다 — 호출하면 스타일 기본 회색
        화살표가 함께 그려져 이중으로 보인다. 자식 없는 행은 아무것도 그리지
        않는다(Qt 기본과 동일). 펼침/접힘 클릭 히트테스트는 그리기와 무관하게
        인덴트 산술로 계산되므로 이 오버라이드의 영향을 받지 않는다.
        """
        if not index.isValid() or rect.width() <= 0 or rect.height() <= 0:
            return
        model = self.model()
        if model is None or not model.hasChildren(index):
            return

        # rect 는 (x=0, width = indentation × (level+1)) — 마지막(가장 안쪽)
        # 인덴트 칸의 중앙을 기준점으로 잡는다. rootIsDecorated(False) 등으로
        # rect 가 좁아져도 칸을 벗어나지 않게 클램프.
        indent = float(min(self.indentation(), rect.width()))
        cx = rect.right() + 1 - indent / 2.0
        cy = rect.top() + rect.height() / 2.0

        half_base = theme.TREE_ARROW_SIZE / 2.0
        half_depth = theme.TREE_ARROW_DEPTH / 2.0

        if self.isExpanded(index):  # ▼ 아래 방향
            points: List[QPointF] = [
                QPointF(cx - half_base, cy - half_depth),
                QPointF(cx + half_base, cy - half_depth),
                QPointF(cx, cy + half_depth),
            ]
        else:  # ▶ 오른쪽 방향
            points = [
                QPointF(cx - half_depth, cy - half_base),
                QPointF(cx - half_depth, cy + half_base),
                QPointF(cx + half_depth, cy),
            ]

        sel = self.selectionModel()
        selected = sel is not None and sel.isSelected(index)
        color = QColor(_ARROW_SELECTED_COLOR if selected else theme.ACCENT)

        # 뷰포트 painter 를 모든 행이 공유하므로 save/restore 필수.
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF(points))
        painter.restore()
