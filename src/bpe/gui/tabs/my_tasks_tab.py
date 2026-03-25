"""My Tasks tab — ShotGrid comp task list with thumbnails and NK open."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nk_finder import find_latest_nk_and_open
from bpe.gui.theme import ACCENT, BORDER
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.tasks import list_comp_tasks_for_project_user
from bpe.shotgrid.users import guess_human_user_for_me, search_human_users

logger = logging.getLogger(__name__)

_AUTOCOMPLETE_DELAY = 350
_THUMB_W = 80
_THUMB_H = 60


class _ShotCard(QFrame):
    """Single shot card widget inside the task list."""

    def __init__(
        self,
        task_data: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.task_data = task_data
        self.setObjectName("card")
        self._build(task_data)

    def _build(self, d: Dict[str, Any]) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        # Thumbnail placeholder (80x60)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB_W, _THUMB_H)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background-color: {BORDER}; border-radius: 4px; border: none;"
        )
        self.thumb_label.setText("img")
        lay.addWidget(self.thumb_label)

        # Info column (shot code, status, due date)
        info = QVBoxLayout()
        info.setSpacing(2)

        shot_code = d.get("shot_code", "")
        task_content = d.get("task_content", "")
        status = d.get("task_status", "")
        due = d.get("due_date") or ""

        title = QLabel(f"{shot_code}  —  {task_content}")
        title.setStyleSheet(f"font-weight: bold; border: none; color: {ACCENT};")
        info.addWidget(title)

        status_label = QLabel(f"상태: {status}")
        status_label.setObjectName("page_subtitle")
        status_label.setStyleSheet("border: none;")
        info.addWidget(status_label)

        due_label = QLabel(f"납기: {due}")
        due_label.setObjectName("page_subtitle")
        due_label.setStyleSheet("border: none;")
        info.addWidget(due_label)

        info.addStretch()
        lay.addLayout(info, 1)

        # NK open button
        btn = QPushButton("NK 열기")
        btn.setFixedWidth(72)
        btn.clicked.connect(self._open_nk)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _open_nk(self) -> None:
        d = self.task_data
        shot_code = d.get("shot_code", "")
        project_code = d.get("project_code") or d.get("project_folder", "")
        if not shot_code or not project_code:
            return
        import os

        server_root = os.environ.get("BPE_SERVER_ROOT", "")
        try:
            find_latest_nk_and_open(shot_code, project_code, server_root)
        except Exception as e:
            logger.warning("NK 열기 실패: %s", e)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            _THUMB_W,
            _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setText("")


class MyTasksTab(QWidget):
    """My Tasks tab: project/user filter → shot card list + notes."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._projects: List[Dict[str, Any]] = []
        self._user_id: Optional[int] = None
        self._cards: List[_ShotCard] = []
        self._workers: List[ShotGridWorker] = []

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

        # ── Splitter: card list (top) + notes (bottom) ──────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Card list inside QScrollArea
        card_area = QScrollArea()
        card_area.setWidgetResizable(True)
        card_area.setFrameShape(QFrame.Shape.NoFrame)
        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        card_area.setWidget(self._card_host)
        splitter.addWidget(card_area)

        # Notes panel
        note_panel = QWidget()
        note_lay = QVBoxLayout(note_panel)
        note_lay.setContentsMargins(8, 8, 8, 8)
        note_hdr = QHBoxLayout()
        note_title = QLabel("Notes")
        note_title.setObjectName("log_title")
        note_hdr.addWidget(note_title)
        note_hdr.addStretch()
        note_lay.addLayout(note_hdr)
        self._note_area = QLabel("샷을 선택하면 노트가 표시됩니다")
        self._note_area.setObjectName("page_subtitle")
        self._note_area.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._note_area.setWordWrap(True)
        note_lay.addWidget(self._note_area, 1)
        splitter.addWidget(note_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

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
            card = _ShotCard(t)
            self._cards.append(card)
            # Insert before the stretch
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

        # Kick off thumbnail downloads
        for card in self._cards:
            self._load_thumbnail(card)

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
