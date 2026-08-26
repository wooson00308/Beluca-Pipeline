# @cursor-change: 2026-08-06, 0.2.x, LUT MOV 행 표시 시 겹침 방지 — 스크롤 영역 + 행 최소 높이
"""Publish tab — 완전 자동 채움 방식으로 MOV 업로드 + TimeLog 생성."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui.widgets.duration_widget import DurationWidget
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.gui.workers.upload_worker import UploadWorker
from bpe.shotgrid.client import get_default_sg, get_shotgun_for_version_mutation, resolve_sudo_login
from bpe.shotgrid.tasks import (
    merge_task_status_combo_options,
    parse_task_status_selection,
    update_task_status,
)
from bpe.shotgrid.timelogs import create_time_log
from bpe.shotgrid.versions import create_version

logger = logging.getLogger(__name__)

_LABEL_W = 130
_ROW_MIN_H = 30
_CRS2_032_PROJECT_CODE = "CRS2_032"
_MMK_PROJECT_CODE = "MMK_028"


def _info_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    """Read-only info row: [label 130px] [widget]."""
    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setObjectName("form_label")
    lbl.setFixedWidth(_LABEL_W)
    lbl.setMinimumHeight(_ROW_MIN_H)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


def _input_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    """Editable input row: [label 130px] [widget]."""
    return _info_row(label_text, widget)


def _read_only_line(text: str = "") -> QLineEdit:
    w = QLineEdit(text)
    w.setReadOnly(True)
    w.setMinimumHeight(_ROW_MIN_H)
    return w


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class PublishTab(QWidget):
    """Publish widget — task_data + user_id를 받아 자동 채움 후 Publish 실행."""

    def __init__(
        self,
        task_data: Dict[str, Any],
        user_id: int,
        user_name: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._task_data = task_data
        self._user_id = user_id
        self._user_name = user_name
        self._sudo_login: Optional[str] = None
        self._mov_path: Optional[str] = None
        self._lut_mov_path: Optional[str] = None
        self._workers: List[Any] = []
        self._publish_in_flight: bool = False
        self._timelog_phase_done: bool = False
        self._finalize_started: bool = False
        # job 큐: (version_name, mov_path)
        self._jobs: List[Tuple[str, str]] = []
        self._job_index: int = 0
        self._completed_versions: List[int] = []
        self._active_upload_version_id: Optional[int] = None
        self._publish_description: str = ""
        self._publish_status_code: Optional[str] = None

        self._build_ui()
        QTimer.singleShot(50, self._init_background)

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        td = self._task_data
        shot_code = td.get("shot_code", "")
        project_code = td.get("project_code") or td.get("project_name", "")
        task_content = td.get("task_content", "")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Publish")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        sub = QLabel("MOV 업로드  ·  Version 생성  ·  TimeLog")
        sub.setObjectName("page_subtitle")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(16)

        # ── Section: 자동 채움 정보 ─────────────────────────────────
        info_section = QLabel("Shot 정보  (자동 채움)")
        info_section.setObjectName("log_title")
        root.addWidget(info_section)
        root.addSpacing(8)

        info_block = QVBoxLayout()
        info_block.setSpacing(8)

        self._shot_label = _read_only_line(shot_code)
        info_block.addLayout(_info_row("Shot", self._shot_label))

        self._project_label = _read_only_line(project_code)
        info_block.addLayout(_info_row("Project", self._project_label))

        self._task_label = _read_only_line(task_content)
        info_block.addLayout(_info_row("Task", self._task_label))

        self._artist_label = _read_only_line(self._user_name or f"ID #{self._user_id}")
        info_block.addLayout(_info_row("Artist", self._artist_label))

        self._version_label = _read_only_line("탐색 중...")
        info_block.addLayout(_info_row("Version Name", self._version_label))

        self._mov_label = _read_only_line("렌더 MOV 탐색 중...")
        info_block.addLayout(_info_row("MOV 파일", self._mov_label))

        # 숨길 때 행 간격까지 함께 사라지도록 위젯으로 감싼다.
        self._lut_mov_label = _read_only_line("")
        lut_row_lay = _info_row("LUT MOV", self._lut_mov_label)
        lut_row_lay.setContentsMargins(0, 0, 0, 0)
        self._lut_mov_row = QWidget()
        self._lut_mov_row.setLayout(lut_row_lay)
        info_block.addWidget(self._lut_mov_row)
        self._set_lut_row_visible(False)

        root.addLayout(info_block)
        root.addSpacing(16)
        root.addWidget(_divider())
        root.addSpacing(16)

        # ── Section: 아티스트 입력 ──────────────────────────────────
        input_section = QLabel("퍼블리쉬 정보  (직접 입력)")
        input_section.setObjectName("log_title")
        root.addWidget(input_section)
        root.addSpacing(8)

        input_block = QVBoxLayout()
        input_block.setSpacing(10)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("수정 사항 또는 작업 내용을 입력하세요")
        self._desc_edit.setFixedHeight(72)
        self._desc_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_block.addLayout(_input_row("Description", self._desc_edit))

        self._status_combo = QComboBox()
        self._status_combo.addItems(merge_task_status_combo_options([]))
        self._status_combo.setCurrentText("wip — work in process")
        input_block.addLayout(_input_row("Task Status", self._status_combo))

        root.addLayout(input_block)
        root.addSpacing(16)
        root.addWidget(_divider())
        root.addSpacing(16)

        # ── Section: TimeLog ────────────────────────────────────────
        timelog_section = QLabel("Time Log  (선택 사항)")
        timelog_section.setObjectName("log_title")
        root.addWidget(timelog_section)
        root.addSpacing(8)

        tl_block = QVBoxLayout()
        tl_block.setSpacing(10)

        self._timelog_desc = QLineEdit()
        self._timelog_desc.setPlaceholderText("Description:")
        tl_block.addLayout(_input_row("Description:", self._timelog_desc))

        self._timelog_duration = DurationWidget(placeholder="Duration:")
        tl_block.addLayout(_input_row("Duration:", self._timelog_duration))

        root.addLayout(tl_block)
        root.addSpacing(20)
        root.addWidget(_divider())
        root.addSpacing(16)

        # ── Progress ────────────────────────────────────────────────
        self._status_msg = QLabel("")
        self._status_msg.setObjectName("status_msg")
        root.addWidget(self._status_msg)
        root.addSpacing(6)

        prog_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(14)
        prog_row.addWidget(self._progress, 1)
        self._pct_label = QLabel("0%")
        self._pct_label.setObjectName("status_msg")
        self._pct_label.setFixedWidth(40)
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self._pct_label)
        root.addLayout(prog_row)
        root.addSpacing(12)

        # ── Log ─────────────────────────────────────────────────────
        log_title = QLabel("로그")
        log_title.setObjectName("log_title")
        root.addWidget(log_title)
        root.addSpacing(4)

        self._log = QTextEdit()
        self._log.setObjectName("log_area")
        self._log.setReadOnly(True)
        self._log.setFixedHeight(100)
        root.addWidget(self._log)
        root.addSpacing(16)

        # ── Buttons ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setMinimumHeight(44)
        self._cancel_btn.setMinimumWidth(100)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)

        self._publish_btn = QPushButton("  Publish  ")
        self._publish_btn.setProperty("primary", True)
        self._publish_btn.setMinimumHeight(44)
        self._publish_btn.setMinimumWidth(120)
        self._publish_btn.setEnabled(False)
        self._publish_btn.clicked.connect(self._on_publish)
        btn_row.addWidget(self._publish_btn)

        root.addLayout(btn_row)

    def _set_lut_row_visible(self, visible: bool) -> None:
        """LUT MOV 행(라벨+필드) 표시/숨김."""
        self._lut_mov_row.setVisible(visible)

    # ── Background init ─────────────────────────────────────────────

    def _init_background(self) -> None:
        """백그라운드에서 MOV 탐색 + sudo_login 확인."""
        self._find_mov_async()
        self._resolve_sudo_login_async()

    def _find_mov_async(self) -> None:
        td = self._task_data
        shot_code = td.get("shot_code", "")
        project_code = td.get("project_code") or td.get("project_folder", "")
        # 태스크별 렌더 폴더 탐색용 (comp/빈값이면 기존 comp 후보 폴더 그대로).
        task_content = (td.get("task_content") or "").strip()

        if not shot_code or not project_code:
            self._mov_label.setText("shot_code / project_code 없음")
            self._log_msg("MOV 탐색 불가: task_data에 shot_code 또는 project_code 없음")
            return

        def _find() -> Dict[str, Optional[str]]:
            import os

            from bpe.core.nk_finder import (
                find_comp_render_mov,
                find_comp_render_mov_pair,
                find_server_root_auto,
            )

            env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
            server_root = find_server_root_auto(project_code) or env_root
            if not server_root:
                return {"mov": None, "lut": None}

            proj_u = (project_code or "").strip().upper()
            if proj_u == _MMK_PROJECT_CODE:
                mov, lut = find_comp_render_mov_pair(
                    shot_code,
                    project_code,
                    server_root,
                    task_content=task_content,
                )
                return {
                    "mov": str(mov) if mov else None,
                    "lut": str(lut) if lut else None,
                }
            if proj_u == _CRS2_032_PROJECT_CODE:
                mov = find_comp_render_mov(
                    shot_code,
                    project_code,
                    server_root,
                    exclude_lut_stem=True,
                    task_content=task_content,
                )
                return {"mov": str(mov) if mov else None, "lut": None}

            mov = find_comp_render_mov(
                shot_code,
                project_code,
                server_root,
                exclude_lut_stem=False,
                task_content=task_content,
            )
            return {"mov": str(mov) if mov else None, "lut": None}

        w = ShotGridWorker(_find)
        w.finished.connect(self._on_mov_found)
        w.error.connect(lambda e: self._on_mov_error(e))
        w.start()
        self._workers.append(w)

    def _on_mov_found(self, result: object) -> None:
        mov_path: Optional[str] = None
        lut_path: Optional[str] = None
        if isinstance(result, dict):
            raw_mov = result.get("mov")
            raw_lut = result.get("lut")
            mov_path = raw_mov if isinstance(raw_mov, str) else None
            lut_path = raw_lut if isinstance(raw_lut, str) else None
        elif isinstance(result, str):
            # 하위 호환 (단일 문자열)
            mov_path = result

        if not mov_path:
            from bpe.core.shot_builder import canonical_task_slug

            slug = canonical_task_slug(self._task_data.get("task_content") or "")
            self._mov_label.setText("렌더된 MOV 없음")
            self._mov_label.setStyleSheet("color: #e07070;")
            self._version_label.setText("—")
            self._set_lut_row_visible(False)
            self._log_msg(f"{slug}/devl/renders/ 아래 .mov 파일을 찾을 수 없습니다.")
            return

        from bpe.shotgrid.parser import parse_version_name_from_filename

        self._mov_path = mov_path
        safe_mov = normalize_path_str(mov_path)
        mov_name = Path(mov_path).name
        self._mov_label.setText(safe_mov)
        self._mov_label.setStyleSheet("")

        ver_name = parse_version_name_from_filename(mov_path)
        self._version_label.setText(ver_name)
        self._log_msg(f"MOV 발견: {mov_name}")

        if lut_path and Path(lut_path).is_file():
            self._lut_mov_path = lut_path
            safe_lut = normalize_path_str(lut_path)
            self._lut_mov_label.setText(safe_lut)
            self._set_lut_row_visible(True)
            lut_ver = parse_version_name_from_filename(lut_path)
            self._version_label.setText(f"{ver_name}  +  {lut_ver}")
            self._log_msg(f"LUT MOV 발견: {Path(lut_path).name}")
            self._log_msg("2개 파일 감지 — 일반 + LUT 동시 업로드")
        else:
            self._lut_mov_path = None
            self._set_lut_row_visible(False)

        self._try_enable_publish()

    def _on_mov_error(self, err: str) -> None:
        self._mov_label.setText("탐색 오류")
        self._mov_label.setStyleSheet("color: #e07070;")
        self._log_msg(f"MOV 탐색 오류: {err}")

    def _resolve_sudo_login_async(self) -> None:
        user_id = self._user_id

        def _resolve() -> Optional[str]:
            sg = get_default_sg()
            return resolve_sudo_login(sg, user_id)

        w = ShotGridWorker(_resolve)
        w.finished.connect(self._on_sudo_resolved)
        w.error.connect(lambda e: self._log_msg(f"sudo_login 확인 오류 (벨루카api로 진행됨): {e}"))
        w.start()
        self._workers.append(w)

    def _on_sudo_resolved(self, result: object) -> None:
        login = result
        if login and isinstance(login, str):
            self._sudo_login = login
            logger.debug("sudo_login resolved: %s", login)
        else:
            logger.debug("sudo_login not resolved — will use default script connection")

    def _try_enable_publish(self) -> None:
        """MOV가 있으면 Publish 버튼 활성화."""
        if self._mov_path and Path(self._mov_path).is_file():
            self._publish_btn.setEnabled(True)

    # ── Publish flow (job queue) ─────────────────────────────────────

    def _on_publish(self) -> None:
        if self._publish_in_flight:
            return
        if not self._mov_path or not Path(self._mov_path).is_file():
            self._log_msg("퍼블리쉬할 MOV 파일이 없습니다.")
            return

        td = self._task_data
        project_id = td.get("project_id")
        shot_id = td.get("shot_id")

        if not project_id or not shot_id:
            self._log_msg("Shot/Project ID를 확인할 수 없습니다.")
            return

        from bpe.shotgrid.parser import parse_version_name_from_filename

        jobs: List[Tuple[str, str]] = []
        jobs.append((parse_version_name_from_filename(self._mov_path), self._mov_path))
        if self._lut_mov_path and Path(self._lut_mov_path).is_file():
            jobs.append((parse_version_name_from_filename(self._lut_mov_path), self._lut_mov_path))

        if not jobs:
            self._log_msg("퍼블리쉬할 MOV 파일이 없습니다.")
            return

        self._jobs = jobs
        self._job_index = 0
        self._completed_versions = []
        self._active_upload_version_id = None
        self._publish_description = self._desc_edit.toPlainText().strip()
        self._publish_status_code = parse_task_status_selection(self._status_combo.currentText())

        self._publish_in_flight = True
        self._timelog_phase_done = False
        self._finalize_started = False
        self._publish_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._set_progress(5, "Version 생성 중...")
        if len(jobs) > 1:
            self._log_msg(f"퍼블리시 시작 — Version {len(jobs)}개 (일반 + LUT)")
        else:
            self._log_msg("Version 생성 중...")

        self._start_next_job()

    def _start_next_job(self) -> None:
        if self._job_index >= len(self._jobs):
            self._update_task_status()
            return

        version_name, _mov = self._jobs[self._job_index]
        n = len(self._jobs)
        td = self._task_data
        project_id = td.get("project_id")
        shot_id = td.get("shot_id")
        task_id = td.get("task_id")
        description = self._publish_description
        status_code = self._publish_status_code
        sudo_login = self._sudo_login
        user_id = self._user_id

        self._log_msg(f"[{self._job_index + 1}/{n}] Version 생성: {version_name}")
        self._set_progress(
            int(5 + (self._job_index / max(n, 1)) * 85),
            f"Version 생성 중... ({self._job_index + 1}/{n})",
        )

        def _create() -> Dict[str, Any]:
            sg = get_shotgun_for_version_mutation(sudo_login)
            return create_version(
                sg,
                project_id=project_id,
                shot_id=shot_id,
                task_id=task_id,
                version_name=version_name,
                description=description,
                artist_id=user_id,
                sg_status=status_code,
            )

        w = ShotGridWorker(_create)
        w.finished.connect(self._on_version_created)
        w.error.connect(self._on_create_error)
        w.start()
        self._workers.append(w)

    def _on_version_created(self, result: object) -> None:
        if self._job_index >= len(self._jobs):
            logger.warning(
                "version_created ignored: job_index=%s jobs=%s",
                self._job_index,
                len(self._jobs),
            )
            return

        ver = result
        if not isinstance(ver, dict) or "id" not in ver:
            self._log_msg(f"Version 생성 실패: {ver}")
            self._handle_job_failure("Version 생성 오류")
            return

        ver_id = ver["id"]
        _ver_name, mov_path = self._jobs[self._job_index]
        n = len(self._jobs)
        self._log_msg(f"Version #{ver_id} 생성 완료. MOV 업로드 시작...")

        base = 5 + (self._job_index / max(n, 1)) * 85
        span = 85 / max(n, 1)

        self._active_upload_version_id = ver_id
        uw = UploadWorker(ver_id, mov_path)
        uw.progress.connect(lambda v, b=base, s=span: self._set_progress(int(b + v * s)))
        uw.status.connect(lambda s: self._status_msg.setText(s))
        uw.done.connect(lambda vid=ver_id: self._on_upload_done(vid))
        uw.error.connect(self._on_upload_error)
        uw.start()
        self._workers.append(uw)

    def _on_upload_done(self, version_id: int) -> None:
        if self._active_upload_version_id != version_id:
            logger.debug(
                "upload_done ignored (duplicate or stale): got=%s active=%s",
                version_id,
                self._active_upload_version_id,
            )
            return
        self._active_upload_version_id = None
        self._completed_versions.append(version_id)
        self._log_msg(f"MOV 업로드 완료! (Version #{version_id})")
        self._job_index += 1
        if self._job_index < len(self._jobs):
            self._start_next_job()
        else:
            self._set_progress(92, "Task 상태 업데이트 중...")
            self._update_task_status()

    def _handle_job_failure(self, status: str) -> None:
        """job 실패 시 복구. 부분 성공이면 Publish 재활성화 금지."""
        self._active_upload_version_id = None
        self._status_msg.setText(status)
        if len(self._jobs) > 1 and self._completed_versions:
            self._log_msg(
                f"부분 완료: Version {self._completed_versions}. "
                "이미 올라간 Version이 있어 재Publish를 막았습니다."
            )
            self._publish_btn.setEnabled(False)
            # _publish_in_flight 유지 — 중복 방지
        else:
            self._publish_in_flight = False
            self._publish_btn.setEnabled(True)
        self._cancel_btn.setText("닫기")
        self._cancel_btn.setEnabled(True)

    def _update_task_status(self, version_id: Optional[int] = None) -> None:
        if self._finalize_started:
            return
        self._finalize_started = True

        status_sel = self._status_combo.currentText()
        status_code = parse_task_status_selection(status_sel)
        task_id = self._task_data.get("task_id")

        if status_code and task_id:

            def _update() -> Dict[str, Any]:
                sg = get_default_sg()
                return update_task_status(sg, task_id, status_code)

            w = ShotGridWorker(_update)
            w.finished.connect(lambda _: self._after_status_update(status_code))
            w.error.connect(lambda e: self._after_status_update(None, err=e))
            w.start()
            self._workers.append(w)
        else:
            self._after_status_update(None)

    def _after_status_update(self, status_code: Optional[str], err: Optional[str] = None) -> None:
        if status_code:
            self._log_msg(f"Task 상태 → {status_code}")
        if err:
            self._log_msg(f"Task 상태 변경 오류 (무시됨): {err}")

        self._create_time_log_if_needed()

    def _create_time_log_if_needed(self) -> None:
        if self._timelog_phase_done:
            return
        self._timelog_phase_done = True

        duration_minutes = self._timelog_duration.total_minutes()
        if duration_minutes < 1:
            self._finish_publish()
            return

        tl_desc = self._timelog_desc.text().strip()
        td = self._task_data
        project_id = td.get("project_id")
        task_id = td.get("task_id")
        user_id = self._user_id

        if not project_id or not task_id:
            self._log_msg("TimeLog: project_id / task_id 없음 — 건너뜀")
            self._finish_publish()
            return

        def _log() -> Dict[str, Any]:
            sg = get_default_sg()
            return create_time_log(
                sg,
                project_id=project_id,
                task_id=task_id,
                user_id=user_id,
                duration_minutes=duration_minutes,
                description=tl_desc,
            )

        w = ShotGridWorker(_log)
        w.finished.connect(lambda _: self._on_timelog_done(duration_minutes))
        w.error.connect(lambda e: self._on_timelog_error(e))
        w.start()
        self._workers.append(w)

    def _on_timelog_done(self, duration_minutes: int) -> None:
        self._log_msg(f"TimeLog 기록 완료: {duration_minutes}분")
        self._finish_publish()

    def _on_timelog_error(self, err: str) -> None:
        self._log_msg(f"TimeLog 생성 오류: {err}")
        self._finish_publish()

    def _finish_publish(self) -> None:
        self._set_progress(100, "퍼블리쉬 완료!")
        if len(self._completed_versions) > 1:
            self._log_msg(f"===== 퍼블리쉬 완료 (Version {self._completed_versions}) =====")
        else:
            self._log_msg("===== 퍼블리쉬 완료 =====")
        self._cancel_btn.setText("닫기")
        self._cancel_btn.setEnabled(True)

    def _on_upload_error(self, err: str) -> None:
        self._log_msg(f"업로드 오류: {err}")
        self._handle_job_failure("업로드 오류")

    def _on_create_error(self, err: str) -> None:
        self._log_msg(f"Version 생성 오류: {err}")
        self._handle_job_failure("Version 생성 오류")

    # ── Cancel ──────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "reject"):
            parent.reject()  # type: ignore[union-attr]

    # ── Helpers ─────────────────────────────────────────────────────

    def _log_msg(self, msg: str) -> None:
        self._log.append(msg)

    def _set_progress(self, value: int, status: str = "") -> None:
        self._progress.setValue(value)
        self._pct_label.setText(f"{value}%")
        if status:
            self._status_msg.setText(status)
