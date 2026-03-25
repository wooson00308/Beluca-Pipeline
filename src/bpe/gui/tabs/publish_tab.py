"""Publish tab — MOV drop → ShotGrid Version create + upload."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.gui.workers.upload_worker import UploadWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.parser import parse_shot_code_from_filename, parse_version_name_from_filename
from bpe.shotgrid.shots import find_shot_any_project
from bpe.shotgrid.tasks import (
    find_tasks_for_shot,
    merge_task_status_combo_options,
    parse_task_status_selection,
    update_task_status,
)
from bpe.shotgrid.users import search_human_users
from bpe.shotgrid.versions import create_version

try:
    from bpe.gui.widgets.drop_zone import DropZone
except ImportError:
    DropZone = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Autocomplete debounce (ms)
_AUTOCOMPLETE_DELAY = 350


def _form_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    """Create a horizontal form row: [label 120px] [widget stretch]."""
    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setObjectName("form_label")
    lbl.setFixedWidth(120)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


class PublishTab(QWidget):
    """Publish tab: drop MOV → create Version → upload."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._shot_data: Optional[Dict[str, Any]] = None
        self._artist_id: Optional[int] = None
        self._task_id: Optional[int] = None
        self._tasks_cache: List[Dict[str, Any]] = []
        self._worker: Optional[ShotGridWorker] = None
        self._upload_worker: Optional[UploadWorker] = None

        self._artist_timer = QTimer(self)
        self._artist_timer.setSingleShot(True)
        self._artist_timer.timeout.connect(self._do_artist_search)

        self._task_timer = QTimer(self)
        self._task_timer.setSingleShot(True)
        self._task_timer.timeout.connect(self._do_task_search)

        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)

        # ── Page header ────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Publish")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        sub = QLabel("Version 업로드  ·  MOV 드래그 앤 드롭")
        sub.setObjectName("page_subtitle")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(16)

        # ── Scroll area ────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        content = QWidget()
        self._form_layout = QVBoxLayout(content)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(16)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        lay = self._form_layout

        # ── Drop zone ─────────────────────────────────────────────
        if DropZone is not None:
            self._drop_zone = DropZone()
            self._drop_zone.setObjectName("drop_zone")
            self._drop_zone.file_dropped.connect(self._on_file_dropped)
            lay.addWidget(self._drop_zone)
        else:
            self._drop_zone = QLabel(
                "MOV 파일을 여기에 드래그하거나 파일 경로를 직접 입력하세요\n(.mov / .mp4)"
            )
            self._drop_zone.setObjectName("drop_zone")
            self._drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._drop_zone.setMinimumHeight(80)
            lay.addWidget(self._drop_zone)

        # File path display
        self._path_label = QLineEdit()
        self._path_label.setPlaceholderText("파일 경로")
        self._path_label.setReadOnly(True)
        lay.addLayout(_form_row("File", self._path_label))

        # ── Form fields ───────────────────────────────────────────

        # Shot link
        self._shot_edit = QLineEdit()
        self._shot_edit.setPlaceholderText("MOV 드롭 시 자동 채움 또는 샷 코드 입력")
        self._shot_edit.editingFinished.connect(self._on_shot_manual)
        lay.addLayout(_form_row("Shot Link", self._shot_edit))

        self._shot_info = QLabel("")
        self._shot_info.setObjectName("validation_label")
        self._shot_info.setVisible(False)
        lay.addWidget(self._shot_info)

        # Version Name
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("MOV 드롭 시 자동 생성")
        lay.addLayout(_form_row("Version Name", self._version_edit))

        # Artist
        self._artist_edit = QLineEdit()
        self._artist_edit.setPlaceholderText("이름 또는 로그인 입력 (자동완성)")
        self._artist_edit.textChanged.connect(
            lambda: self._artist_timer.start(_AUTOCOMPLETE_DELAY)
        )
        lay.addLayout(_form_row("Artist", self._artist_edit))

        self._artist_combo = QComboBox()
        self._artist_combo.setVisible(False)
        self._artist_combo.currentIndexChanged.connect(self._on_artist_selected)
        lay.addWidget(self._artist_combo)

        self._artist_info = QLabel("")
        self._artist_info.setObjectName("validation_label")
        self._artist_info.setVisible(False)
        lay.addWidget(self._artist_info)

        # Task
        self._task_edit = QLineEdit()
        self._task_edit.setPlaceholderText("Task 이름 입력 (Shot 확정 후 자동완성)")
        self._task_edit.textChanged.connect(
            lambda: self._task_timer.start(_AUTOCOMPLETE_DELAY)
        )
        lay.addLayout(_form_row("Task", self._task_edit))

        self._task_combo = QComboBox()
        self._task_combo.setVisible(False)
        self._task_combo.currentIndexChanged.connect(self._on_task_selected)
        lay.addWidget(self._task_combo)

        self._task_info = QLabel("")
        self._task_info.setObjectName("validation_label")
        self._task_info.setVisible(False)
        lay.addWidget(self._task_info)

        # Description
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("수정 사항 또는 메모")
        self._desc_edit.setMaximumHeight(80)
        lay.addLayout(_form_row("Description", self._desc_edit))

        # Task Status
        self._status_combo = QComboBox()
        self._status_combo.addItems(merge_task_status_combo_options([]))
        self._status_combo.setCurrentText("(비움)")
        lay.addLayout(_form_row("Task Status", self._status_combo))

        # ── Action row ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._create_btn = QPushButton("  Create Version  ")
        self._create_btn.setProperty("primary", True)
        self._create_btn.setMinimumHeight(44)
        self._create_btn.clicked.connect(self._on_create_version)
        btn_row.addWidget(self._create_btn)

        self._test_btn = QPushButton("  연결 테스트  ")
        self._test_btn.setMinimumHeight(44)
        btn_row.addWidget(self._test_btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # ── Progress ──────────────────────────────────────────────
        self._status_msg = QLabel("")
        self._status_msg.setObjectName("status_msg")
        lay.addWidget(self._status_msg)

        prog_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        prog_row.addWidget(self._progress, 1)

        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("status_msg")
        self._percent_label.setFixedWidth(40)
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self._percent_label)
        lay.addLayout(prog_row)

        # ── Log area ─────────────────────────────────────────────
        log_title = QLabel("로그")
        log_title.setObjectName("log_title")
        lay.addWidget(log_title)

        self._log = QTextEdit()
        self._log.setObjectName("log_area")
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(140)
        lay.addWidget(self._log)

        lay.addStretch()

    # ── Logging helper ──────────────────────────────────────────────

    def _log_msg(self, msg: str) -> None:
        self._log.append(msg)

    # ── Progress helpers ────────────────────────────────────────────

    def _set_progress(self, value: int, status: str = "") -> None:
        self._progress.setValue(value)
        self._percent_label.setText(f"{value}%")
        if status:
            self._status_msg.setText(status)

    # ── File drop handling ──────────────────────────────────────────

    def _on_file_dropped(self, path: str) -> None:
        self._path_label.setText(path)
        shot_code = parse_shot_code_from_filename(path)
        version_name = parse_version_name_from_filename(path)
        self._version_edit.setText(version_name)

        if shot_code:
            self._shot_edit.setText(shot_code)
            self._log_msg(f"샷 코드 추출: {shot_code}")
            self._lookup_shot(shot_code)
        else:
            self._log_msg("파일명에서 샷 코드를 추출하지 못했습니다.")

    def _on_shot_manual(self) -> None:
        code = self._shot_edit.text().strip()
        if code:
            self._lookup_shot(code)

    # ── ShotGrid shot lookup ────────────────────────────────────────

    def _lookup_shot(self, shot_code: str) -> None:
        self._shot_info.setText("검색 중...")
        self._shot_info.setVisible(True)
        self._shot_data = None
        self._task_id = None

        def _find() -> Optional[Dict[str, Any]]:
            sg = get_default_sg()
            return find_shot_any_project(sg, shot_code)

        w = ShotGridWorker(_find)
        w.finished.connect(self._on_shot_found)
        w.error.connect(lambda e: self._on_shot_error(e))
        w.start()
        self._worker = w

    def _on_shot_found(self, result: object) -> None:
        shot = result  # type: ignore[assignment]
        if not shot or not isinstance(shot, dict):
            self._shot_info.setText("샷을 찾을 수 없습니다.")
            self._shot_info.setVisible(True)
            self._log_msg("샷 검색 결과 없음")
            return
        self._shot_data = shot
        proj = shot.get("project") or {}
        proj_name = proj.get("name") or proj.get("code") or ""
        self._shot_info.setText(
            f"✓ Shot #{shot.get('id')} — {shot.get('code', '')} ({proj_name})"
        )
        self._shot_info.setVisible(True)
        self._log_msg(f"샷 확인: {shot.get('code')} (project: {proj_name})")
        self._load_tasks_for_shot(shot["id"])

    def _on_shot_error(self, err: str) -> None:
        self._shot_info.setText(f"오류: {err}")
        self._shot_info.setVisible(True)
        self._log_msg(f"샷 검색 오류: {err}")

    # ── Task autocomplete ───────────────────────────────────────────

    def _load_tasks_for_shot(self, shot_id: int) -> None:
        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return find_tasks_for_shot(sg, shot_id)

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_tasks_loaded)
        w.error.connect(lambda e: self._log_msg(f"Task 로드 오류: {e}"))
        w.start()
        self._worker = w

    def _on_tasks_loaded(self, result: object) -> None:
        tasks: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._tasks_cache = tasks
        self._task_combo.clear()
        if tasks:
            self._task_combo.setVisible(True)
            for t in tasks:
                label = f"{t.get('content', '')} ({t.get('sg_status_list', '')})"
                self._task_combo.addItem(label, t.get("id"))
            self._on_task_selected(0)
            self._log_msg(f"Task {len(tasks)}개 로드됨")
        else:
            self._task_combo.setVisible(False)
            self._task_info.setText("Task 없음")
            self._task_info.setVisible(True)

    def _do_task_search(self) -> None:
        query = self._task_edit.text().strip()
        if not query or not self._tasks_cache:
            return
        q_lower = query.lower()
        self._task_combo.clear()
        matched = [
            t for t in self._tasks_cache
            if q_lower in (t.get("content") or "").lower()
        ]
        if matched:
            self._task_combo.setVisible(True)
            for t in matched:
                label = f"{t.get('content', '')} ({t.get('sg_status_list', '')})"
                self._task_combo.addItem(label, t.get("id"))
        else:
            self._task_combo.setVisible(False)

    def _on_task_selected(self, idx: int) -> None:
        if idx < 0:
            return
        tid = self._task_combo.itemData(idx)
        if tid is not None:
            self._task_id = int(tid)
            self._task_info.setText(f"✓ Task #{self._task_id}")
            self._task_info.setVisible(True)

    # ── Artist autocomplete ─────────────────────────────────────────

    def _do_artist_search(self) -> None:
        query = self._artist_edit.text().strip()
        if len(query) < 2:
            self._artist_combo.setVisible(False)
            return

        def _search() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return search_human_users(sg, query)

        w = ShotGridWorker(_search)
        w.finished.connect(self._on_artist_results)
        w.error.connect(lambda e: self._log_msg(f"Artist 검색 오류: {e}"))
        w.start()
        self._worker = w

    def _on_artist_results(self, result: object) -> None:
        users: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._artist_combo.clear()
        if users:
            self._artist_combo.setVisible(True)
            for u in users:
                label = f"{u.get('name', '')} ({u.get('login', '')})"
                self._artist_combo.addItem(label, u.get("id"))
        else:
            self._artist_combo.setVisible(False)

    def _on_artist_selected(self, idx: int) -> None:
        if idx < 0:
            return
        uid = self._artist_combo.itemData(idx)
        if uid is not None:
            self._artist_id = int(uid)
            name = self._artist_combo.itemText(idx)
            self._artist_info.setText(f"✓ {name}")
            self._artist_info.setVisible(True)

    # ── Create Version + Upload ─────────────────────────────────────

    def _on_create_version(self) -> None:
        mov_path = self._path_label.text().strip()
        if not mov_path:
            self._log_msg("파일을 먼저 드롭하세요.")
            return
        if not Path(mov_path).is_file():
            self._log_msg(f"파일이 존재하지 않습니다: {mov_path}")
            return
        if not self._shot_data:
            self._log_msg("Shot이 확정되지 않았습니다.")
            return

        version_name = self._version_edit.text().strip()
        if not version_name:
            self._log_msg("Version Name이 비어 있습니다.")
            return

        shot = self._shot_data
        proj = shot.get("project") or {}
        project_id = proj.get("id")
        shot_id = shot.get("id")
        if not project_id or not shot_id:
            self._log_msg("Shot/Project ID를 확인할 수 없습니다.")
            return

        description = self._desc_edit.toPlainText().strip()
        task_id = self._task_id
        artist_id = self._artist_id

        self._create_btn.setEnabled(False)
        self._set_progress(0, "Version 생성 중...")
        self._log_msg("Version 생성 중...")

        def _create() -> Dict[str, Any]:
            sg = get_default_sg()
            return create_version(
                sg,
                project_id=project_id,
                shot_id=shot_id,
                task_id=task_id,
                version_name=version_name,
                description=description,
                artist_id=artist_id,
            )

        w = ShotGridWorker(_create)
        w.finished.connect(lambda ver: self._on_version_created(ver, mov_path))
        w.error.connect(self._on_create_error)
        w.start()
        self._worker = w

    def _on_version_created(self, result: object, mov_path: str) -> None:
        ver = result  # type: ignore[assignment]
        if not isinstance(ver, dict) or "id" not in ver:
            self._log_msg(f"Version 생성 실패: {ver}")
            self._create_btn.setEnabled(True)
            return

        ver_id = ver["id"]
        self._log_msg(f"Version #{ver_id} 생성 완료. 업로드 시작...")
        self._set_progress(10, "업로드 중...")

        sg = get_default_sg()
        uw = UploadWorker(sg, ver_id, mov_path)
        uw.progress.connect(lambda v: self._set_progress(int(10 + v * 85)))
        uw.status.connect(lambda s: self._status_msg.setText(s))
        uw.finished.connect(lambda: self._on_upload_done(ver_id))
        uw.error.connect(self._on_upload_error)
        uw.start()
        self._upload_worker = uw

    def _on_upload_done(self, version_id: int) -> None:
        self._set_progress(100, "업로드 완료!")
        self._log_msg(f"업로드 완료! (Version #{version_id})")
        self._create_btn.setEnabled(True)
        self._update_task_status_if_needed()

    def _on_upload_error(self, err: str) -> None:
        self._status_msg.setText("업로드 오류")
        self._log_msg(f"업로드 오류: {err}")
        self._create_btn.setEnabled(True)

    def _on_create_error(self, err: str) -> None:
        self._status_msg.setText("Version 생성 오류")
        self._log_msg(f"Version 생성 오류: {err}")
        self._create_btn.setEnabled(True)

    def _update_task_status_if_needed(self) -> None:
        status_sel = self._status_combo.currentText()
        status_code = parse_task_status_selection(status_sel)
        if not status_code or not self._task_id:
            return

        task_id = self._task_id

        def _update() -> Dict[str, Any]:
            sg = get_default_sg()
            return update_task_status(sg, task_id, status_code)

        w = ShotGridWorker(_update)
        w.finished.connect(lambda _: self._log_msg(f"Task 상태 → {status_code}"))
        w.error.connect(lambda e: self._log_msg(f"Task 상태 변경 오류: {e}"))
        w.start()
        self._worker = w
