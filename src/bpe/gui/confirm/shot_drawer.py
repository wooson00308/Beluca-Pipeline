"""컨펌 창의 샷 목록 서랍 — 외주 / 내부 / TM / SV 갈래, 업체 고르기, 찾기, 정렬."""

from __future__ import annotations

import queue
from html import escape
from typing import Any, Dict, List, Optional, Tuple

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
    GROUPS,
    SORT_OLD,
    SORTS,
    filter_rows,
    row_subtitle,
    sort_rows,
    vendor_names,
)
from bpe.core.logging import get_logger
from bpe.core.settings import get_confirm_settings, save_confirm_settings
from bpe.gui.confirm import style
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


def _band(name: str, bg: str) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"QFrame#{name} {{ background: {bg}; border-bottom: 1px solid {style.EDGE}; }}")
    return f


class ShotDrawer(QWidget):
    """창 왼쪽에 겹쳐 뜨는 샷 목록."""

    task_picked = Signal(object)
    rows_changed = Signal()

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
        groups = QHBoxLayout()
        groups.setSpacing(0)
        self._group_btns: Dict[str, QPushButton] = {}
        for g in GROUPS:
            b = QPushButton(g)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, name=g: self._set_group(name))
            self._group_btns[g] = b
            groups.addWidget(b)
        style.make_segments(list(self._group_btns.values()))
        for b in self._group_btns.values():
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 0px 12px; }")
        hrow.addLayout(groups)
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
        outer.addWidget(filt)

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
        self._say("프로젝트를 고르면 확인 대기 샷이 나옵니다")

    def _reload(self) -> None:
        pid = self._project.currentData()
        if pid is None:
            return
        self._req += 1
        req = self._req
        self._say("목록 읽는 중…")

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.confirm_list import list_confirm_tasks

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
        for name, b in self._group_btns.items():
            b.setChecked(name == self._group)
        self._vendor.setEnabled(self._group == GROUPS[0])

    def shown_rows(self) -> List[Dict[str, Any]]:
        return list(self._shown)

    def summary(self) -> str:
        """위 막대의 목록 버튼에 적을 글(예: 「외주 6」). 아직 안 읽었으면 빈 글."""
        return f"{self._group} {len(self._shown)}" if self._loaded else ""

    def set_current_task(self, task_id: Any) -> None:
        """지금 열려 있는 샷을 목록에서 표시한다."""
        if task_id != self._current_task:
            self._current_task = task_id
            self._refill()

    def _is_current(self, r: Dict[str, Any]) -> bool:
        return self._current_task is not None and r.get("task_id") == self._current_task

    @staticmethod
    def _row_html(r: Dict[str, Any]) -> str:
        status = escape(str(r.get("task_status") or ""))
        return (
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td><b style="color:{style.TEXT_STRONG}; {style.mono()}">'
            f"{escape(str(r.get('shot_code') or ''))}</b></td>"
            f'<td align="right"><span style="color:{style.STATUS_DOT}; {style.mono()}">'
            f"{status}</span></td></tr></table>"
            f'<span style="color:{style.DIM}">{escape(row_subtitle(r))}</span>'
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
        row = QWidget()
        row.setObjectName("drawer_row")
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.setStyleSheet(
            f"QWidget#drawer_row {{ border-left: 2px solid "
            f"{style.ACCENT if current else 'transparent'}; "
            f"background: {style.RAISED if current else 'transparent'}; }}"
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
        return row

    def _refill(self) -> None:
        vendor = str(self._vendor.currentData() or "") if self._group == GROUPS[0] else ""
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
            self._count.setText(f"{len(self._shown)}컷")
            self._say("" if self._shown else "이 갈래에는 확인 대기 샷이 없습니다")
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

    def _on_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(_ROLE)
        if isinstance(row, dict):
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
