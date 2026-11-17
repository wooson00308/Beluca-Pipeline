"""컨펌 창의 샷 목록 서랍 — 외주 / 내부 / TM / SV 갈래, 업체 고르기, 찾기, 정렬.

Annotation 모드에서는 작업을 나눠 주기 전(wtg·assign)의 샷을 샷마다 한 줄로 보여 주고,
내 작업 탭과 같은 필터(시퀀스·태그 …)로 좁힌다.
"""

from __future__ import annotations

import queue
from html import escape
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_list import (
    GROUP_VENDOR,
    GROUPS,
    MODE_ANNOTATION,
    MODE_CONFIRM,
    MODES,
    SORT_OLD,
    SORTS,
    annotation_status_text,
    annotation_subtitle,
    filter_annotation_rows,
    filter_rows,
    row_subtitle,
    sort_rows,
    vendor_names,
)
from bpe.core.confirm_sequence import SEQ_MAX_CUTS, SEQ_MIN_CUTS, order_rows, toggle_pick
from bpe.core.logging import get_logger
from bpe.core.settings import get_confirm_settings, save_confirm_settings
from bpe.core.shot_filter_logic import (
    ShotFacetField,
    matching_shot_ids,
    selection_value_count,
)
from bpe.gui.confirm import status_style, style
from bpe.gui.widgets.facet_filter_panel import FacetFilterPanel
from bpe.gui.workers.confirm_thumb_worker import ThumbFetchWorker
from bpe.gui.workers.sg_worker import ShotGridWorker

logger = get_logger("gui.confirm.shot_drawer")

DRAWER_WIDTH = 330
_THUMB_W, _THUMB_H = 80, 45
_ROW_H = _THUMB_H + 12
_THUMB_THREADS = 4
_ROLE = Qt.ItemDataRole.UserRole
_ALL_VENDORS = "업체 전체"
_PICK_PROJECT = "프로젝트 고르기"
_ANNOTATION_TITLE = "wtg · assign 샷"
_FILTER_ARROW = chr(0x25BE)


def _band(name: str, bg: str) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"QFrame#{name} {{ background: {bg}; border-bottom: 1px solid {style.EDGE}; }}")
    return f


class ShotDrawer(QWidget):
    """창 왼쪽에 겹쳐 뜨는 샷 목록."""

    task_picked = Signal(object)
    rows_changed = Signal()
    sequence_requested = Signal(object)  # 이어 볼 컷들(샷 이름 순)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(DRAWER_WIDTH)
        self.setObjectName("confirm_drawer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#confirm_drawer {{ background: {style.PANEL}; "
            f"border-right: 1px solid #000000; }}"
        )
        self._workers: List[Any] = []
        self._rows: List[Dict[str, Any]] = []
        self._shown: List[Dict[str, Any]] = []
        self._loaded = False
        self._projects_asked = False
        self._thumbs: Dict[Any, QPixmap] = {}
        self._thumb_labels: Dict[Any, QLabel] = {}
        self._thumb_jobs: "queue.Queue[Tuple[Any, str]]" = queue.Queue()
        self._thumb_workers: List[ThumbFetchWorker] = []
        self._thumb_asked: set = set()
        self._current_task: Any = None
        self._req = 0
        self._closed = False
        self._mode = MODE_CONFIRM
        self._seq_pick = False  # 이어 볼 컷을 고르는 중인가
        self._seq_keys: List[Any] = []  # 고른 컷(task_id)
        self._mode_rows: Dict[str, List[Dict[str, Any]]] = {}  # 모드 → 읽어 둔 목록(같은 프로젝트)
        self._rows_pid: Any = None
        # 내 작업 탭과 같은 샷 필터(Annotation 모드)
        self._facet_fields: List[ShotFacetField] = []
        self._facet_rows: List[Dict[str, Any]] = []
        self._facet_selection: Dict[str, Set[str]] = {}
        self._facet_allowed: Optional[Set[int]] = None
        self._facet_pid: Any = None
        self._facet_req = 0
        self._facet_panel: Optional[FacetFilterPanel] = None
        saved = get_confirm_settings()
        self._group = saved["list_group"] if saved["list_group"] in GROUPS else GROUPS[0]
        self._sort = saved["list_sort"] if saved["list_sort"] in SORTS else SORT_OLD
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 1, 0)
        outer.setSpacing(0)

        head = _band("drawer_head", style.HEADER)
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(8, 6, 8, 6)
        hrow.setSpacing(8)
        # 갈래 이름은 샷그리드 Versions 화면의 분류 이름 그대로(길어서 고르기 칸으로 둔다)
        self._group_box = QComboBox()
        self._group_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._group_box.addItems(list(GROUPS))
        self._group_box.setToolTip("샷그리드 Versions 화면의 분류와 같은 이름입니다")
        self._group_box.setMinimumWidth(180)
        self._group_box.setStyleSheet(f"QComboBox {{ color: {style.TEXT_STRONG}; }}")
        self._group_box.activated.connect(lambda _i: self._set_group(self._group_box.currentText()))
        hrow.addWidget(self._group_box)
        self._mode_title = QLabel(_ANNOTATION_TITLE)  # Annotation 모드에서 갈래 칸 자리에 보인다
        self._mode_title.setStyleSheet(f"color: {style.TEXT_STRONG};")
        self._mode_title.setToolTip("어느 태스크든 상태가 wtg · assign 인 샷 (샷마다 한 줄)")
        self._mode_title.hide()
        hrow.addWidget(self._mode_title)
        hrow.addStretch(1)
        self._count = QLabel("")
        self._count.setStyleSheet(f"color: {style.DIM};")
        hrow.addWidget(self._count)
        outer.addWidget(head)

        proj = _band("drawer_project", style.PANEL)
        prow = QHBoxLayout(proj)
        prow.setContentsMargins(8, 6, 8, 6)
        prow.setSpacing(6)
        self._project = QComboBox()
        self._project.addItem(_PICK_PROJECT, None)
        self._project.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._project.currentIndexChanged.connect(self._reload)
        prow.addWidget(self._project, 1)
        self._refresh = QPushButton("조회")
        self._refresh.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh.clicked.connect(self._reload)
        prow.addWidget(self._refresh)
        outer.addWidget(proj)

        filt = _band("drawer_filter", style.PANEL)
        frow = QHBoxLayout(filt)
        frow.setContentsMargins(8, 6, 8, 6)
        frow.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("찾기")
        self._search.setToolTip("샷 이름이나 작업자 찾기")
        self._search.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._search.textChanged.connect(self._refill)
        frow.addWidget(self._search, 2)
        self._vendor = QComboBox()
        self._vendor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vendor.currentIndexChanged.connect(self._refill)
        frow.addWidget(self._vendor, 2)
        self._sort_box = QComboBox()
        self._sort_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sort_box.addItems(list(SORTS))
        self._sort_box.setCurrentText(self._sort)
        self._sort_box.currentTextChanged.connect(self._set_sort)
        frow.addWidget(self._sort_box, 2)
        self._facet_btn = QPushButton(f"필터  {_FILTER_ARROW}")
        self._facet_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._facet_btn.setToolTip("시퀀스·태그 등 샷 정보로 목록 좁히기 (내 작업 탭과 같은 필터)")
        self._facet_btn.clicked.connect(self._toggle_facets)
        self._facet_btn.setEnabled(False)
        self._facet_btn.hide()
        frow.addWidget(self._facet_btn, 2)
        outer.addWidget(filt)

        # 이어 보기: 켜면 줄을 눌러 컷을 고르고, 아래 버튼으로 이어서 재생한다
        seq = _band("drawer_seq", style.PANEL)
        srow = QHBoxLayout(seq)
        srow.setContentsMargins(8, 6, 8, 6)
        srow.setSpacing(6)
        self._seq_btn = QPushButton("이어 보기")
        self._seq_btn.setCheckable(True)
        self._seq_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seq_btn.setToolTip(
            f"켜고 컷을 눌러 고른 뒤({SEQ_MIN_CUTS}~{SEQ_MAX_CUTS}컷) "
            "이어서 재생합니다 — 샷 이름 순"
        )
        self._seq_btn.setStyleSheet(
            f"QPushButton:checked {{ background: {style.ON}; color: {style.TEXT_STRONG}; "
            f"border-bottom: 2px solid {style.WARN}; }}"
        )
        self._seq_btn.toggled.connect(self._set_seq_pick)
        srow.addWidget(self._seq_btn)
        self._seq_note = QLabel("")
        self._seq_note.setStyleSheet(f"color: {style.DIM};")
        srow.addWidget(self._seq_note, 1)
        self._seq_clear = QPushButton("비우기")
        self._seq_clear.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seq_clear.clicked.connect(self.clear_sequence_picks)
        self._seq_clear.hide()
        srow.addWidget(self._seq_clear)
        self._seq_play = QPushButton("이어 재생")
        self._seq_play.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seq_play.setStyleSheet(
            f"QPushButton {{ background: {style.ACCENT}; color: {style.ON_ACCENT}; "
            f"font-weight: bold; }}"
            f"QPushButton:disabled {{ color: #6a6a6a; background: #2c2c2c; }}"
        )
        self._seq_play.clicked.connect(self._request_sequence)
        self._seq_play.hide()
        srow.addWidget(self._seq_play)
        self._seq_band = seq
        outer.addWidget(seq)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(
            f"color: {style.DIM}; padding: 8px 10px; border-bottom: 1px solid {style.EDGE};"
        )
        self._note.hide()
        outer.addWidget(self._note)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setStyleSheet(
            f"QListWidget {{ border: none; border-radius: 0px; padding: 0px; "
            f"background: {style.PANEL}; }}"
            f"QListWidget::item {{ padding: 0px; margin: 0px; border: none; border-radius: 0px; "
            f"border-bottom: 1px solid {style.EDGE}; }}"
            f"QListWidget::item:hover {{ background: {style.HEADER}; }}"
            f"QListWidget::item:selected {{ background: transparent; }}"
        )
        self._list.itemClicked.connect(self._on_clicked)
        outer.addWidget(self._list, 1)
        self._sync_groups()

    def _say(self, text: str) -> None:
        self._note.setText(text)
        self._note.setVisible(bool(text))

    # ── 조회 ────────────────────────────────────────────────────

    def load_projects(self) -> None:
        """서랍을 처음 열 때 프로젝트 목록을 읽는다."""
        if self._projects_asked:
            return
        self._projects_asked = True
        self._say("프로젝트 읽는 중…")

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.projects import list_active_projects

            return list_active_projects(get_default_sg())

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_projects)
        w.error.connect(self._on_projects_failed)
        w.start()
        self._workers.append(w)

    def _on_projects_failed(self, msg: str) -> None:
        self._projects_asked = False  # 서랍을 다시 열면 한 번 더 읽어 본다
        self._say(f"프로젝트를 읽지 못했습니다: {msg}")

    def _on_projects(self, result: object) -> None:
        if self._closed or not isinstance(result, list):
            return
        self._project.blockSignals(True)
        self._project.clear()
        self._project.addItem(_PICK_PROJECT, None)
        for p in sorted(result, key=lambda r: str(r.get("code") or r.get("name") or "")):
            label = str(p.get("code") or p.get("name") or p.get("id"))
            self._project.addItem(label, p.get("id"))
        self._project.blockSignals(False)
        self._say(self._pick_hint())

    def _annotation(self) -> bool:
        return self._mode == MODE_ANNOTATION

    def _pick_hint(self) -> str:
        if self._annotation():
            return "프로젝트를 고르면 wtg · assign 샷이 나옵니다"
        return "프로젝트를 고르면 확인 대기 샷이 나옵니다"

    def _reload(self) -> None:
        pid = self._project.currentData()
        if pid is None:
            return
        if pid != self._rows_pid:  # 프로젝트가 바뀌면 다른 모드에 읽어 둔 목록·필터도 버린다
            self._rows_pid = pid
            self._mode_rows = {}
            self._drop_facets()
        self._req += 1
        req = self._req
        self._say("목록 읽는 중…")
        annotation = self._annotation()
        if annotation:
            self._ensure_facets(pid)

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.confirm_list import list_annotation_shots, list_confirm_tasks

            if annotation:
                return list_annotation_shots(get_default_sg(), int(pid))
            return list_confirm_tasks(get_default_sg(), int(pid))

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req: self._on_rows(r, q))
        w.error.connect(lambda e: self._say(f"목록을 읽지 못했습니다: {e}"))
        w.start()
        self._workers.append(w)

    def _on_rows(self, result: object, req: int) -> None:
        if self._closed or req != self._req or not isinstance(result, list):
            return
        self.set_rows(result)

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._loaded = True
        self._thumb_asked = set(self._thumbs)
        self._vendor.blockSignals(True)
        self._vendor.clear()
        self._vendor.addItem(_ALL_VENDORS, "")
        for name in vendor_names(self._rows):
            self._vendor.addItem(name, name)
        self._vendor.blockSignals(False)
        self._refill()

    # ── 거르기 ───────────────────────────────────────────────────

    def _set_group(self, group: str) -> None:
        self._group = group
        save_confirm_settings({"list_group": group})
        self._sync_groups()
        self._refill()

    def _set_sort(self, mode: str) -> None:
        self._sort = mode
        save_confirm_settings({"list_sort": mode})
        self._refill()

    def _sync_groups(self) -> None:
        self._group_box.setCurrentText(self._group)
        self._vendor.setEnabled(self._group == GROUP_VENDOR)

    def shown_rows(self) -> List[Dict[str, Any]]:
        return list(self._shown)

    def summary(self) -> str:
        """위 막대의 목록 버튼에 적을 글(예: 「외주 6」). 아직 안 읽었으면 빈 글."""
        if not self._loaded:
            return ""
        name = MODE_ANNOTATION if self._annotation() else self._group
        return f"{name} {len(self._shown)}"

    # ── 모드(Confirm / Annotation) ───────────────────────────────

    def mode(self) -> str:
        return self._mode

    def project_text(self) -> str:
        """고른 프로젝트 이름(아직 안 골랐으면 빈 글)."""
        return self._project.currentText() if self._project.currentData() is not None else ""

    def set_mode(self, mode: str) -> None:
        """목록을 Confirm(확인 대기) 과 Annotation(wtg·assign 샷) 사이에서 바꾼다."""
        if mode not in MODES or mode == self._mode:
            return
        if self._loaded:
            self._mode_rows[self._mode] = list(self._rows)
        self._mode = mode
        self._req += 1  # 앞 모드에서 읽던 목록이 늦게 와도 버린다
        annotation = self._annotation()
        self._group_box.setVisible(not annotation)
        self._mode_title.setVisible(annotation)
        self._vendor.setVisible(not annotation)
        self._sort_box.setVisible(not annotation)
        self._facet_btn.setVisible(annotation)
        self._seq_band.setVisible(not annotation)  # 이어 보기는 확인 대기 목록에서만
        if annotation and self._seq_pick:
            self._seq_btn.setChecked(False)
        if self._facet_panel is not None and self._facet_panel.isVisible():
            self._facet_panel.hide()
        self._current_task = None
        cached = self._mode_rows.get(mode)
        if cached is not None:
            self.set_rows(cached)
            return
        self._rows, self._loaded = [], False
        self._count.setText("")
        self._refill()
        if self._project.currentData() is not None:
            self._reload()
        elif self._projects_asked:
            self._say(self._pick_hint())

    # ── 샷 필터(내 작업 탭과 같은 것) ────────────────────────────

    def _drop_facets(self) -> None:
        self._facet_req += 1
        self._facet_pid = None
        self._facet_fields, self._facet_rows = [], []
        self._facet_selection, self._facet_allowed = {}, None
        if self._facet_panel is not None:
            self._facet_panel.hide()
            self._facet_panel.deleteLater()
            self._facet_panel = None
        self._sync_facet_btn()

    def _sync_facet_btn(self) -> None:
        n = selection_value_count(self._facet_selection)
        self._facet_btn.setText(f"필터 {n}  {_FILTER_ARROW}" if n else f"필터  {_FILTER_ARROW}")
        self._facet_btn.setEnabled(bool(self._facet_fields and self._facet_rows))

    def _ensure_facets(self, pid: Any) -> None:
        """프로젝트의 샷 정보(시퀀스·태그 …)를 뒤에서 한 번 읽는다."""
        if self._facet_pid == pid:
            return
        self._facet_pid = pid
        self._facet_req += 1
        req = self._facet_req

        def _fetch() -> Dict[str, Any]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.shot_filters import (
                discover_shot_facet_fields,
                fetch_shot_facet_data,
            )

            sg = get_default_sg()
            fields = discover_shot_facet_fields(sg, int(pid))
            rows = fetch_shot_facet_data(sg, int(pid), fields) if fields else []
            return {"fields": fields, "rows": rows}

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req: self._on_facets(r, q))
        w.error.connect(lambda e: logger.warning("confirm drawer: facet load failed: %s", e))
        w.start()
        self._workers.append(w)

    def _on_facets(self, result: object, req: int) -> None:
        if self._closed or req != self._facet_req or not isinstance(result, dict):
            return
        self.set_facets(result.get("fields") or [], result.get("rows") or [])

    def set_facets(self, fields: List[Any], rows: List[Any]) -> None:
        """필터에 쓸 샷 정보를 넣는다(고른 것은 비운다)."""
        self._facet_fields = [f for f in fields if isinstance(f, ShotFacetField)]
        self._facet_rows = [r for r in rows if isinstance(r, dict)]
        self._facet_selection, self._facet_allowed = {}, None
        if self._facet_panel is not None:
            self._facet_panel.hide()
            self._facet_panel.deleteLater()
            self._facet_panel = None
        self._sync_facet_btn()
        if self._annotation():
            self._refill()

    def _facet_rows_in_list(self) -> List[Dict[str, Any]]:
        """필터 칸의 숫자가 목록과 맞게, 지금 목록에 있는 샷의 정보만 추린다."""
        ids = {r.get("shot_id") for r in self._rows}
        return [r for r in self._facet_rows if r.get("id") in ids]

    def _toggle_facets(self) -> None:
        panel = self._facet_panel
        if panel is not None and panel.isVisible():
            panel.hide()
            return
        if not self._facet_fields:
            return
        if panel is None:
            panel = FacetFilterPanel(self)
            panel.selectionChanged.connect(self.set_facet_selection)
            panel.set_facets(self._facet_fields, self._facet_rows_in_list())
            self._facet_panel = panel
        panel.show_under(self._facet_btn)

    def set_facet_selection(self, selection: object) -> None:
        sel: Dict[str, Set[str]] = {}
        if isinstance(selection, dict):
            for k, v in selection.items():
                if isinstance(v, (set, list, tuple)) and v:
                    sel[str(k)] = {str(x) for x in v}
        self._facet_selection, self._facet_allowed = sel, None
        self._sync_facet_btn()
        self._refill()

    def _allowed_shot_ids(self) -> Optional[Set[int]]:
        """필터로 남은 샷. 고른 것이 없으면 ``None``(전부)."""
        if not self._facet_selection or not self._facet_fields or not self._facet_rows:
            return None
        if self._facet_allowed is None:
            self._facet_allowed = matching_shot_ids(
                self._facet_rows, self._facet_fields, self._facet_selection
            )
        return self._facet_allowed

    def set_current_task(self, task_id: Any) -> None:
        """지금 열려 있는 샷을 목록에서 표시한다."""
        if task_id != self._current_task:
            self._current_task = task_id
            self._refill()

    # ── 이어 볼 컷 고르기 ────────────────────────────────────────

    def _set_seq_pick(self, on: bool) -> None:
        self._seq_pick = bool(on)
        if not on:
            self._seq_keys = []
        self._sync_seq_bar()
        self._redraw_rows()

    def clear_sequence_picks(self) -> None:
        self._seq_keys = []
        self._sync_seq_bar()
        self._redraw_rows()

    def sequence_picks(self) -> List[Dict[str, Any]]:
        """고른 컷들 — 샷 이름 순."""
        by_key = {r.get("task_id"): r for r in self._rows}
        return order_rows([by_key[k] for k in self._seq_keys if k in by_key])

    def _sync_seq_bar(self) -> None:
        n = len(self._seq_keys)
        self._seq_clear.setVisible(self._seq_pick and n > 0)
        self._seq_play.setVisible(self._seq_pick)
        self._seq_play.setEnabled(n >= SEQ_MIN_CUTS)
        self._seq_play.setText(f"{n}컷 이어 재생" if n else "이어 재생")
        if not self._seq_pick:
            self._seq_note.setText("")
        elif n < SEQ_MIN_CUTS:
            self._seq_note.setText("컷을 눌러 고르세요")
        else:
            self._seq_note.setText("")

    def _toggle_seq_row(self, row: Dict[str, Any]) -> None:
        self._seq_keys, ok = toggle_pick(self._seq_keys, row.get("task_id"))
        self._sync_seq_bar()
        if not ok:
            self._seq_note.setText(f"한 번에 {SEQ_MAX_CUTS}컷까지")
        self._redraw_rows()

    def _request_sequence(self) -> None:
        rows = self.sequence_picks()
        if len(rows) >= SEQ_MIN_CUTS:
            self.sequence_requested.emit(rows)

    def _redraw_rows(self) -> None:
        """줄 모양만 다시 그린다 — 목록을 비우지 않아 스크롤 자리가 그대로다."""
        self._thumb_labels = {}
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = item.data(_ROLE)
            if isinstance(row, dict):
                self._list.setItemWidget(item, self._make_row(row))

    def mark_sent(self, task_id: Any, status: str = "", shot_id: Any = None) -> int:
        """방금 Note·상태를 보낸 줄에 「보냄」을 달고, 바뀐 상태가 있으면 그 색으로 바로 보인다.

        샷그리드에서 다시 조회하지 않고 그 줄만 다시 그린다 — 줄의 원래 상태(``task_status``)는
        건드리지 않아, 갈래·필터에서 줄이 갑자기 사라지지 않고 스크롤 자리도 그대로다.
        다시 조회하면 샷그리드의 새 값으로 채워진다. 표시한 줄 수를 돌려준다.
        """
        if task_id is None and shot_id is None:
            return 0

        def hit(r: Dict[str, Any]) -> bool:
            if task_id is not None and r.get("task_id") == task_id:
                return True
            if task_id is not None and any(
                t.get("task_id") == task_id for t in r.get("tasks") or []
            ):
                return True  # Annotation 줄: 샷 한 줄에 태스크가 여럿
            return task_id is None and shot_id is not None and r.get("shot_id") == shot_id

        marked: List[Dict[str, Any]] = []
        for rows in [self._rows, *self._mode_rows.values()]:
            for r in rows:
                if hit(r) and not any(r is m for m in marked):
                    r["sent"] = True
                    if status:
                        r["sent_status"] = status
                    marked.append(r)
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = item.data(_ROLE)
            if isinstance(row, dict) and hit(row):
                row["sent"] = True
                if status:
                    row["sent_status"] = status
                item.setData(_ROLE, row)
                self._list.setItemWidget(item, self._make_row(row))
        return len(marked)

    def sent_status_of(self, task_id: Any) -> str:
        """이 창에서 보내서 바꾼 상태(없으면 빈 글) — 그 샷을 다시 열 때 머리 줄에 쓴다."""
        if task_id is None:
            return ""
        for rows in [self._rows, *self._mode_rows.values()]:
            for r in rows:
                if r.get("task_id") == task_id and r.get("sent_status"):
                    return str(r["sent_status"])
        return ""

    def _is_current(self, r: Dict[str, Any]) -> bool:
        return self._current_task is not None and r.get("task_id") == self._current_task

    @staticmethod
    def _status_code(r: Dict[str, Any]) -> str:
        """줄에 보일 상태 — 방금 보내서 바꾼 상태가 있으면 그것(다시 조회하기 전까지)."""
        return str(r.get("sent_status") or r.get("task_status") or "")

    def _row_html(self, r: Dict[str, Any]) -> str:
        code = self._status_code(r)
        status = escape(code)
        sub = row_subtitle(r)
        if self._annotation():  # 샷 한 줄에 태스크가 여럿 — 상태는 모두, 둘째 줄은 태스크들
            status = escape(annotation_status_text(r) or code)
            sub = annotation_subtitle(r)
        sent = (
            f'<span style="color:{style.OK}; font-size:{style.FONT_SMALL_PX}px">보냄</span>&nbsp; '
            if r.get("sent")
            else ""
        )
        return (
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td><b style="color:{style.TEXT_STRONG}; {style.mono()}">'
            f"{escape(str(r.get('shot_code') or ''))}</b></td>"
            f'<td align="right">{sent}<span style="color:{status_style.text_color(code)}; '
            f'{style.mono()}">{status}</span></td></tr></table>'
            f'<span style="color:{style.DIM}">{escape(sub)}</span>'
        )

    @staticmethod
    def _thumb_key(r: Dict[str, Any]) -> Any:
        """썸네일을 기억하는 열쇠 — 버전이 바뀌면 새 그림을 받는다."""
        return (r.get("task_id"), r.get("latest_version_id"))

    @staticmethod
    def _thumb_url(r: Dict[str, Any]) -> str:
        url = r.get("latest_version_image") or r.get("shot_image") or ""
        return url if isinstance(url, str) else ""

    def _make_row(self, r: Dict[str, Any]) -> QWidget:
        current = self._is_current(r)
        picked = self._seq_pick and r.get("task_id") in self._seq_keys
        edge = style.WARN if picked else style.ACCENT if current else "transparent"
        row = QWidget()
        row.setObjectName("drawer_row")
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.setStyleSheet(
            f"QWidget#drawer_row {{ border-left: {4 if picked else 2}px solid {edge}; "
            f"background: {style.RAISED if current or picked else 'transparent'}; }}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 6, 8, 6)
        lay.setSpacing(10)
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet(f"background: {style.FIELD}; border: 1px solid {style.EDGE};")
        key = self._thumb_key(r)
        if key in self._thumbs:
            thumb.setPixmap(self._thumbs[key])
        else:
            self._thumb_labels[key] = thumb
        lay.addWidget(thumb)
        text = QLabel(self._row_html(r))
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setIndent(0)
        lay.addWidget(text, 1)
        chip = QLabel()  # 상태 색 네모 + 아이콘
        chip.setFixedSize(16, 16)
        code = self._status_code(r)
        if code:
            chip.setPixmap(status_style.chip(code, 16))
        lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _refill(self) -> None:
        annotation = self._annotation()
        if annotation:
            self._shown = filter_annotation_rows(
                self._rows, search=self._search.text(), shot_ids=self._allowed_shot_ids()
            )
        else:
            vendor = str(self._vendor.currentData() or "") if self._group == GROUP_VENDOR else ""
            rows = filter_rows(self._rows, self._group, vendor=vendor, search=self._search.text())
            self._shown = sort_rows(rows, self._sort)
        self._list.clear()
        self._thumb_labels = {}
        for r in self._shown:
            item = QListWidgetItem()
            item.setData(_ROLE, r)
            item.setSizeHint(QSize(0, _ROW_H))
            self._list.addItem(item)
            self._list.setItemWidget(item, self._make_row(r))
        if self._loaded:
            self._count.setText(f"{len(self._shown)}{'샷' if annotation else '컷'}")
            empty = "이 갈래에는 확인 대기 샷이 없습니다"
            if annotation:
                narrowed = bool(self._facet_selection or self._search.text().strip())
                empty = "조건에 맞는 샷이 없습니다" if narrowed else "wtg · assign 인 샷이 없습니다"
            self._say("" if self._shown else empty)
        self._fetch_thumbs()
        self.rows_changed.emit()

    # ── 썸네일 ───────────────────────────────────────────────────

    def _fetch_thumbs(self) -> None:
        """보이는 줄 중 아직 그림이 없는 것을 줄 세워 받는다(한 번 청한 것은 다시 안 청한다)."""
        added = False
        for r in self._shown:
            key, url = self._thumb_key(r), self._thumb_url(r)
            if not url or key in self._thumbs or key in self._thumb_asked:
                continue
            self._thumb_asked.add(key)
            self._thumb_jobs.put((key, url))
            added = True
        if not added or self._closed:
            return
        self._thumb_workers = [w for w in self._thumb_workers if w.isRunning()]
        while len(self._thumb_workers) < _THUMB_THREADS:
            w = ThumbFetchWorker(self._thumb_jobs)
            w.thumb_ready.connect(self._on_thumb)
            w.start()
            self._thumb_workers.append(w)

    def _on_thumb(self, key: object, data: object) -> None:
        if self._closed or not isinstance(data, bytes):
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        scaled = pm.scaled(
            _THUMB_W,
            _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - _THUMB_W) // 2)
        y = max(0, (scaled.height() - _THUMB_H) // 2)
        self._thumbs[key] = scaled.copy(QRect(x, y, _THUMB_W, _THUMB_H))
        label = self._thumb_labels.pop(key, None)
        if label is not None:
            try:
                label.setPixmap(self._thumbs[key])
            except RuntimeError:  # 목록이 다시 그려져 그 줄이 사라진 경우
                pass

    def refresh_rows(self) -> None:
        """줄 모양만 다시 그린다(상태 색·아이콘이 바뀌었을 때)."""
        self._refill()

    def _on_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(_ROLE)
        if not isinstance(row, dict):
            return
        if self._seq_pick:  # 이어 볼 컷을 고르는 중 — 열지 않고 고르기만 한다
            self._toggle_seq_row(row)
            return
        self.task_picked.emit(row)

    def shutdown(self) -> None:
        self._closed = True
        for t in self._thumb_workers:
            t.stop()
        for t in self._thumb_workers:
            t.wait(3000)
        self._thumb_workers = []
        for w in self._workers:
            try:
                if w.isRunning():
                    w.wait(3000)
            except RuntimeError:
                pass
        self._workers.clear()
