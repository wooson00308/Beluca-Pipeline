"""Feedback / review tab — SV·TM queue, FFmpeg preview, annotations, ShotGrid Notes."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.feedback_file_log import append_feedback_log_verbose
from bpe.core.feedback_project_paths import (
    effective_project_for_paths as _effective_project_for_paths_impl,
)
from bpe.core.logging import get_logger
from bpe.core.nk_finder import (
    find_server_root_auto,
    resolve_comp_renders_dir,
    resolve_local_comp_mov_for_feedback,
)
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.settings import get_feedback_frame_start
from bpe.gui import theme
from bpe.gui.feedback_panel_png import FEEDBACK_PANEL_ICON_PX, load_feedback_panel_icon
from bpe.gui.feedback_tool_icons import (
    make_arrow_tool_icon,
    make_ellipse_icon,
    make_rect_icon,
)
from bpe.gui.shotgrid_open_shot import setup_copy_shot_name_button, setup_shotgrid_open_shot_button
from bpe.gui.widgets.annotation_overlay import AnnotationTool
from bpe.gui.widgets.clickable_image import ClickableImage
from bpe.gui.widgets.progress_fill_button import ProgressFillButton
from bpe.gui.widgets.video_player_widget import VideoPlayerWidget
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg, get_shotgun_for_version_mutation, resolve_sudo_login
from bpe.shotgrid.notes import (
    CreateNoteResult,
    build_native_style_note_subject,
    create_note_with_result,
    download_attachment_bytes,
    get_note_attachments,
    list_notes_for_shots,
    note_addressings_from_assignees,
)
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.tasks import (
    BELUCA_TASK_STATUS_PRESETS,
    list_review_tasks_for_project,
    update_task_status,
)
from bpe.shotgrid.users import guess_human_user_for_me

# 피드백 툴바 버튼·팔레트 등 기존 크기 대비 1.2배 작게(÷1.2)
_FB_ICON_SCALE = 1.0 / 1.2

logger = get_logger("gui.tabs.feedback_tab")

_THUMB_W = 120
_THUMB_H = 82
_PNG_UPLOAD_MAX_EDGE = 1280


def _png_bytes_for_shotgrid_upload(data: bytes) -> bytes:
    """큰 PNG는 업로드 실패(네트워크·S3 파트)를 줄이기 위해 한 변 최대로 줄인다."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage

    img = QImage()
    if not img.loadFromData(data):
        return data
    w, h = img.width(), img.height()
    if w < 1 or h < 1:
        return data
    if max(w, h) <= _PNG_UPLOAD_MAX_EDGE:
        return data
    scaled = img.scaled(
        _PNG_UPLOAD_MAX_EDGE,
        _PNG_UPLOAD_MAX_EDGE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not scaled.save(buf, "PNG"):
        return data
    out = bytes(ba)
    return out if len(out) < len(data) else data


def _sanitize_feedback_filename_part(s: str, max_len: int = 48) -> str:
    t = re.sub(r"[^\w.\-]+", "_", (s or "").strip(), flags=re.UNICODE)
    t = t.strip("._") or "shot"
    return t[:max_len]


def _effective_project_for_paths(task: Dict[str, Any]) -> str:
    """SG Project.code가 비어 있을 때 로컬 vfx/project_연도/<폴더명> 탐색용 문자열."""
    return _effective_project_for_paths_impl(task)


def _shot_card_primary_title(task: Dict[str, Any]) -> str:
    """Queue card title: SG movie path basename, else Version code as ``.mov``, else shot code."""
    sg = (task.get("latest_version_sg_path") or "").strip()
    if sg:
        name = Path(sg.replace("\\", "/")).name.strip()
        if name:
            return name
    code = (task.get("latest_version_code") or "").strip()
    if code:
        low = code.lower()
        if low.endswith((".mov", ".mp4", ".mxf", ".avi", ".webm")):
            return code
        return f"{code}.mov"
    return (task.get("shot_code") or "").strip() or "—"


def _feedback_filt_chip_unselected_style() -> str:
    """SV/TM 필터 버튼 비선택 상태와 동일한 칩 스타일 (폴더열기 등)."""
    return (
        f"background: {theme.INPUT_BG}; color: {theme.TEXT}; "
        f"border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 12px;"
    )


def _first_task_assignee_name(task: Dict[str, Any]) -> str:
    """Version 업로더가 없을 때 Task 담당자 첫 명을 표시."""
    raw = task.get("task_assignees") or []
    if not isinstance(raw, list) or not raw:
        return ""
    u0 = raw[0]
    if isinstance(u0, dict):
        return str(u0.get("name") or "").strip()
    return ""


def _feedback_task_uploader_line(task: Dict[str, Any]) -> str:
    """카드 중간 줄: ``Comp: 이름`` (버전 업로더 우선, 없으면 태스크 담당자)."""
    tc = (task.get("task_content") or "").strip()
    tc_disp = (tc[:1].upper() + tc[1:].lower()) if tc else ""
    upl = (task.get("version_uploader_name") or "").strip()
    if not upl:
        upl = _first_task_assignee_name(task)
    if tc_disp and upl:
        return f"{tc_disp}: {upl}"
    if upl:
        return upl
    if tc_disp:
        return tc_disp
    return "—"


# 프로젝트 / 필터 행 첫 열(라벨) 너비 — 좌측 정렬 맞춤
_QUEUE_LABEL_COL_W = 72


class NoScrollComboBox(QComboBox):
    """휠·가운데 버튼 스크롤로 항목이 바뀌지 않도록 한다."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()


class FeedbackTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._workers: List[Any] = []
        self._projects: List[Dict[str, Any]] = []
        self._tasks: List[Dict[str, Any]] = []
        self._filter_statuses: List[str] = ["sv", "tm"]
        self._selected_task: Optional[Dict[str, Any]] = None
        self._selected_version_id: Optional[int] = None
        self._selected_version_code: str = ""
        self._shot_cards: List[QFrame] = []
        self._projects_bootstrapped = False
        self._proj_req_id = 0
        self._list_req_id = 0
        self._video_req_id = 0
        self._thumb_token: Dict[Any, int] = {}
        self._submit_busy = False
        self._notes_req_id = 0
        self._notes_attach_seq = 0
        self._current_mov_path: str = ""
        self._submit_btn_default_text = ""
        self._ann_by_frame: Dict[int, List[Dict[str, Any]]] = {}
        self._tracked_frame_idx: Optional[int] = None
        self._restoring_feedback_overlay = False

        self._submit_anim_timer = QTimer(self)
        self._submit_anim_timer.setInterval(110)
        self._submit_anim_timer.timeout.connect(self._on_submit_progress_anim_tick)

        self._build_ui()
        self._submit_btn_default_text = self._submit_btn.text()
        self._video.frame_index_changed.connect(self._on_feedback_video_frame_changed)
        self._video.annotation_overlay.changed.connect(self._on_feedback_overlay_changed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self._main_split = split

        # ── Center: 빨강·초록·영상(핑크는 VideoPlayer 내부) ───────────
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)

        self._header_title = QLabel("")
        self._header_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._header_title.setStyleSheet(
            f"font-size: 19px; font-weight: 700; color: {theme.TEXT}; border: none;"
        )
        self._header_title.setWordWrap(True)

        self._header_sub = QLabel("")
        self._header_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._header_sub.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 13px; border: none;")

        # VideoPlayer는 초록 툴바(두께·색·undo)가 annotation_overlay를 쓰므로 먼저 만든다.
        self._video = VideoPlayerWidget()
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        green_inner = QWidget()
        gh = QHBoxLayout(green_inner)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.setSpacing(4)

        self._ann_tool_group = QButtonGroup(self)
        self._ann_tool_group.setExclusive(True)

        _tb_icon_px = FEEDBACK_PANEL_ICON_PX

        _tb_col = QColor(theme.TEXT)
        _ico_move = load_feedback_panel_icon("feedback_move", FEEDBACK_PANEL_ICON_PX)
        _ico_txt = load_feedback_panel_icon("feedback_text", FEEDBACK_PANEL_ICON_PX)
        _ico_pen = load_feedback_panel_icon("feedback_pen", FEEDBACK_PANEL_ICON_PX)

        def _mk_tool_btn(tip: str, *, text: str = "", icon: Optional[QIcon] = None) -> QToolButton:
            b = QToolButton()
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setFixedSize(max(28, round(45 * _FB_ICON_SCALE)), max(26, round(42 * _FB_ICON_SCALE)))
            b.setStyleSheet(
                f"QToolButton {{ color: {theme.TEXT}; border: none; border-radius: 4px; }}"
                f"QToolButton:checked {{ background-color: rgba(45, 139, 122, 0.42); "
                f"border: 1px solid {theme.ACCENT}; }}"
                f"QToolButton:hover {{ background-color: rgba(255,255,255,0.07); }}"
            )
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(_tb_icon_px, _tb_icon_px))
            else:
                b.setText(text)
            return b

        self._tool_none = _mk_tool_btn(
            "이동 / 선택(끔)",
            icon=_ico_move,
        )
        self._tool_pen = _mk_tool_btn("펜", icon=_ico_pen)
        self._tool_arrow = _mk_tool_btn("화살표", icon=make_arrow_tool_icon(_tb_icon_px, _tb_col))
        self._tool_rect = _mk_tool_btn("사각형", icon=make_rect_icon(_tb_icon_px, _tb_col))
        self._tool_ell = _mk_tool_btn("타원", icon=make_ellipse_icon(_tb_icon_px, _tb_col))
        self._tool_txt = _mk_tool_btn("텍스트", icon=_ico_txt)

        self._ann_tool_group.addButton(self._tool_none, int(AnnotationTool.NONE))
        self._ann_tool_group.addButton(self._tool_pen, int(AnnotationTool.PEN))
        self._ann_tool_group.addButton(self._tool_arrow, int(AnnotationTool.ARROW))
        self._ann_tool_group.addButton(self._tool_rect, int(AnnotationTool.RECT))
        self._ann_tool_group.addButton(self._tool_ell, int(AnnotationTool.ELLIPSE))
        self._ann_tool_group.addButton(self._tool_txt, int(AnnotationTool.TEXT))
        self._ann_tool_group.idClicked.connect(self._on_ann_tool_group_id)

        for tb in (
            self._tool_none,
            self._tool_pen,
            self._tool_arrow,
            self._tool_rect,
            self._tool_ell,
            self._tool_txt,
        ):
            gh.addWidget(tb)

        gh.addSpacing(8)
        gh.addWidget(QLabel("px"))
        self._ann_width_spin = QSpinBox()
        self._ann_width_spin.setRange(1, 48)
        self._ann_width_spin.setValue(3)
        self._ann_width_spin.setFixedWidth(max(52, round(78 * _FB_ICON_SCALE)))
        self._ann_width_spin.valueChanged.connect(
            lambda v: self._video.annotation_overlay.set_pen_width(int(v))
        )
        self._video.annotation_overlay.set_pen_width(self._ann_width_spin.value())
        gh.addWidget(self._ann_width_spin)

        self._palette_by_hex: Dict[str, QToolButton] = {}
        for hex_c, tip in (
            ("#ff0000", "빨강"),
            ("#ffff00", "노랑"),
            ("#ffffff", "흰색"),
            ("#3b82f6", "파랑"),
            ("#22c55e", "초록"),
        ):
            cb = QToolButton()
            cb.setText("●")
            cb.setToolTip(tip)
            cb.setAutoRaise(True)
            _ps = max(28, round(39 * _FB_ICON_SCALE))
            cb.setFixedSize(_ps, _ps)
            cb.clicked.connect(lambda _=False, h=hex_c: self._on_ann_palette_pick(h))
            self._palette_by_hex[hex_c] = cb
            gh.addWidget(cb)

        gh.addStretch()

        tools_scroll = QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tools_scroll.setMaximumHeight(max(56, round(78 * _FB_ICON_SCALE)))
        tools_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        tools_scroll.setWidget(green_inner)
        tools_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.addStretch(1)
        tools_row.addWidget(tools_scroll, 0)
        tools_row.addStretch(1)

        self._left_queue_header = QWidget()
        lqh = QVBoxLayout(self._left_queue_header)
        lqh.setContentsMargins(0, 0, 0, 0)
        lqh.setSpacing(6)
        lqh.addWidget(self._header_title)
        lqh.addWidget(self._header_sub)
        lqh.addLayout(tools_row)
        cl.addWidget(self._left_queue_header)

        self._tool_none.setChecked(True)
        self._style_ann_palette_selection("#ffffff")

        self._video_host = QWidget()
        vvh = QVBoxLayout(self._video_host)
        vvh.setContentsMargins(0, 0, 0, 0)
        vvh.setSpacing(4)
        ann_actions = QHBoxLayout()
        ann_actions.setContentsMargins(0, 0, 0, 0)
        ann_actions.addStretch(1)
        self._btn_feedback_undo = QToolButton()
        self._btn_feedback_undo.setIcon(
            load_feedback_panel_icon("feedback_undo", FEEDBACK_PANEL_ICON_PX)
        )
        self._btn_feedback_undo.setIconSize(QSize(FEEDBACK_PANEL_ICON_PX, FEEDBACK_PANEL_ICON_PX))
        self._btn_feedback_undo.setToolTip("실행 취소 (주석 한 단계)")
        self._btn_feedback_undo.setAutoRaise(True)
        _ann_act_w = max(28, round(40 * _FB_ICON_SCALE))
        _ann_act_h = max(26, round(36 * _FB_ICON_SCALE))
        self._btn_feedback_undo.setFixedSize(_ann_act_w, _ann_act_h)
        self._btn_feedback_undo.clicked.connect(self._video.annotation_overlay.undo_last)
        _undo_fx = QGraphicsOpacityEffect(self._btn_feedback_undo)
        _undo_fx.setOpacity(0.8)
        self._btn_feedback_undo.setGraphicsEffect(_undo_fx)
        self._btn_feedback_clear = QToolButton()
        self._btn_feedback_clear.setIcon(
            load_feedback_panel_icon("feedback_clear", FEEDBACK_PANEL_ICON_PX)
        )
        self._btn_feedback_clear.setIconSize(QSize(FEEDBACK_PANEL_ICON_PX, FEEDBACK_PANEL_ICON_PX))
        self._btn_feedback_clear.setToolTip("모두 지우기")
        self._btn_feedback_clear.setAutoRaise(True)
        self._btn_feedback_clear.setFixedSize(_ann_act_w, _ann_act_h)
        self._btn_feedback_clear.clicked.connect(self._video.annotation_overlay.clear_all)
        _clear_fx = QGraphicsOpacityEffect(self._btn_feedback_clear)
        _clear_fx.setOpacity(0.8)
        self._btn_feedback_clear.setGraphicsEffect(_clear_fx)
        ann_actions.addWidget(self._btn_feedback_undo)
        ann_actions.addWidget(self._btn_feedback_clear)
        vvh.addLayout(ann_actions)
        vvh.addWidget(self._video, 1)

        cl.addWidget(self._video_host, 1)

        center.setMinimumWidth(480)
        split.addWidget(center)

        # ── Right: 대기열 | 노트 스택 ──────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._right_stack = QStackedWidget()

        page_queue = QWidget()
        pql = QVBoxLayout(page_queue)
        pql.setContentsMargins(0, 0, 0, 0)
        pql.setSpacing(8)

        row1 = QHBoxLayout()
        _proj_lbl = QLabel("프로젝트")
        _proj_lbl.setFixedWidth(_QUEUE_LABEL_COL_W)
        row1.addWidget(_proj_lbl)
        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(160)
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)
        row1.addWidget(self._project_combo, 1)
        self._refresh_btn = QPushButton("조회")
        self._refresh_btn.clicked.connect(self._reload_tasks)
        row1.addWidget(self._refresh_btn)

        filt = QHBoxLayout()
        _filt_lbl_sp = QLabel("")
        _filt_lbl_sp.setFixedWidth(_QUEUE_LABEL_COL_W)
        filt.addWidget(_filt_lbl_sp)
        self._btn_all = QPushButton("SV+TM")
        self._btn_sv = QPushButton("SV")
        self._btn_tm = QPushButton("TM")
        self._filt_group = QButtonGroup(self)
        self._filt_group.setExclusive(True)
        self._btn_all.setCheckable(True)
        self._btn_sv.setCheckable(True)
        self._btn_tm.setCheckable(True)
        self._filt_group.addButton(self._btn_all, 0)
        self._filt_group.addButton(self._btn_sv, 1)
        self._filt_group.addButton(self._btn_tm, 2)
        for b in (self._btn_all, self._btn_sv, self._btn_tm):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_all.setChecked(True)
        self._filt_group.idClicked.connect(self._on_filter_group_id)
        filt.addWidget(self._btn_all)
        filt.addWidget(self._btn_sv)
        filt.addWidget(self._btn_tm)
        filt.addStretch()
        self._apply_filt_btn_style()

        self._task_status_lbl = QLabel("")
        self._task_status_lbl.setObjectName("page_subtitle")

        self._right_queue_header = QWidget()
        rqh = QVBoxLayout(self._right_queue_header)
        rqh.setContentsMargins(0, 0, 0, 0)
        rqh.setSpacing(8)
        rqh.addLayout(row1)
        rqh.addLayout(filt)
        rqh.addWidget(self._task_status_lbl)

        self._queue_align_spacer = QWidget()
        self._queue_align_spacer.setFixedHeight(0)

        pql.addWidget(self._right_queue_header)
        pql.addWidget(self._queue_align_spacer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 4, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_host)
        pql.addWidget(scroll, 1)

        self._right_stack.addWidget(page_queue)

        page_notes = QWidget()
        pnl = QVBoxLayout(page_notes)
        pnl.setContentsMargins(0, 0, 0, 0)
        pnl.setSpacing(8)

        back_row = QHBoxLayout()
        self._btn_back_queue = QPushButton("← 목록으로")
        self._btn_back_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_back_queue.clicked.connect(self._on_back_to_queue)
        back_row.addWidget(self._btn_back_queue)
        back_row.addStretch()
        pnl.addLayout(back_row)

        self._notes_title_lbl = QLabel("")
        self._notes_title_lbl.setWordWrap(True)
        self._notes_title_lbl.setStyleSheet(
            f"font-weight: 700; color: {theme.ACCENT}; border: none;"
        )
        pnl.addWidget(self._notes_title_lbl)

        notes_scroll = QScrollArea()
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._notes_host = QWidget()
        self._notes_layout = QVBoxLayout(self._notes_host)
        self._notes_layout.setContentsMargins(4, 4, 4, 4)
        self._notes_layout.setSpacing(8)
        self._notes_layout.addStretch()
        notes_scroll.setWidget(self._notes_host)
        pnl.addWidget(notes_scroll, 1)

        st_note = QHBoxLayout()
        st_note.addWidget(QLabel("태스크 상태:"))
        self._notes_status_combo = NoScrollComboBox()
        for scode, lbl in BELUCA_TASK_STATUS_PRESETS:
            self._notes_status_combo.addItem(f"{scode} — {lbl}", scode)
        self._notes_status_combo.currentIndexChanged.connect(self._on_notes_status_combo)
        st_note.addWidget(self._notes_status_combo, 1)
        pnl.addLayout(st_note)

        pnl.addWidget(QLabel("코멘트"))
        self._comment = QPlainTextEdit()
        self._comment.setPlaceholderText("작업자에게 전달할 피드백을 입력하세요.")
        self._comment.setMinimumHeight(120)
        self._comment.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        pnl.addWidget(self._comment, 0)

        self._submit_btn = ProgressFillButton("ShotGrid에 노트 제출")
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.setMinimumHeight(theme.BUTTON_HEIGHT)
        self._submit_btn.clicked.connect(self._submit_note)
        pnl.addWidget(self._submit_btn)

        self._right_stack.addWidget(page_notes)

        rl.addWidget(self._right_stack, 1)
        right.setMinimumWidth(300)
        split.addWidget(right)

        split.setStretchFactor(0, 7)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        QTimer.singleShot(0, self._sync_queue_panel_alignment)
        self._sync_feedback_video_placeholder()

    def _sync_feedback_video_placeholder(self) -> None:
        """프로젝트 미선택 시 플레이어 슬라이더 숨김·로고 표시."""
        pid = self._project_combo.currentData()
        self._video.set_feedback_project_selected(pid is not None)

    def _apply_filt_btn_style(self) -> None:
        sel = (
            f"background: {theme.ACCENT}; color: #fff; border-radius: 6px; "
            f"padding: 6px 12px; border: 1px solid {theme.ACCENT};"
        )
        unsel = (
            f"background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 12px;"
        )
        for b in (self._btn_all, self._btn_sv, self._btn_tm):
            b.setStyleSheet(sel if b.isChecked() else unsel)

    def _sync_queue_panel_alignment(self) -> None:
        if not self.isVisible():
            return
        self._left_queue_header.updateGeometry()
        self._right_queue_header.updateGeometry()
        h_l = self._left_queue_header.height()
        if h_l <= 0:
            h_l = self._left_queue_header.sizeHint().height()
        h_r = self._right_queue_header.height()
        if h_r <= 0:
            h_r = self._right_queue_header.sizeHint().height()
        gap = max(0, h_l - h_r)
        self._queue_align_spacer.setFixedHeight(gap)

    def _on_ann_tool_group_id(self, btn_id: int) -> None:
        try:
            self._set_ann_tool(AnnotationTool(btn_id))
        except ValueError:
            pass

    def _on_ann_palette_pick(self, hex_c: str) -> None:
        self._video.annotation_overlay.set_color(QColor(hex_c))
        self._style_ann_palette_selection(hex_c)

    def _style_ann_palette_selection(self, selected_hex: str) -> None:
        sel = (selected_hex or "").strip().lower()
        for h, btn in self._palette_by_hex.items():
            ring = f"2px solid {theme.ACCENT}" if h.lower() == sel else "none"
            btn.setStyleSheet(
                f"color: {h}; font-size: 21px; border: {ring}; border-radius: 20px; padding: 2px;"
            )

    def _on_submit_progress_anim_tick(self) -> None:
        if not self._submit_busy:
            self._submit_anim_timer.stop()
            return
        cur = self._submit_btn.fill_ratio()
        if cur >= 0.92:
            return
        self._submit_btn.set_fill_ratio(min(0.92, cur + 0.024))

    def _start_submit_progress_animation(self) -> None:
        if not self._submit_anim_timer.isActive():
            self._submit_anim_timer.start()

    def _restore_submit_ui_after_note(self) -> None:
        self._submit_anim_timer.stop()
        self._submit_btn.reset_progress_visual()
        self._submit_btn.setEnabled(True)
        self._submit_btn.setText(self._submit_btn_default_text)

    def _on_back_to_queue(self) -> None:
        self._right_stack.setCurrentIndex(0)

    def _refresh_header_labels(self, mov_path: Optional[str] = None) -> None:
        task = self._selected_task
        if not task:
            self._header_title.setText("")
            self._header_sub.setText("")
            return
        proj = (task.get("project_code") or task.get("project_name") or "").strip()
        ver = (self._selected_version_code or task.get("latest_version_code") or "").strip()
        shot = (task.get("shot_code") or "").strip()
        base = ""
        if mov_path:
            base = Path(mov_path).name
        title = base or ver or shot
        self._header_title.setText(title)
        self._header_sub.setText(f"In Project: {proj}" if proj else "")

    def _set_ann_tool(self, tool: AnnotationTool) -> None:
        self._video.annotation_overlay.set_tool(tool)
        bid = int(tool)
        btn = self._ann_tool_group.button(bid)
        if btn is not None:
            btn.setChecked(True)

    def _sync_ann_tool_buttons(self) -> None:
        t = self._video.annotation_overlay.tool
        for btn in self._ann_tool_group.buttons():
            if self._ann_tool_group.id(btn) == int(t):
                btn.setChecked(True)
                break

    def _sync_notes_status_combo(self) -> None:
        task = self._selected_task
        if not task:
            return
        cur = (task.get("task_status") or "").strip().lower()
        self._notes_status_combo.blockSignals(True)
        for i in range(self._notes_status_combo.count()):
            if str(self._notes_status_combo.itemData(i) or "").strip().lower() == cur:
                self._notes_status_combo.setCurrentIndex(i)
                break
        self._notes_status_combo.blockSignals(False)
        self._apply_combo_status_colors(self._notes_status_combo, cur)

    def _on_notes_status_combo(self, _idx: int = 0) -> None:
        task = self._selected_task
        if not task:
            return
        self._on_task_status_combo(task, self._notes_status_combo)

    def _clear_note_rows(self) -> None:
        while self._notes_layout.count() > 1:
            item = self._notes_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _load_notes_for_shot(self) -> None:
        task = self._selected_task
        if not task:
            return
        sid = task.get("shot_id")
        if sid is None:
            return
        self._notes_req_id += 1
        req = self._notes_req_id

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_notes_for_shots(sg, [int(sid)], days_back=0, limit=250)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req: self._on_notes_loaded(r, q))
        w.error.connect(lambda e, q=req: self._on_notes_load_error(e, q))
        w.start()
        self._workers.append(w)

    def _on_notes_load_error(self, err: str, req: int) -> None:
        if req != self._notes_req_id:
            return
        self._clear_note_rows()
        err_lbl = QLabel(f"(노트 조회 실패: {err})")
        err_lbl.setWordWrap(True)
        self._notes_layout.insertWidget(0, err_lbl)

    def _load_feedback_note_attachments(
        self, note_id: int, fr: QFrame, fl: QVBoxLayout, seq: int
    ) -> None:
        def _fetch() -> List[Optional[bytes]]:
            sg = get_default_sg()
            metas = get_note_attachments(sg, note_id)
            out: List[Optional[bytes]] = []
            for m in metas:
                out.append(download_attachment_bytes(sg, m))
            return out

        def _on_done(result: object) -> None:
            if seq != self._notes_attach_seq:
                return
            if not isinstance(result, list):
                return
            valid: List[bytes] = [d for d in result if isinstance(d, bytes)]
            if not valid:
                return

            img_host = QWidget(fr)
            img_host.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Fixed,
            )
            img_row = QHBoxLayout(img_host)
            img_row.setContentsMargins(0, 4, 0, 0)
            img_row.setSpacing(6)
            clickables: List[ClickableImage] = []
            for data in valid:
                ci = ClickableImage(img_host)
                ci.set_image_bytes(data)
                clickables.append(ci)
                img_row.addWidget(ci)
            pms: List[QPixmap] = []
            for ci in clickables:
                op = ci.original_pixmap()
                if op is not None and not op.isNull():
                    pms.append(op)
            if len(pms) > 1 and len(pms) == len(clickables):
                for i, ci in enumerate(clickables):
                    ci.set_siblings(pms, i)
            fl.addWidget(img_host)

        w = ShotGridWorker(_fetch)
        w.finished.connect(_on_done)
        w.start()
        self._workers.append(w)

    def _on_notes_loaded(self, result: object, req: int) -> None:
        if req != self._notes_req_id:
            return
        self._clear_note_rows()
        rows = result if isinstance(result, list) else []
        if not rows:
            empty = QLabel("(이 샷에 연결된 노트가 없습니다)")
            empty.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
            self._notes_layout.insertWidget(0, empty)
            return
        self._notes_attach_seq += 1
        att_seq = self._notes_attach_seq
        for n in rows:
            fr = QFrame()
            fr.setObjectName("card")
            fl = QVBoxLayout(fr)
            fl.setContentsMargins(8, 8, 8, 8)
            subj = (n.get("subject") or "").strip()
            author = (n.get("author") or "").strip()
            ts = (n.get("timestamp") or "").strip()
            head = QLabel(f"{author} · {ts}" + (f" · {subj}" if subj else ""))
            head.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; border: none;")
            fl.addWidget(head)
            body = QLabel((n.get("content") or "").strip() or "—")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.setStyleSheet(f"color: {theme.TEXT}; border: none;")
            fl.addWidget(body)
            nid = n.get("note_id")
            if nid is not None:
                try:
                    self._load_feedback_note_attachments(int(nid), fr, fl, att_seq)
                except (TypeError, ValueError):
                    pass
            self._notes_layout.insertWidget(self._notes_layout.count() - 1, fr)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._projects_bootstrapped:
            self._projects_bootstrapped = True
            self._load_projects()
        QTimer.singleShot(0, self._sync_queue_panel_alignment)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            self._video.setFocus()
        self._sync_queue_panel_alignment()

    def _on_filter_group_id(self, btn_id: int) -> None:
        if btn_id == 0:
            self._set_filter(["sv", "tm"])
        elif btn_id == 1:
            self._set_filter(["sv"])
        elif btn_id == 2:
            self._set_filter(["tm"])
        self._apply_filt_btn_style()

    def _set_filter(self, statuses: List[str]) -> None:
        self._filter_statuses = [s.strip().lower() for s in statuses if s.strip()]
        self._reload_tasks()

    def _task_count_caption(self, n: int) -> str:
        fs = list(self._filter_statuses)
        if fs == ["sv", "tm"]:
            tag = "SV+TM"
        elif fs == ["sv"]:
            tag = "SV만"
        elif fs == ["tm"]:
            tag = "TM만"
        else:
            tag = "+".join(fs).upper() if fs else "—"
        return f"{n}개 샷 ({tag})"

    def _load_projects(self) -> None:
        self._proj_req_id += 1
        req = self._proj_req_id
        self._task_status_lbl.setText("프로젝트 로드 중…")

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_active_projects(sg)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req: self._on_projects_loaded(r, q))
        w.error.connect(
            lambda e, q=req: self._on_projects_load_error(e, q),
        )
        w.start()
        self._workers.append(w)

    def _on_projects_load_error(self, err: str, req: int) -> None:
        if req != self._proj_req_id:
            return
        self._task_status_lbl.setText(f"프로젝트 오류: {err}")

    def _on_projects_loaded(self, result: object, req: int) -> None:
        if req != self._proj_req_id:
            return
        self._projects = result if isinstance(result, list) else []
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        self._project_combo.addItem("프로젝트를 선택하세요", None)
        for p in self._projects:
            name = (p.get("name") or p.get("code") or "").strip()
            self._project_combo.addItem(name, p.get("id"))
        self._project_combo.setCurrentIndex(0)
        self._project_combo.blockSignals(False)
        self._reload_tasks()
        QTimer.singleShot(0, self._sync_queue_panel_alignment)

    def _on_project_changed(self, _idx: int = 0) -> None:
        self._reload_tasks()

    def _clear_per_frame_ann_state(self) -> None:
        self._ann_by_frame.clear()
        self._tracked_frame_idx = None

    def _feedback_is_dirty(self) -> bool:
        if self._comment.toPlainText().strip():
            return True
        if any(bool(v) for v in self._ann_by_frame.values()):
            return True
        if self._video.annotation_overlay.has_content():
            return True
        return False

    def _clear_feedback_draft(self) -> None:
        self._comment.clear()
        self._clear_per_frame_ann_state()
        self._video.annotation_overlay.clear_all()

    def _confirm_discard_feedback_on_task_change(self, new_task: Dict[str, Any]) -> bool:
        old = self._selected_task
        if (
            isinstance(old, dict)
            and old.get("task_id") is not None
            and old.get("task_id") == new_task.get("task_id")
        ):
            return True
        if not self._feedback_is_dirty():
            return True
        r = QMessageBox.question(
            self,
            "피드백 초기화",
            "작성 중인 코멘트 또는 그림이 있습니다. 다른 샷으로 이동하면 지워집니다.\n"
            "계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return False
        self._clear_feedback_draft()
        return True

    def _on_feedback_video_frame_changed(self, idx: int) -> None:
        if self._restoring_feedback_overlay:
            return
        if self._tracked_frame_idx == idx:
            return
        prev = self._tracked_frame_idx
        if prev is not None and prev != idx:
            snap = self._video.annotation_overlay.get_shapes_snapshot()
            if snap:
                self._ann_by_frame[prev] = snap
            else:
                self._ann_by_frame.pop(prev, None)
        self._restoring_feedback_overlay = True
        self._video.annotation_overlay.set_shapes_snapshot(
            self._ann_by_frame.get(idx),
            emit_changed=False,
        )
        self._restoring_feedback_overlay = False
        self._tracked_frame_idx = idx

    def _on_feedback_overlay_changed(self) -> None:
        if self._restoring_feedback_overlay:
            return
        idx = self._tracked_frame_idx
        if idx is None:
            idx = self._video.current_frame_index()
        snap = self._video.annotation_overlay.get_shapes_snapshot()
        if snap:
            self._ann_by_frame[idx] = snap
        else:
            self._ann_by_frame.pop(idx, None)

    def _sync_current_frame_ann_to_dict(self) -> None:
        idx = self._tracked_frame_idx
        if idx is None:
            idx = self._video.current_frame_index()
        snap = self._video.annotation_overlay.get_shapes_snapshot()
        if snap:
            self._ann_by_frame[idx] = snap
        else:
            self._ann_by_frame.pop(idx, None)

    @staticmethod
    def _unlink_note_tmp_paths(paths: Optional[List[str]]) -> None:
        if not paths:
            return
        for p in paths:
            if p and Path(p).is_file():
                Path(p).unlink(missing_ok=True)

    def _reload_tasks(self) -> None:
        pid = self._project_combo.currentData()
        if pid is None:
            self._task_status_lbl.setText("프로젝트를 선택하세요.")
            self._clear_cards()
            self._selected_task = None
            self._clear_per_frame_ann_state()
            self._video.set_feedback_project_selected(False)
            self._video.clear()
            return
        self._video.set_feedback_project_selected(True)
        self._task_status_lbl.setText("조회 중…")
        st = list(self._filter_statuses)
        self._list_req_id += 1
        req = self._list_req_id
        prev_sel_tid = self._selected_task.get("task_id") if self._selected_task else None

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_review_tasks_for_project(sg, int(pid), statuses=st)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req, prev=prev_sel_tid: self._on_tasks_loaded(r, q, prev))
        w.error.connect(lambda e, q=req: self._on_tasks_load_error(e, q))
        w.start()
        self._workers.append(w)

    def _on_tasks_load_error(self, err: str, req: int) -> None:
        if req != self._list_req_id:
            return
        self._task_status_lbl.setText(f"오류: {err}")

    def _on_tasks_loaded(self, result: object, req: int, prev_sel_tid: Any) -> None:
        if req != self._list_req_id:
            return
        tasks = result if isinstance(result, list) else []
        self._tasks = tasks
        self._task_status_lbl.setText(self._task_count_caption(len(tasks)))
        self._rebuild_cards()
        if tasks:
            self._schedule_card_title_local_enrichment(req)
        on_queue = self._right_stack.currentIndex() == 0
        if prev_sel_tid is not None:
            for c in self._shot_cards:
                td = getattr(c, "_task_data", None)
                if isinstance(td, dict) and td.get("task_id") == prev_sel_tid:
                    if on_queue:
                        if self._apply_card_task_selection(c):
                            self._refresh_header_labels()
                        return
                    self._select_shot_card(c)
                    return
            self._selected_task = None
            self._selected_version_id = None
            self._selected_version_code = ""
            self._clear_per_frame_ann_state()
            self._video.clear()
            for c in self._shot_cards:
                c.setStyleSheet("")
            return
        if self._shot_cards:
            self._open_first_shot_queue_view(self._shot_cards[0])
            return
        self._selected_task = None
        self._selected_version_id = None
        self._selected_version_code = ""
        self._clear_per_frame_ann_state()
        self._video.clear()

    def _clear_cards(self) -> None:
        for c in self._shot_cards:
            self._card_layout.removeWidget(c)
            c.deleteLater()
        self._shot_cards.clear()

    def _rebuild_cards(self) -> None:
        self._clear_cards()
        for t in self._tasks:
            card = self._make_shot_card(t)
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)
            self._shot_cards.append(card)
            self._load_thumb_for_task(t, card)

    def _schedule_card_title_local_enrichment(self, list_req: int) -> None:
        """SG에 경로가 없는 샷도 로컬 comp MOV 파일명으로 카드 제목을 맞춘다 (백그라운드)."""
        tasks_copy = [dict(t) for t in self._tasks]

        def _work() -> List[Tuple[int, str]]:
            out: List[Tuple[int, str]] = []
            env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
            for task in tasks_copy:
                raw_tid = task.get("task_id")
                if raw_tid is None:
                    continue
                try:
                    tid = int(raw_tid)
                except (TypeError, ValueError):
                    continue
                shot = (task.get("shot_code") or "").strip()
                proj = _effective_project_for_paths(task)
                if not shot or not proj:
                    continue
                server_root = find_server_root_auto(proj) or env_root
                if not server_root:
                    continue
                sg_path = (task.get("latest_version_sg_path") or "").strip()
                ver_code = (task.get("latest_version_code") or "").strip() or None
                mov, _tried, _warn = resolve_local_comp_mov_for_feedback(
                    shot,
                    proj,
                    server_root,
                    sg_movie_raw=sg_path,
                    version_code=ver_code,
                )
                if mov is not None and mov.is_file():
                    out.append((tid, mov.name))
            return out

        w = ShotGridWorker(_work)
        w.finished.connect(lambda rows, q=list_req: self._apply_card_title_enrichment(rows, q))
        w.error.connect(lambda _e: None)
        w.start()
        self._workers.append(w)

    def _apply_card_title_enrichment(self, rows: object, list_req: int) -> None:
        if list_req != self._list_req_id:
            return
        if not isinstance(rows, list):
            return
        by_tid: Dict[int, QFrame] = {}
        for c in self._shot_cards:
            td = getattr(c, "_task_data", None)
            if not isinstance(td, dict):
                continue
            raw = td.get("task_id")
            if raw is None:
                continue
            try:
                by_tid[int(raw)] = c
            except (TypeError, ValueError):
                continue
        for item in rows:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            tid_v, name = item[0], item[1]
            try:
                tid = int(tid_v)
            except (TypeError, ValueError):
                continue
            if not isinstance(name, str) or not name.strip():
                continue
            card = by_tid.get(tid)
            if card is None:
                continue
            lbl = getattr(card, "_shot_title_lbl", None)
            if lbl is not None:
                lbl.setText(name.strip())

    def _open_feedback_render_folder(self, task: Dict[str, Any]) -> None:
        """샷 comp 렌더 폴더(기존 nk_finder 규칙)를 탐색기로 연다."""
        shot = (task.get("shot_code") or "").strip()
        proj = _effective_project_for_paths(task)
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = (find_server_root_auto(proj) or env_root).strip()
        if not shot or not server_root:
            QMessageBox.information(
                self,
                "폴더 열기",
                "서버 루트 또는 샷 정보를 찾을 수 없습니다.",
            )
            return
        target = resolve_comp_renders_dir(shot, proj, server_root)
        if target is None:
            QMessageBox.information(
                self,
                "폴더 열기",
                "렌더 폴더를 찾을 수 없습니다.\n"
                "샷 폴더 또는 comp/devl/renders 등 경로가 없을 수 있습니다.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(normalize_path_str(str(target))))

    def _make_shot_card(self, task: Dict[str, Any]) -> QFrame:
        fr = QFrame()
        fr.setObjectName("card")
        fr.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(fr)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        thumb.setText("—")
        thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        primary_title = _shot_card_primary_title(task)
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        shot_lbl = QLabel(primary_title)
        shot_lbl.setStyleSheet(
            f"font-weight: bold; color: {theme.ACCENT}; font-size: 12px; border: none;"
        )
        shot_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        sg_open_btn = QPushButton()
        setup_shotgrid_open_shot_button(sg_open_btn, task.get("shot_id"))
        copy_btn = QPushButton()
        setup_copy_shot_name_button(copy_btn, (task.get("shot_code") or "").strip() or None)
        filt_h = max(28, self._btn_tm.sizeHint().height())
        folder_btn = QPushButton("폴더열기")
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.setStyleSheet(_feedback_filt_chip_unselected_style())
        folder_btn.setFixedHeight(filt_h)
        folder_btn.setToolTip("이 샷 comp 렌더 폴더를 탐색기로 엽니다")
        folder_btn.clicked.connect(lambda _c=False, td=task: self._open_feedback_render_folder(td))
        title_row.addWidget(shot_lbl, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(sg_open_btn, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addStretch(1)
        title_row.addWidget(folder_btn, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(title_row)

        uploader_lbl = QLabel(_feedback_task_uploader_line(task))
        uploader_lbl.setStyleSheet(
            f"font-weight: bold; color: {theme.TEXT}; font-size: 12px; border: none;"
        )
        uploader_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        col.addWidget(uploader_lbl)

        st_row = QHBoxLayout()
        st_lbl = QLabel("상태:")
        st_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        st_row.addWidget(st_lbl)
        combo = NoScrollComboBox()
        for scode, lbl in BELUCA_TASK_STATUS_PRESETS:
            combo.addItem(f"{scode} — {lbl}", scode)
        cur = (task.get("task_status") or "").strip().lower()
        idx = 0
        for i in range(combo.count()):
            if str(combo.itemData(i)).lower() == cur:
                idx = i
                break
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        bg, fg = theme.task_status_badge_colors(cur)
        combo.setStyleSheet(
            f"QComboBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 2px 8px; }}"
            f"QComboBox:hover {{ border-color: {theme.BORDER_FOCUS}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{"
            f"background-color: {theme.PANEL_BG}; color: {theme.TEXT}; "
            f"selection-background-color: {theme.ACCENT}; selection-color: #ffffff; }}"
        )
        combo.currentIndexChanged.connect(
            lambda _i, td=task, c=combo: self._on_task_status_combo(td, c)
        )
        st_row.addWidget(combo, 1)
        col.addLayout(st_row)
        lay.addLayout(col, 1)

        fr._thumb_lbl = thumb  # type: ignore[attr-defined]
        fr._shot_title_lbl = shot_lbl  # type: ignore[attr-defined]
        fr._task_data = task  # type: ignore[attr-defined]
        fr._status_combo = combo  # type: ignore[attr-defined]

        def _press(e: QMouseEvent) -> None:
            if e.button() == Qt.MouseButton.LeftButton:
                self._select_shot_card(fr)
            else:
                QFrame.mousePressEvent(fr, e)

        fr.mousePressEvent = _press  # type: ignore[method-assign]

        return fr

    def _set_combo_index_for_status(self, combo: QComboBox, ns: str) -> None:
        ns_l = (ns or "").strip().lower()
        combo.blockSignals(True)
        for i in range(combo.count()):
            if str(combo.itemData(i) or "").strip().lower() == ns_l:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)
        self._apply_combo_status_colors(combo, ns_l)

    def _mirror_task_status_combos(
        self, task: Dict[str, Any], exclude_combo: Optional[QComboBox] = None
    ) -> None:
        tid = task.get("task_id")
        if tid is None:
            return
        ns = (task.get("task_status") or "").strip().lower()
        for c in self._shot_cards:
            td = getattr(c, "_task_data", None)
            if not isinstance(td, dict) or td.get("task_id") != tid:
                continue
            oc = getattr(c, "_status_combo", None)
            if oc is None or oc is exclude_combo:
                continue
            self._set_combo_index_for_status(oc, ns)
        st = self._selected_task
        if (
            isinstance(st, dict)
            and st.get("task_id") == tid
            and self._notes_status_combo is not exclude_combo
        ):
            self._set_combo_index_for_status(self._notes_status_combo, ns)

    def _on_task_status_combo(self, task: Dict[str, Any], combo: QComboBox) -> None:
        code = combo.currentData()
        if not code:
            return
        if task.get("task_id") is None:
            return
        prev_code = (task.get("task_status") or "").strip().lower()
        new_st = str(code).strip().lower()
        if new_st == prev_code:
            return
        task["task_status"] = new_st
        self._apply_combo_status_colors(combo, new_st)
        self._mirror_task_status_combos(task, exclude_combo=combo)

    def _apply_combo_status_colors(self, combo: QComboBox, status: object) -> None:
        ns = str(status).strip().lower() if status else ""
        bg, fg = theme.task_status_badge_colors(ns)
        combo.setStyleSheet(
            f"QComboBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 2px 8px; }}"
            f"QComboBox:hover {{ border-color: {theme.BORDER_FOCUS}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{"
            f"background-color: {theme.PANEL_BG}; color: {theme.TEXT}; "
            f"selection-background-color: {theme.ACCENT}; selection-color: #ffffff; }}"
        )

    def _after_status_update(self, task: Dict[str, Any], new_status: object) -> None:
        ns = str(new_status).strip().lower() if new_status else ""
        task["task_status"] = ns
        allowed: Set[str] = set(self._filter_statuses)
        if ns not in allowed:
            self._reload_tasks()

    def _load_thumb_for_task(self, task: Dict[str, Any], card: QFrame) -> None:
        url = task.get("shot_image")
        lbl = getattr(card, "_thumb_lbl", None)
        tid = task.get("task_id")
        if not url or not isinstance(url, str) or lbl is None or tid is None:
            return
        self._thumb_token[tid] = self._thumb_token.get(tid, 0) + 1
        tok = self._thumb_token[tid]

        def _dl() -> Optional[bytes]:
            import urllib.request

            try:
                with urllib.request.urlopen(url, timeout=12) as resp:
                    return resp.read()
            except Exception:
                return None

        w = ShotGridWorker(_dl)

        def _done(data: object, t=tid, tk=tok, ref=lbl) -> None:
            if self._thumb_token.get(t) != tk:
                return
            self._apply_thumb(ref, data)

        w.finished.connect(_done)
        w.start()
        self._workers.append(w)

    def _apply_thumb(self, lbl: QLabel, data: object) -> None:
        if not data or not isinstance(data, bytes):
            return
        pm = QPixmap()
        if pm.loadFromData(data):
            scaled = pm.scaled(
                _THUMB_W,
                _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (scaled.width() - _THUMB_W) // 2)
            y = max(0, (scaled.height() - _THUMB_H) // 2)
            lbl.setPixmap(scaled.copy(QRect(x, y, _THUMB_W, _THUMB_H)))
            lbl.setText("")

    def _sync_shot_card_primary_titles(self) -> None:
        for c in self._shot_cards:
            lbl = getattr(c, "_shot_title_lbl", None)
            task = getattr(c, "_task_data", None)
            if lbl is None or not isinstance(task, dict):
                continue
            lbl.setText(_shot_card_primary_title(task))
            lbl.setStyleSheet(
                f"font-weight: bold; color: {theme.ACCENT}; font-size: 12px; border: none;"
            )

    def _apply_mov_name_to_selected_shot_card(self, mov_path: str) -> None:
        task = self._selected_task
        if not isinstance(task, dict):
            return
        tid = task.get("task_id")
        for c in self._shot_cards:
            td = getattr(c, "_task_data", None)
            lbl = getattr(c, "_shot_title_lbl", None)
            if lbl is None or not isinstance(td, dict):
                continue
            if td.get("task_id") != tid:
                continue
            lbl.setText(Path(mov_path).name)
            lbl.setStyleSheet(
                f"font-weight: bold; color: {theme.ACCENT}; font-size: 12px; border: none;"
            )
            return

    def _apply_card_task_selection(self, card: QFrame) -> bool:
        task = getattr(card, "_task_data", None)
        if not isinstance(task, dict):
            return False
        self._selected_task = task
        self._selected_version_code = (task.get("latest_version_code") or "").strip()
        lvid = task.get("latest_version_id")
        try:
            vi = int(lvid) if lvid is not None else 0
        except (TypeError, ValueError):
            vi = 0
        self._selected_version_id = vi if vi > 0 else None
        for c in self._shot_cards:
            c.setStyleSheet("")
        card.setStyleSheet(f"QFrame#card {{ border: 2px solid {theme.ACCENT}; }}")
        return True

    def _open_first_shot_queue_view(self, card: QFrame) -> None:
        """프로젝트 조회 직후: 첫 샷 영상 + 오른쪽 샷 목록(노트 탭으로 전환하지 않음)."""
        task = getattr(card, "_task_data", None)
        if not isinstance(task, dict):
            return
        if not self._confirm_discard_feedback_on_task_change(task):
            return
        if not self._apply_card_task_selection(card):
            return
        self._refresh_header_labels()
        self._right_stack.setCurrentIndex(0)
        self._load_mov_for_selection()

    def _select_shot_card(self, card: QFrame) -> None:
        task = getattr(card, "_task_data", None)
        if not isinstance(task, dict):
            return
        if not self._confirm_discard_feedback_on_task_change(task):
            return
        if not self._apply_card_task_selection(card):
            return
        task = self._selected_task
        if not isinstance(task, dict):
            return

        shot = (task.get("shot_code") or "").strip()
        ver = (self._selected_version_code or "").strip()
        self._notes_title_lbl.setText(f"{shot} · {ver}" if ver else shot or "—")
        self._refresh_header_labels()
        self._sync_notes_status_combo()
        self._load_notes_for_shot()
        self._right_stack.setCurrentIndex(1)

        self._load_mov_for_selection()

    def _server_root_for_task(self, task: Dict[str, Any]) -> str:
        proj = _effective_project_for_paths(task)
        fb = (os.environ.get("BPE_FEEDBACK_SERVER_ROOT") or "").strip()
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        if fb:
            return normalize_path_str(fb).strip()
        auto = find_server_root_auto(proj)
        if auto:
            return normalize_path_str(str(auto)).strip()
        if env_root:
            return normalize_path_str(env_root).strip()
        return ""

    def _load_mov_for_selection(self) -> None:
        task = self._selected_task
        if not task:
            self._clear_per_frame_ann_state()
            self._video.clear()
            return
        shot = (task.get("shot_code") or "").strip()
        proj = _effective_project_for_paths(task)
        root = self._server_root_for_task(task)
        self._video.annotation_overlay.set_tool(AnnotationTool.NONE)
        self._sync_ann_tool_buttons()

        if not shot or not proj:
            self._clear_per_frame_ann_state()
            self._video.clear()
            return

        if not root:
            self._clear_per_frame_ann_state()
            self._video.clear()
            QMessageBox.warning(
                self,
                "서버 루트 없음",
                "프로젝트 서버 경로를 찾지 못했습니다.\n"
                "• 환경 변수 BPE_FEEDBACK_SERVER_ROOT 또는 BPE_SERVER_ROOT 를 설정하거나\n"
                "• 드라이브에 vfx/project_연도/<프로젝트코드> 구조가 있는지 확인하세요.",
            )
            return

        vc = (self._selected_version_code or "").strip() or None
        self._video_req_id += 1
        vid = self._video_req_id
        self._clear_per_frame_ann_state()
        self._video.clear()
        self._current_mov_path = ""
        self._sync_shot_card_primary_titles()

        snap = dict(task)

        def _work() -> Tuple[Optional[str], List[str], Optional[str]]:
            mov, tried, warn = resolve_local_comp_mov_for_feedback(
                snap.get("shot_code") or "",
                _effective_project_for_paths(snap),
                root,
                sg_movie_raw=snap.get("latest_version_sg_path") or "",
                version_code=vc,
            )
            if mov is None:
                return None, tried, None
            return normalize_path_str(str(mov)), tried, warn

        w = ShotGridWorker(_work)

        def _done(result: object) -> None:
            if vid != self._video_req_id:
                return
            if not isinstance(result, tuple) or len(result) != 3 or not isinstance(result[1], list):
                self._clear_per_frame_ann_state()
                self._video.clear()
                return
            path_str: Optional[str] = result[0]  # type: ignore[assignment]
            tried_lines: List[str] = result[1]  # type: ignore[assignment]
            warn_msg: Optional[str] = result[2]  # type: ignore[assignment]
            if not path_str:
                self._clear_per_frame_ann_state()
                self._video.clear()
                detail = "\n".join(tried_lines) if tried_lines else "(진단 정보 없음)"
                QMessageBox.information(
                    self,
                    "영상 파일 없음",
                    "다음을 확인하세요.\n"
                    "• ShotGrid Version에 디스크 경로(sg_path_to_movie)가 있는지\n"
                    "• 샷 폴더 아래 comp/devl/renders, comp/renders 등에 "
                    ".mov / .mp4 / .mxf 파일이 있는지\n"
                    "• 파일 이름에 버전 코드가 포함되는지\n\n"
                    f"진단:\n{detail}",
                )
                return
            ok = self._video.load_mov(path_str)
            self._video.set_feedback_frame_start(get_feedback_frame_start())
            self._current_mov_path = path_str
            self._apply_mov_name_to_selected_shot_card(path_str)
            self._video.set_clip_footer_text(Path(path_str).name)
            self._refresh_header_labels(path_str)
            if warn_msg and ok:
                logger.info("Feedback: %s", warn_msg)
            if not ok:
                QMessageBox.warning(
                    self,
                    "재생 실패",
                    "파일을 읽지 못했거나 FFmpeg로 디코딩하지 못했습니다.\n"
                    "(Windows 최신 빌드에는 FFmpeg가 포함됩니다.)\n"
                    f"파일: {path_str}",
                )
            self._video.setFocus()
            if ok:
                self._tracked_frame_idx = self._video.current_frame_index()

        w.finished.connect(_done)
        w.error.connect(
            lambda e, v=vid: self._on_video_resolve_error(e, v),
        )
        w.start()
        self._workers.append(w)

    def _on_video_resolve_error(self, msg: str, req: int) -> None:
        if req != self._video_req_id:
            return
        self._clear_per_frame_ann_state()
        self._video.clear()
        self._current_mov_path = ""
        self._sync_shot_card_primary_titles()
        QMessageBox.warning(self, "영상 경로", str(msg))

    def _submit_note(self) -> None:
        if self._submit_busy:
            return
        task = self._selected_task
        if not task:
            QMessageBox.warning(self, "제출", "샷을 먼저 선택하세요.")
            return
        self._sync_current_frame_ann_to_dict()
        text = self._comment.toPlainText().strip()
        frame_idxs = sorted(i for i, sh in self._ann_by_frame.items() if sh)
        has_drawings = bool(frame_idxs)
        if not text and not has_drawings:
            QMessageBox.warning(self, "제출", "코멘트 또는 그림 중 하나는 필요합니다.")
            return
        pid = task.get("project_id")
        sid = task.get("shot_id")
        if pid is None or sid is None:
            QMessageBox.warning(self, "제출", "프로젝트/샷 정보가 없습니다.")
            return

        shot_code = (task.get("shot_code") or "").strip()
        ver_for_subject = (self._selected_version_code or "").strip()
        vid = self._selected_version_id

        tmp_paths: List[str] = []
        frame_start = get_feedback_frame_start()
        safe_shot = _sanitize_feedback_filename_part(shot_code)

        if has_drawings:
            self._submit_busy = True
            self._submit_btn.setEnabled(False)
            self._submit_btn.setText("캡처 중…")
            self._submit_btn.set_fill_ratio(0.03)
            n_frames = max(len(frame_idxs), 1)
            for i, fi in enumerate(frame_idxs):
                self._restoring_feedback_overlay = True
                self._video.annotation_overlay.set_shapes_snapshot(
                    self._ann_by_frame.get(fi),
                    emit_changed=False,
                )
                self._restoring_feedback_overlay = False
                disp = frame_start + int(fi)
                png_bytes = self._video.capture_annotated_png_bytes(
                    burn_in_text=f"프레임 {disp}",
                    frame_index=int(fi),
                )
                if not png_bytes:
                    self._unlink_note_tmp_paths(tmp_paths)
                    self._submit_busy = False
                    self._restore_submit_ui_after_note()
                    QMessageBox.warning(
                        self,
                        "제출",
                        "그림을 PNG로 만들지 못했습니다.\n"
                        "FFmpeg가 있고 영상 경로가 접근 가능한지 확인하세요.",
                    )
                    return
                png_bytes = _png_bytes_for_shotgrid_upload(png_bytes)
                prefix = f"bpe_fb_{safe_shot}_{disp}_"
                fd, tmp_p = tempfile.mkstemp(suffix=".png", prefix=prefix)
                os.close(fd)
                try:
                    Path(tmp_p).write_bytes(png_bytes)
                except OSError as exc:
                    Path(tmp_p).unlink(missing_ok=True)
                    self._unlink_note_tmp_paths(tmp_paths)
                    self._submit_busy = False
                    self._restore_submit_ui_after_note()
                    QMessageBox.warning(self, "제출", f"임시 이미지 저장 실패: {exc}")
                    return
                tmp_paths.append(tmp_p)
                self._submit_btn.set_fill_ratio((i + 1) / float(n_frames) * 0.52)

        att_list: Optional[List[str]] = tmp_paths if tmp_paths else None
        append_feedback_log_verbose(
            "note_submit_start",
            task_id=task.get("task_id"),
            project_id=int(pid),
            shot_id=int(sid),
            has_png=bool(att_list),
            png_count=len(tmp_paths),
            text_len=len(text),
            version_id=int(vid) if vid is not None else 0,
        )
        self._submit_btn.setText("제출 중…")
        self._submit_busy = True
        self._submit_btn.setEnabled(False)
        if has_drawings:
            self._submit_btn.set_fill_ratio(max(self._submit_btn.fill_ratio(), 0.52))
        else:
            self._submit_btn.set_fill_ratio(0.14)
        self._start_submit_progress_animation()

        def _do() -> CreateNoteResult:
            base_sg = get_default_sg()
            me = guess_human_user_for_me(base_sg)
            author_name = ""
            if me:
                author_name = (me.get("name") or me.get("login") or "").strip()
            subject = build_native_style_note_subject(
                author_name,
                ver_for_subject or None,
                shot_code,
            )
            env_login = (os.environ.get("BPE_FEEDBACK_NOTE_SUDO_LOGIN") or "").strip()
            sudo_login = env_login
            if not sudo_login and me and me.get("id") is not None:
                try:
                    sudo_login = (resolve_sudo_login(base_sg, int(me["id"])) or "").strip()
                except Exception:
                    sudo_login = ""
                if not sudo_login:
                    sudo_login = (me.get("login") or "").strip()

            sg = get_shotgun_for_version_mutation(sudo_login) if sudo_login else base_sg
            addr = note_addressings_from_assignees(task.get("task_assignees"))
            res = create_note_with_result(
                sg,
                project_id=int(pid),
                shot_id=int(sid),
                subject=subject,
                content=text or "(이미지 피드백)",
                version_id=vid,
                attachment_path=None,
                attachment_paths=att_list,
                author_user=me,
                addressings_to=addr if addr else None,
            )
            note_row = res.note if isinstance(res.note, dict) else {}
            append_feedback_log_verbose(
                "note_submit_worker_result",
                note_id=note_row.get("id"),
                attachment_requested=res.attachment_requested,
                attachment_ok=res.attachment_ok,
                attachment_err_len=len((res.attachment_error or "")),
            )
            if note_row.get("id") is not None:
                tid = task.get("task_id")
                code = (task.get("task_status") or "").strip()
                if tid is not None and code:
                    sfn = (task.get("status_field") or "sg_status_list").strip()
                    update_task_status(sg, int(tid), code, field_name=sfn or None)
            return res

        w = ShotGridWorker(_do)
        w.finished.connect(lambda r: self._on_note_submitted(r, tmp_paths))
        w.error.connect(lambda e: self._on_note_failed(e, tmp_paths))
        w.start()
        self._workers.append(w)

    def _on_note_submitted(self, result: object, tmp_paths: Optional[List[str]]) -> None:
        append_feedback_log_verbose(
            "note_submit_ui_done",
            ok_type=type(result).__name__,
            is_create_note_result=isinstance(result, CreateNoteResult),
        )
        self._submit_busy = False
        self._restore_submit_ui_after_note()
        self._unlink_note_tmp_paths(tmp_paths)
        self._comment.clear()
        self._clear_per_frame_ann_state()
        self._video.annotation_overlay.clear_all()
        self._load_notes_for_shot()
        if not isinstance(result, CreateNoteResult):
            QMessageBox.warning(self, "제출", "응답 형식 오류")
            return
        st = self._selected_task
        if isinstance(st, dict) and st.get("task_id") is not None:
            self._after_status_update(st, st.get("task_status"))
        if result.attachment_requested and not result.attachment_ok:
            QMessageBox.warning(
                self,
                "부분 완료",
                "노트는 ShotGrid에 등록되었으나 이미지 첨부에 실패했습니다.\n"
                f"{result.attachment_error or ''}",
            )
            return
        QMessageBox.information(self, "완료", "ShotGrid에 노트가 등록되었습니다.")

    def _on_note_failed(self, msg: str, tmp_paths: Optional[List[str]]) -> None:
        append_feedback_log_verbose("note_submit_ui_error", msg_len=len(msg))
        self._submit_busy = False
        self._restore_submit_ui_after_note()
        self._unlink_note_tmp_paths(tmp_paths)
        QMessageBox.warning(self, "제출 실패", msg)
