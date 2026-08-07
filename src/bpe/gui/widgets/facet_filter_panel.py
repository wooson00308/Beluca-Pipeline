# @cursor-change: 2026-08-07, 0.2.x, ShotGrid 스타일 다중 카테고리 필터 패널 (팝업)
"""ShotGrid Shot 패널을 닮은 다중 선택 필터 팝업.

레이아웃 사고를 막기 위해 기존 QSplitter를 건드리지 않고 독립 팝업 창(Qt.Popup)으로 뜬다.
ShotGrid Shot 패널과 동일하게 기본 카테고리(Sequence·Status·Tags·Element·Char)는 펼친 채로
열리고, 나머지는 SG의 "More Filters"처럼 「기타 항목」 버튼 뒤에 접어 둔다.
접혀 있는 카테고리는 펼칠 때 체크박스를 만들므로 값이 수백 개여도 여는 속도에 영향이 없다.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.core.shot_filter_logic import (
    ShotFacetField,
    build_facet_counts,
    facet_key,
    selection_value_count,
    sort_facet_values_by_label,
    split_facet_fields_for_display,
)
from bpe.gui import theme

_PANEL_WIDTH = 330
_PANEL_MIN_HEIGHT = 220
# 화면 가용 높이의 이 비율까지 늘어난다 (상한 _PANEL_MAX_HEIGHT)
_PANEL_HEIGHT_RATIO = 0.8
_PANEL_MAX_HEIGHT = 900
# 카테고리당 기본으로 보여주는 값 개수 (ShotGrid와 동일)
_SECTION_VISIBLE_LIMIT = 5
_EMIT_DEBOUNCE_MS = 180
_LABEL_MAX_CHARS = 26


def _elide(text: str, limit: int = _LABEL_MAX_CHARS) -> str:
    s = (text or "").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


class _FacetSection(QWidget):
    """카테고리 하나 — 헤더(접기/펼치기) + 값 체크박스 목록."""

    def __init__(
        self,
        facet_field: ShotFacetField,
        values: Sequence[Tuple[str, int]],
        on_changed: Callable[[], None],
        on_resized: Callable[[], None],
        parent: Optional[QWidget] = None,
        *,
        expanded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._field = facet_field
        self._values: List[Tuple[str, int]] = list(values)
        self._on_changed = on_changed
        self._on_resized = on_resized
        self._selected: Dict[str, str] = {}
        self._expanded = False
        self._show_all = False
        self._body_built = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._header = QPushButton()
        self._header.setObjectName("facet_section_header_btn")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle_expanded)
        lay.addWidget(self._header)

        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(14, 2, 4, 6)
        self._body_lay.setSpacing(2)
        self._body.setVisible(False)
        lay.addWidget(self._body)

        self._search: Optional[QLineEdit] = None
        self._rows_host = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(2)
        self._more_btn = QPushButton("")
        self._more_btn.setObjectName("facet_more_btn")
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.clicked.connect(self._toggle_show_all)

        self._update_header()
        if expanded:
            self._set_expanded(True)

    # ── public ──────────────────────────────────────────────────────

    @property
    def field_name(self) -> str:
        return self._field.field_name

    def selected_labels(self) -> Set[str]:
        return set(self._selected.values())

    def clear_selection(self) -> None:
        if not self._selected:
            return
        self._selected.clear()
        self._update_header()
        if self._body_built:
            self._render_rows()

    def matches_query(self, query: str) -> bool:
        """상단 검색어가 카테고리 이름 또는 값 중 하나에라도 걸리는지."""
        q = (query or "").strip().lower()
        if not q:
            return True
        if q in self._field.display_label.lower() or q in self._field.field_name.lower():
            return True
        return any(q in label.lower() for label, _n in self._values)

    def set_values(self, values: Sequence[Tuple[str, int]]) -> None:
        self._values = list(values)
        valid = {facet_key(label) for label, _n in self._values}
        self._selected = {k: v for k, v in self._selected.items() if k in valid}
        self._update_header()
        if self._body_built:
            self._render_rows()

    # ── internals ───────────────────────────────────────────────────

    def _update_header(self) -> None:
        """ShotGrid처럼 이름만 보여준다. 값 종류 수를 붙이면 샷 개수로 오해하기 쉬움."""
        arrow = "\u25be" if self._expanded else "\u25b8"
        n_sel = len(self._selected)
        suffix = f"  \u00b7 {n_sel}개 선택" if n_sel else ""
        self._header.setText(f"{arrow}  {_elide(self._field.display_label)}{suffix}")
        color = theme.ACCENT_TEXT if n_sel else theme.TEXT
        weight = "600" if n_sel else "500"
        self._header.setStyleSheet(f"color: {color}; font-weight: {weight};")

    def _toggle_expanded(self) -> None:
        self._set_expanded(not self._expanded)
        self._on_resized()

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        if expanded and not self._body_built:
            self._build_body()
        self._body.setVisible(expanded)
        self._update_header()

    def _build_body(self) -> None:
        self._body_built = True
        self._body_lay.addWidget(self._rows_host)
        self._body_lay.addWidget(self._more_btn)
        # 값 검색창은 SG와 동일하게 「더보기」 아래에 둔다. 표시 한도를 넘는 값이 있을 때만 필요.
        if len(self._values) > _SECTION_VISIBLE_LIMIT:
            edit = QLineEdit()
            edit.setObjectName("facet_search_edit")
            edit.setPlaceholderText(f"{_elide(self._field.display_label, 12)} 검색")
            edit.setFixedHeight(26)
            edit.textChanged.connect(lambda _t: self._render_rows())
            self._body_lay.addWidget(edit)
            self._search = edit
        self._render_rows()

    def _visible_values(self) -> Tuple[List[Tuple[str, int]], int]:
        q = self._search.text().strip().lower() if self._search is not None else ""
        pool = [(lbl, n) for lbl, n in self._values if not q or q in lbl.lower()]
        # ShotGrid와 동일하게 개수가 아니라 이름순. 선택한 값만 위로 고정한다.
        pool = sort_facet_values_by_label(pool)
        pool = sorted(pool, key=lambda it: 0 if facet_key(it[0]) in self._selected else 1)
        limit = len(pool) if self._show_all else max(_SECTION_VISIBLE_LIMIT, len(self._selected))
        return pool[:limit], len(pool)

    def _render_rows(self) -> None:
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        shown, total = self._visible_values()
        if not shown:
            empty = QLabel("해당하는 값 없음")
            empty.setObjectName("facet_empty_label")
            self._rows_lay.addWidget(empty)
        for label, count in shown:
            self._rows_lay.addWidget(self._make_row(label, count))

        if total > len(shown):
            self._more_btn.setText(f"더보기 ({total - len(shown)})")
            self._more_btn.setVisible(True)
        elif self._show_all and total > _SECTION_VISIBLE_LIMIT:
            self._more_btn.setText("접기")
            self._more_btn.setVisible(True)
        else:
            self._more_btn.setVisible(False)

    def _make_row(self, label: str, count: int) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        cb = QCheckBox(_elide(label))
        cb.setToolTip(label)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setChecked(facet_key(label) in self._selected)
        cb.toggled.connect(lambda checked, lb=label: self._on_value_toggled(lb, checked))
        h.addWidget(cb, 1)
        cnt = QLabel(str(count))
        cnt.setObjectName("facet_count_label")
        h.addWidget(cnt, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return row

    def _on_value_toggled(self, label: str, checked: bool) -> None:
        key = facet_key(label)
        if not key:
            return
        if checked:
            self._selected[key] = label
        else:
            self._selected.pop(key, None)
        self._update_header()
        self._on_changed()

    def _toggle_show_all(self) -> None:
        self._show_all = not self._show_all
        self._render_rows()
        self._on_resized()


class FacetFilterPanel(QFrame):
    """카테고리별 다중 선택 필터 팝업. 선택이 바뀌면 ``selectionChanged``를 디바운스해 보낸다."""

    selectionChanged = Signal(object)  # Dict[str, Set[str]]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("facet_filter_panel")
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setFixedWidth(_PANEL_WIDTH)
        self.setMaximumHeight(_PANEL_MAX_HEIGHT)
        self.setStyleSheet(_panel_qss())

        self._sections: List[_FacetSection] = []
        self._secondary_names: Set[str] = set()
        self._show_secondary = False
        self._shot_row_count = 0
        self._anchor: Optional[QWidget] = None
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.timeout.connect(self._emit_selection)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._field_search = QLineEdit()
        self._field_search.setObjectName("facet_search_edit")
        self._field_search.setPlaceholderText("항목 검색 (예: 시퀀스, 태그)")
        self._field_search.setFixedHeight(28)
        self._field_search.textChanged.connect(self._apply_field_search)
        top.addWidget(self._field_search, 1)
        self._clear_btn = QPushButton("초기화")
        self._clear_btn.setObjectName("facet_clear_btn")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(lambda: self.clear_selection(emit=True))
        top.addWidget(self._clear_btn, 0)
        lay.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._host_lay = QVBoxLayout(self._host)
        self._host_lay.setContentsMargins(0, 0, 0, 0)
        self._host_lay.setSpacing(2)
        self._host_lay.addStretch(1)
        self._scroll.setWidget(self._host)
        lay.addWidget(self._scroll, 1)

        # SG의 "More Filters" — 자주 안 쓰는 카테고리를 접어 두는 버튼
        self._more_fields_btn = QPushButton("")
        self._more_fields_btn.setObjectName("facet_more_fields_btn")
        self._more_fields_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_fields_btn.setVisible(False)
        self._more_fields_btn.clicked.connect(self._toggle_secondary)

        self._status = QLabel("")
        self._status.setObjectName("facet_status_label")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

    # ── public API ──────────────────────────────────────────────────

    def set_facets(
        self,
        fields: Sequence[ShotFacetField],
        shot_rows: Sequence[Dict[str, Any]],
    ) -> None:
        """카테고리 목록과 Shot 원본 데이터를 받아 패널을 다시 만든다 (선택은 초기화).

        기본 카테고리는 펼친 채로, 나머지는 「기타 항목」 뒤에 접어서 배치한다.
        """
        self._clear_sections()
        self._shot_row_count = len(shot_rows)
        counts = build_facet_counts(shot_rows, fields)
        primary, secondary = split_facet_fields_for_display(fields, counts)

        for f in primary:
            self._add_section(f, counts.get(f.field_name) or [], expanded=True)

        self._host_lay.insertWidget(self._host_lay.count() - 1, self._more_fields_btn)

        for f in secondary:
            sec = self._add_section(f, counts.get(f.field_name) or [], expanded=False)
            if sec is not None:
                self._secondary_names.add(sec.field_name)

        self._show_secondary = False
        self._update_section_visibility()
        self._update_status()

    def _add_section(
        self,
        facet_field: ShotFacetField,
        values: Sequence[Tuple[str, int]],
        *,
        expanded: bool,
    ) -> Optional[_FacetSection]:
        """값이 하나도 없는 카테고리는 만들지 않는다 (프로젝트마다 비어있는 필드가 있음)."""
        if not values:
            return None
        sec = _FacetSection(
            facet_field,
            values,
            self._schedule_emit,
            self._refit,
            self._host,
            expanded=expanded,
        )
        self._host_lay.insertWidget(self._host_lay.count() - 1, sec)
        self._sections.append(sec)
        return sec

    def selection(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for sec in self._sections:
            vals = sec.selected_labels()
            if vals:
                out[sec.field_name] = vals
        return out

    def has_selection(self) -> bool:
        return any(sec.selected_labels() for sec in self._sections)

    def clear_selection(self, *, emit: bool = True) -> None:
        changed = self.has_selection()
        for sec in self._sections:
            sec.clear_selection()
        if emit and changed:
            self._schedule_emit()

    def show_under(self, anchor: QWidget) -> None:
        """앵커 위젯 아래에 띄우되 화면 밖으로 나가지 않게 보정한다."""
        self._anchor = anchor
        self._refit()
        self.show()
        self.raise_()
        self._refit()

    # ── internals ───────────────────────────────────────────────────

    def _refit(self) -> None:
        """카테고리를 펼칠 때마다 높이를 다시 잡고 화면 안쪽으로 위치를 보정한다.

        새로 만든 체크박스는 스타일 적용(polish) 뒤에야 정확한 크기를 알려주므로
        즉시 한 번, 이벤트 루프가 한 바퀴 돈 뒤 한 번 더 맞춘다.
        """
        self._apply_fit()
        QTimer.singleShot(0, self._apply_fit)

    def _apply_fit(self) -> None:
        anchor = self._anchor
        if anchor is None:
            return
        try:
            anchor_h = anchor.height()
            top_left = anchor.mapToGlobal(QPoint(0, 0))
            screen = anchor.screen()
        except RuntimeError:  # 앵커 위젯이 이미 파괴된 경우
            self._anchor = None
            return
        # 방금 펼친 섹션의 크기가 아직 반영 안 됐을 수 있으므로 안쪽부터 레이아웃을 갱신
        for widget in (*self._sections, self._host, self):
            wlay = widget.layout()
            if wlay is not None:
                wlay.invalidate()
                wlay.activate()
        # QScrollArea의 sizeHint는 내용 높이를 반영하지 않으므로 내부 위젯 기준으로 직접 계산
        chrome = (
            self._field_search.sizeHint().height() + self._status.sizeHint().height() + 20 + 12 + 4
        )
        wanted = self._host.sizeHint().height() + chrome
        height = min(_PANEL_MAX_HEIGHT, max(_PANEL_MIN_HEIGHT, wanted))
        x, y = top_left.x(), top_left.y() + anchor_h + 2
        if screen is not None:
            avail = screen.availableGeometry()
            # 기본 카테고리를 펼쳐 두면 내용이 길어지므로 화면의 80%까지 허용
            cap = max(_PANEL_MIN_HEIGHT, int(avail.height() * _PANEL_HEIGHT_RATIO))
            height = min(height, cap)
            x = min(max(avail.left(), x), max(avail.left(), avail.right() - self.width()))
            if y + height > avail.bottom():
                y = max(avail.top(), min(top_left.y() - height - 2, avail.bottom() - height))
        self.resize(self.width(), int(height))
        self.move(int(x), int(y))

    def _clear_sections(self) -> None:
        for sec in self._sections:
            self._host_lay.removeWidget(sec)
            sec.setParent(None)
            sec.deleteLater()
        self._sections = []
        self._secondary_names = set()
        self._host_lay.removeWidget(self._more_fields_btn)
        self._more_fields_btn.setParent(None)
        self._more_fields_btn.setVisible(False)

    def _toggle_secondary(self) -> None:
        self._show_secondary = not self._show_secondary
        self._update_section_visibility()
        self._refit()

    def _apply_field_search(self, _text: str) -> None:
        self._update_section_visibility()
        self._refit()

    def _update_section_visibility(self) -> None:
        """검색 중이면 「기타 항목」 안쪽까지 전부 뒤져서 보여준다."""
        query = self._field_search.text().strip()
        searching = bool(query)
        hidden_count = 0
        for sec in self._sections:
            match = sec.matches_query(query)
            if sec.field_name in self._secondary_names:
                visible = match and (searching or self._show_secondary)
                if not searching and not self._show_secondary:
                    hidden_count += 1
            else:
                visible = match
            sec.setVisible(visible)

        if searching or not self._secondary_names:
            self._more_fields_btn.setVisible(False)
            return
        arrow = "\u25be" if self._show_secondary else "\u25b8"
        n = hidden_count if not self._show_secondary else len(self._secondary_names)
        self._more_fields_btn.setText(f"{arrow}  기타 항목 {n}개")
        self._more_fields_btn.setVisible(True)

    def _update_status(self) -> None:
        if not self._sections:
            self._status.setText("필터할 수 있는 항목이 없습니다.")
            return
        n = selection_value_count(self.selection())
        head = f"{n}개 조건 적용" if n else "필터 없음"
        self._status.setText(f"{head} · 샷 {self._shot_row_count}개 기준")

    def _schedule_emit(self) -> None:
        self._update_status()
        self._emit_timer.start(_EMIT_DEBOUNCE_MS)

    def _emit_selection(self) -> None:
        self.selectionChanged.emit(self.selection())


def _panel_qss() -> str:
    return f"""
    QFrame#facet_filter_panel {{
        background-color: {theme.PANEL_BG};
        border: 1px solid {theme.BORDER};
        border-radius: 6px;
    }}
    QPushButton#facet_section_header_btn {{
        background-color: transparent;
        border: none;
        padding: 6px 4px;
        text-align: left;
        font-size: {theme.FONT_SIZE}px;
    }}
    QPushButton#facet_section_header_btn:hover {{
        background-color: {theme.INPUT_BG};
        border-radius: 4px;
    }}
    QPushButton#facet_more_fields_btn {{
        background-color: transparent;
        color: {theme.TEXT_LABEL};
        border: none;
        border-top: 1px solid {theme.BORDER};
        padding: 8px 4px;
        margin-top: 4px;
        text-align: left;
        font-size: {theme.FONT_SIZE}px;
    }}
    QPushButton#facet_more_fields_btn:hover {{
        color: {theme.ACCENT_TEXT};
    }}
    QPushButton#facet_more_btn, QPushButton#facet_clear_btn {{
        background-color: {theme.INPUT_BG};
        color: {theme.TEXT_LABEL};
        border: 1px solid {theme.BORDER};
        border-radius: 4px;
        padding: 3px 8px;
        font-size: {theme.FONT_SIZE_SMALL}px;
    }}
    QPushButton#facet_more_btn:hover, QPushButton#facet_clear_btn:hover {{
        color: {theme.ACCENT_TEXT};
        border-color: {theme.ACCENT};
    }}
    QLineEdit#facet_search_edit {{
        background-color: {theme.INPUT_BG};
        color: {theme.TEXT};
        border: 1px solid {theme.BORDER};
        border-radius: 4px;
        padding: 2px 6px;
        font-size: {theme.FONT_SIZE_SMALL}px;
    }}
    QLineEdit#facet_search_edit:focus {{
        border-color: {theme.BORDER_FOCUS};
    }}
    QLabel#facet_count_label {{
        color: {theme.TEXT_LABEL};
        font-size: {theme.FONT_SIZE_SMALL}px;
    }}
    QLabel#facet_status_label, QLabel#facet_empty_label {{
        color: {theme.TEXT_DIM};
        font-size: {theme.FONT_SIZE_SMALL}px;
    }}
    QCheckBox {{
        color: {theme.TEXT};
        font-size: {theme.FONT_SIZE_SMALL}px;
        spacing: 6px;
    }}
    """
