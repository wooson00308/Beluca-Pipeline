"""My Tasks tab — ShotGrid comp task list with thumbnails, NukeX open, shot folder."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.core.nk_finder import (
    find_latest_nk_and_open,
    find_server_root_auto,
    find_shot_folder,
)
from bpe.gui import theme
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.notes import list_notes_for_shots
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.tasks import list_comp_tasks_for_project_user
from bpe.shotgrid.users import guess_human_user_for_me, search_human_users

logger = get_logger("gui.tabs.my_tasks_tab")

_AUTOCOMPLETE_DELAY = 350
_THUMB_W = 160
_THUMB_H = 110

# Task status code -> (background hex, text hex) — ShotGrid-style palette
_STATUS_COLORS: Dict[str, Tuple[str, str]] = {
    "wtg": ("#FFFF00", "#111111"),
    "assign": ("#E8E4C0", "#111111"),
    "wip": ("#F0A0C0", "#111111"),
    "retake": ("#FF6600", "#FFFFFF"),
    "cfrm": ("#CCCCCC", "#111111"),
    "sv": ("#00AA00", "#FFFFFF"),
    "pub-s": ("#003399", "#FFFFFF"),
    "pubok": ("#00CCCC", "#111111"),
    "ct": ("#88AAFF", "#111111"),
    "cts": ("#007799", "#FFFFFF"),
    "ctr": ("#CC0000", "#FFFFFF"),
    "cto": ("#8800CC", "#FFFFFF"),
    "disent": ("#00AACC", "#FFFFFF"),
    "fin": ("#1A1A1A", "#FFFFFF"),
    "hld": ("#000000", "#FFFFFF"),
    "omt": ("#666666", "#FFFFFF"),
    "nocg": ("#444444", "#AAAAAA"),
    "error": ("#777777", "#FFFFFF"),
    "rev": ("#00AA77", "#FFFFFF"),
    "tm": ("#88CC88", "#111111"),
}


def _status_cell_colors(status_code: str) -> Tuple[str, str]:
    key = (status_code or "").strip().lower()
    return _STATUS_COLORS.get(key, (theme.PANEL_BG, theme.TEXT))


def _format_task_date(val: Any) -> str:
    if val is None:
        return "—"
    if isinstance(val, dict):
        inner = val.get("date") or val.get("name") or val.get("value")
        if inner is not None:
            return str(inner).strip() or "—"
        return "—"
    s = str(val).strip()
    return s if s else "—"


def _vline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(1)
    line.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
    return line


class _ShotCard(QFrame):
    """Single shot card widget inside the task list."""

    def __init__(
        self,
        task_data: Dict[str, Any],
        publish_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.task_data = task_data
        self._publish_callback = publish_callback
        self.setObjectName("card")
        self._build(task_data)

    def _build(self, d: Dict[str, Any]) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 8, 8)
        lay.setSpacing(0)

        # Thumbnail (fills cell; pixmap cropped in set_thumbnail)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB_W, _THUMB_H)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        self.thumb_label.setText("img")
        lay.addWidget(self.thumb_label)

        shot_code = d.get("shot_code", "")
        task_content = d.get("task_content", "")
        status = d.get("task_status", "")
        delivery = _format_task_date(d.get("delivery_date"))
        vfx_wo = (d.get("vfx_work_order") or "").strip()
        ver_raw = (d.get("latest_version_code") or "").strip()

        lay.addWidget(_vline())

        # Shot name, task, version (thumbnail right)
        info = QVBoxLayout()
        info.setSpacing(4)
        info.setContentsMargins(8, 0, 8, 0)
        title = QLabel(shot_code)
        title.setStyleSheet(f"font-weight: bold; border: none; color: {theme.ACCENT};")
        info.addWidget(title)
        task_line = QLabel(f"Task: {task_content}")
        task_line.setObjectName("page_subtitle")
        task_line.setStyleSheet(f"border: none; color: {theme.TEXT};")
        info.addWidget(task_line)
        version_line = QLabel(f"Version: {ver_raw}" if ver_raw else "Version: —")
        version_line.setObjectName("page_subtitle")
        version_line.setStyleSheet(f"border: none; color: {theme.TEXT};")
        info.addWidget(version_line)
        info.addStretch()
        lay.addLayout(info, 1)

        lay.addWidget(_vline())

        # Status cell (full background color)
        bg, fg = _status_cell_colors(status)
        status_cell = QWidget()
        status_cell.setFixedWidth(76)
        status_cell.setStyleSheet(f"background-color: {bg}; border: none;")
        st_lay = QVBoxLayout(status_cell)
        st_lay.setContentsMargins(6, 6, 6, 6)
        st_hdr = QLabel("STATUS")
        st_hdr.setStyleSheet(
            f"color: {fg}; font-size: 10px; border: none; background: transparent;"
        )
        st_val = QLabel((status or "—").strip() or "—")
        st_val.setWordWrap(True)
        st_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        st_val.setStyleSheet(
            f"color: {fg}; font-weight: bold; font-size: 13px; border: none; "
            "background: transparent;"
        )
        st_lay.addWidget(st_hdr)
        st_lay.addWidget(st_val)
        st_lay.addStretch()
        lay.addWidget(status_cell, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(_vline())

        # Delivery date column (Shot field)
        date_col = QWidget()
        date_col.setFixedWidth(100)
        dc_lay = QVBoxLayout(date_col)
        dc_lay.setContentsMargins(6, 6, 6, 6)
        dc_hdr = QLabel("Delivery date")
        dc_hdr.setObjectName("page_subtitle")
        dc_hdr.setStyleSheet("border: none;")
        dc_val = QLabel(delivery)
        dc_val.setWordWrap(True)
        dc_val.setStyleSheet(f"color: {theme.TEXT}; border: none;")
        dc_lay.addWidget(dc_hdr)
        dc_lay.addWidget(dc_val)
        dc_lay.addStretch()
        lay.addWidget(date_col, alignment=Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(_vline())

        # VFX work order (stretch)
        vfx_col = QWidget()
        vfx_lay = QVBoxLayout(vfx_col)
        vfx_lay.setContentsMargins(6, 6, 6, 6)
        vfx_hdr = QLabel("VFX work order")
        vfx_hdr.setObjectName("page_subtitle")
        vfx_hdr.setStyleSheet("border: none;")
        vfx_val = QLabel(vfx_wo if vfx_wo else "—")
        vfx_val.setWordWrap(True)
        vfx_val.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        vfx_val.setStyleSheet(f"color: {theme.TEXT}; border: none;")
        vfx_lay.addWidget(vfx_hdr)
        vfx_lay.addWidget(vfx_val)
        vfx_lay.addStretch()
        lay.addWidget(vfx_col, 2)

        lay.addWidget(_vline())

        # Action buttons (vertical stack)
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.setContentsMargins(4, 0, 0, 0)
        folder_btn = QPushButton("폴더 열기")
        folder_btn.setMinimumWidth(100)
        folder_btn.clicked.connect(self._open_shot_folder)
        btn_col.addWidget(folder_btn)

        nuke_btn = QPushButton("NukeX")
        nuke_btn.setMinimumWidth(72)
        nuke_btn.clicked.connect(self._open_nk)
        btn_col.addWidget(nuke_btn)

        publish_btn = QPushButton("퍼블리쉬")
        publish_btn.setMinimumWidth(80)
        publish_btn.clicked.connect(self._on_publish)
        btn_col.addWidget(publish_btn)
        btn_col.addStretch()
        lay.addLayout(btn_col)

    def _on_publish(self) -> None:
        if self._publish_callback is not None:
            self._publish_callback(self.task_data)

    def _open_shot_folder(self) -> None:
        d = self.task_data
        shot_code = d.get("shot_code", "")
        project_code = d.get("project_code") or d.get("project_folder", "")
        if not shot_code or not project_code:
            logger.warning("폴더 열기: shot_code 또는 project_code 없음")
            return

        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = find_server_root_auto(project_code) or env_root
        if not server_root:
            logger.warning(
                "폴더 열기: 서버 루트를 찾을 수 없음 (드라이브:\\vfx\\project_연도\\%s)",
                project_code,
            )
            return
        folder = find_shot_folder(shot_code, project_code, server_root)
        if folder is None or not folder.is_dir():
            logger.warning("폴더 열기: 샷 폴더를 찾을 수 없음 (%s)", shot_code)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _open_nk(self) -> None:
        d = self.task_data
        shot_code = d.get("shot_code", "")
        project_code = d.get("project_code") or d.get("project_folder", "")
        if not shot_code or not project_code:
            return

        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = find_server_root_auto(project_code) or env_root
        if not server_root:
            logger.warning(
                "NK 열기: 서버 루트를 찾을 수 없음 (드라이브:\\vfx\\project_연도\\%s)",
                project_code,
            )
            return
        try:
            find_latest_nk_and_open(shot_code, project_code, server_root)
        except Exception as e:
            logger.warning("NK 열기 실패: %s", e)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            _THUMB_W,
            _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - _THUMB_W) // 2)
        y = max(0, (scaled.height() - _THUMB_H) // 2)
        cropped = scaled.copy(QRect(x, y, _THUMB_W, _THUMB_H))
        self.thumb_label.setPixmap(cropped)
        self.thumb_label.setText("")


class MyTasksTab(QWidget):
    """My Tasks tab: project/user filter → shot card list + notes."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._projects: List[Dict[str, Any]] = []
        self._user_id: Optional[int] = None
        self._cards: List[_ShotCard] = []
        self._workers: List[ShotGridWorker] = []
        self._note_widgets: List[QFrame] = []
        self._last_shot_ids: List[int] = []
        self._notes_req_seq: int = 0
        self._splitter_halves_done: bool = False
        self._splitter_equalize_attempts: int = 0

        self._user_timer = QTimer(self)
        self._user_timer.setSingleShot(True)
        self._user_timer.timeout.connect(self._do_user_search)

        self._build_ui()
        QTimer.singleShot(200, self._load_projects)
        QTimer.singleShot(400, self._guess_me)

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)

        # ── Page header ────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("My Tasks")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        sub = QLabel("ShotGrid 배정 샷 조회")
        sub.setObjectName("page_subtitle")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(16)

        # ── Filter bar ─────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        proj_label = QLabel("프로젝트")
        proj_label.setObjectName("form_label")
        proj_label.setFixedWidth(60)
        filter_row.addWidget(proj_label)

        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(200)
        self._project_combo.addItem("-- 로딩 중 --")
        filter_row.addWidget(self._project_combo)

        user_label = QLabel("담당자")
        user_label.setObjectName("form_label")
        user_label.setFixedWidth(50)
        filter_row.addWidget(user_label)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("이름 입력 후 선택")
        self._user_edit.setMaximumWidth(170)
        self._user_edit.textChanged.connect(lambda: self._user_timer.start(_AUTOCOMPLETE_DELAY))
        filter_row.addWidget(self._user_edit)

        self._user_combo = QComboBox()
        self._user_combo.setVisible(False)
        self._user_combo.currentIndexChanged.connect(self._on_user_selected)
        filter_row.addWidget(self._user_combo)

        self._user_info = QLabel("")
        self._user_info.setObjectName("validation_label")
        self._user_info.setVisible(False)
        filter_row.addWidget(self._user_info)

        me_btn = QPushButton("나로 설정")
        me_btn.setFixedWidth(76)
        me_btn.clicked.connect(self._guess_me)
        filter_row.addWidget(me_btn)

        self._status_filter = QComboBox()
        self._status_filter.addItems(["(전체)", "wip", "retake", "wtg", "fin"])
        self._status_filter.setFixedWidth(100)
        filter_row.addWidget(self._status_filter)

        refresh_btn = QPushButton("  조회  ")
        refresh_btn.setProperty("primary", True)
        refresh_btn.clicked.connect(self._refresh)
        filter_row.addWidget(refresh_btn)

        filter_row.addStretch()
        root.addLayout(filter_row)

        # Loading indicator
        self._loading_label = QLabel("")
        self._loading_label.setObjectName("status_msg")
        root.addWidget(self._loading_label)

        # ── Splitter: card list (left) + notes (right) ─────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        # Shot list panel (header + scroll, mirrors note_panel)
        shot_panel = QWidget()
        shot_lay = QVBoxLayout(shot_panel)
        shot_lay.setContentsMargins(8, 8, 8, 8)

        shot_hdr = QHBoxLayout()
        shot_title = QLabel("샷 목록")
        shot_title.setObjectName("log_title")
        shot_hdr.addWidget(shot_title)
        shot_sub = QLabel("배정 comp 태스크")
        shot_sub.setObjectName("page_subtitle")
        shot_hdr.addWidget(shot_sub)
        shot_hdr.addStretch()
        shot_lay.addLayout(shot_hdr)

        card_area = QScrollArea()
        card_area.setWidgetResizable(True)
        card_area.setFrameShape(QFrame.Shape.NoFrame)
        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        card_area.setWidget(self._card_host)
        shot_lay.addWidget(card_area, 1)

        self._splitter.addWidget(shot_panel)

        # Right panel — panel selector + stacked (Notes | Shot Builder)
        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.setSpacing(6)

        # Panel toggle row
        sel_row = QHBoxLayout()
        sel_row.setSpacing(4)
        self._notes_panel_btn = QPushButton("Notes")
        self._notes_panel_btn.setProperty("selected", True)
        self._notes_panel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notes_panel_btn.clicked.connect(lambda: self._switch_right_panel(0))
        sel_row.addWidget(self._notes_panel_btn)
        self._shot_builder_panel_btn = QPushButton("Shot Builder")
        self._shot_builder_panel_btn.setProperty("selected", False)
        self._shot_builder_panel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._shot_builder_panel_btn.clicked.connect(lambda: self._switch_right_panel(1))
        sel_row.addWidget(self._shot_builder_panel_btn)
        sel_row.addStretch()
        right_lay.addLayout(sel_row)

        # Stacked widget
        self._right_stack = QStackedWidget()

        # ── Page 0: Notes ────────────────────────────────────────────
        notes_page = QWidget()
        notes_page_lay = QVBoxLayout(notes_page)
        notes_page_lay.setContentsMargins(0, 0, 0, 0)
        notes_page_lay.setSpacing(4)

        note_hdr = QHBoxLayout()
        note_title = QLabel("Notes")
        note_title.setObjectName("log_title")
        note_hdr.addWidget(note_title)
        note_sub = QLabel("최근 2주 코멘트")
        note_sub.setObjectName("page_subtitle")
        note_hdr.addWidget(note_sub)
        note_hdr.addStretch()
        note_refresh_btn = QPushButton("노트 새로고침")
        note_refresh_btn.setFixedWidth(120)
        note_refresh_btn.clicked.connect(self._refresh_notes_clicked)
        note_hdr.addWidget(note_refresh_btn)
        notes_page_lay.addLayout(note_hdr)

        note_scroll = QScrollArea()
        note_scroll.setWidgetResizable(True)
        note_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._note_host = QWidget()
        self._note_layout = QVBoxLayout(self._note_host)
        self._note_layout.setContentsMargins(0, 0, 0, 0)
        self._note_layout.setSpacing(6)
        self._note_layout.addStretch()
        note_scroll.setWidget(self._note_host)
        notes_page_lay.addWidget(note_scroll, 1)

        self._right_stack.addWidget(notes_page)

        # ── Page 1: Shot Builder ──────────────────────────────────────
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab

        self._shot_builder_panel = ShotBuilderTab()
        self._right_stack.addWidget(self._shot_builder_panel)

        right_lay.addWidget(self._right_stack, 1)
        self._splitter.addWidget(right_panel)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._splitter_halves_done:
            QTimer.singleShot(0, self._equalize_splitter_first_show)

    def _equalize_splitter_first_show(self) -> None:
        if self._splitter_halves_done:
            return
        w = self._splitter.width()
        if w <= 0:
            self._splitter_equalize_attempts += 1
            if self._splitter_equalize_attempts < 20:
                QTimer.singleShot(50, self._equalize_splitter_first_show)
            else:
                self._splitter_halves_done = True
            return
        self._splitter_halves_done = True
        half = w // 2
        self._splitter.setSizes([half, w - half])

    # ── Project loading ─────────────────────────────────────────────

    def _load_projects(self) -> None:
        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_active_projects(sg)

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_projects_loaded)
        w.error.connect(lambda e: self._loading_label.setText(f"프로젝트 로드 오류: {e}"))
        w.start()
        self._workers.append(w)

    def _on_projects_loaded(self, result: object) -> None:
        projects: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._projects = projects
        self._project_combo.clear()
        self._project_combo.addItem("(전체)", None)
        for p in projects:
            name = p.get("name") or p.get("code") or ""
            self._project_combo.addItem(name, p.get("id"))

    # ── User autocomplete / guess ───────────────────────────────────

    def _guess_me(self) -> None:
        def _fetch() -> Optional[Dict[str, Any]]:
            sg = get_default_sg()
            return guess_human_user_for_me(sg)

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_guess_me_result)
        w.error.connect(lambda e: self._user_info.setText(f"자동 감지 실패: {e}"))
        w.start()
        self._workers.append(w)

    def _on_guess_me_result(self, result: object) -> None:
        user = result  # type: ignore[assignment]
        if not user or not isinstance(user, dict):
            self._user_info.setText("자동 감지 실패")
            self._user_info.setVisible(True)
            return
        self._user_id = user.get("id")
        name = user.get("name") or user.get("login") or ""
        self._user_edit.setText(name)
        self._user_info.setText(f"✓ #{self._user_id}")
        self._user_info.setVisible(True)

    def _do_user_search(self) -> None:
        query = self._user_edit.text().strip()
        if len(query) < 2:
            self._user_combo.setVisible(False)
            return

        def _search() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return search_human_users(sg, query)

        w = ShotGridWorker(_search)
        w.finished.connect(self._on_user_results)
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _on_user_results(self, result: object) -> None:
        users: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._user_combo.clear()
        if users:
            self._user_combo.setVisible(True)
            for u in users:
                label = f"{u.get('name', '')} ({u.get('login', '')})"
                self._user_combo.addItem(label, u.get("id"))
        else:
            self._user_combo.setVisible(False)

    def _on_user_selected(self, idx: int) -> None:
        if idx < 0:
            return
        uid = self._user_combo.itemData(idx)
        if uid is not None:
            self._user_id = int(uid)
            self._user_info.setText(f"✓ #{self._user_id}")
            self._user_info.setVisible(True)

    # ── Refresh / fetch tasks ───────────────────────────────────────

    def _refresh(self) -> None:
        if self._user_id is None:
            self._loading_label.setText("담당자를 먼저 선택하세요.")
            return

        project_id = self._project_combo.currentData()
        user_id = self._user_id
        status_raw = self._status_filter.currentText()
        status = None if status_raw == "(전체)" else status_raw

        self._loading_label.setText("조회 중...")
        self._clear_cards()

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_comp_tasks_for_project_user(
                sg,
                project_id=project_id,
                human_user_id=user_id,
                status_filter=status,
            )

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_tasks_loaded)
        w.error.connect(lambda e: self._loading_label.setText(f"오류: {e}"))
        w.start()
        self._workers.append(w)

    def _on_tasks_loaded(self, result: object) -> None:
        tasks: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._loading_label.setText(f"{len(tasks)}개 Task 로드됨")
        self._clear_cards()
        for t in tasks:
            card = _ShotCard(t, publish_callback=self._open_publish_dialog)
            self._cards.append(card)
            # Insert before the stretch
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

        # Kick off thumbnail downloads
        for card in self._cards:
            self._load_thumbnail(card)

        # Kick off note loading
        shot_ids = [int(t.get("shot_id")) for t in tasks if t.get("shot_id") is not None]
        self._last_shot_ids = shot_ids
        if shot_ids:
            self._load_notes(shot_ids)
        else:
            self._clear_notes()
            self._add_note_placeholder("조회된 샷이 없습니다.")

    def _clear_cards(self) -> None:
        for card in self._cards:
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    # ── Thumbnail loading ───────────────────────────────────────────

    def _load_thumbnail(self, card: _ShotCard) -> None:
        img_url = card.task_data.get("shot_image")
        if not img_url or not isinstance(img_url, str):
            return

        def _download() -> Optional[bytes]:
            import urllib.request

            try:
                with urllib.request.urlopen(img_url, timeout=10) as resp:
                    return resp.read()
            except Exception:
                return None

        w = ShotGridWorker(_download)
        w.finished.connect(lambda data: self._apply_thumbnail(card, data))
        w.start()
        self._workers.append(w)

    def _apply_thumbnail(self, card: _ShotCard, data: object) -> None:
        if not data or not isinstance(data, bytes):
            return
        pm = QPixmap()
        pm.loadFromData(data)
        if not pm.isNull():
            card.set_thumbnail(pm)

    # ── Notes panel ──────────────────────────────────────────────────

    def _refresh_notes_clicked(self) -> None:
        if not self._last_shot_ids:
            self._loading_label.setText("먼저 조회를 실행하세요.")
            return
        self._load_notes(self._last_shot_ids)

    def _load_notes(self, shot_ids: List[int]) -> None:
        self._notes_req_seq += 1
        seq = self._notes_req_seq
        ids = [int(sid) for sid in shot_ids if sid is not None][:150]
        self._loading_label.setText("노트 불러오는 중...")

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_notes_for_shots(sg, ids)

        def _on_done(result: object) -> None:
            if seq != self._notes_req_seq:
                return
            notes: List[Dict[str, Any]] = result if isinstance(result, list) else []
            self._loading_label.setText("")
            self._render_notes(notes)

        def _on_error(msg: str) -> None:
            if seq != self._notes_req_seq:
                return
            self._loading_label.setText("")
            logger.warning("노트 로드 실패: %s", msg)
            self._clear_notes()
            self._add_note_placeholder("노트 로드 실패")

        w = ShotGridWorker(_fetch)
        w.finished.connect(_on_done)
        w.error.connect(_on_error)
        w.start()
        self._workers.append(w)

    def _clear_notes(self) -> None:
        for widget in self._note_widgets:
            self._note_layout.removeWidget(widget)
            widget.deleteLater()
        self._note_widgets.clear()

    def _add_note_placeholder(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("page_subtitle")
        self._note_layout.insertWidget(self._note_layout.count() - 1, lbl)
        self._note_widgets.append(lbl)  # type: ignore[arg-type]

    def _render_notes(self, notes: List[Dict[str, Any]]) -> None:
        self._clear_notes()
        if not notes:
            self._add_note_placeholder("코멘트가 없거나 아직 조회하지 않았습니다.")
            return
        for rec in notes:
            card = self._make_note_card(rec)
            self._note_layout.insertWidget(self._note_layout.count() - 1, card)
            self._note_widgets.append(card)

    def _make_note_card(self, rec: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        proj = (rec.get("project_name") or "—").strip()
        author = (rec.get("author") or "—").strip()
        context = (rec.get("context") or "—").strip()
        ts = (rec.get("timestamp") or "—").strip()
        meta = f"{proj}  ·  {author}  ·  {context}  ·  {ts}"

        meta_label = QLabel(meta)
        meta_label.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
        lay.addWidget(meta_label)

        raw = (rec.get("content") or rec.get("subject") or "—").strip()
        body = raw.replace("\n", " ").strip() or "—"
        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet(f"color: {theme.TEXT}; border: none;")
        lay.addWidget(body_label)

        return card

    # ── Right panel toggle ────────────────────────────────────────────

    def _switch_right_panel(self, idx: int) -> None:
        self._right_stack.setCurrentIndex(idx)
        for i, btn in enumerate([self._notes_panel_btn, self._shot_builder_panel_btn]):
            btn.setProperty("selected", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Publish dialog ────────────────────────────────────────────────

    def _open_publish_dialog(self, task_data: Dict[str, Any]) -> None:
        from bpe.gui.tabs.publish_tab import PublishTab

        dlg = QDialog(self)
        dlg.setWindowTitle("퍼블리쉬")
        dlg.setMinimumSize(720, 640)
        dlg.resize(820, 720)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        pub = PublishTab()
        lay.addWidget(pub)

        shot_code = task_data.get("shot_code", "")
        if shot_code:
            pub._shot_edit.setText(shot_code)
            pub._lookup_shot(shot_code)

        dlg.exec()
