"""BPE 컨펌 전용 창 — 누크 없이 쓰는 뷰어 + 그림 메모 + 작업 비하인드.

기존 피드백 탭과 따로 뜨는 독립 창이다. 영상을 프레임 단위로 메모리에 올려 재생하고,
원본·전 버전·지금 버전·편집본을 번호 키로 번갈아 본다. 모양은 ``style.py``(시안 2판).
"""

from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import time
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QImage,
    QKeyEvent,
    QPainter,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import bpe.core.config as cfg
from bpe.core.atomic_io import read_json_file, write_json_file
from bpe.core.confirm_annotations import AnnotationDoc
from bpe.core.confirm_checks import (
    STATE_FAIL,
    STATE_PASS,
    CheckResult,
    basis_text,
    check_work_against_reference,
    failure_lines,
    has_failure,
)
from bpe.core.confirm_decode import fit_decode_size, frame_byte_size
from bpe.core.confirm_media import find_shot_media, parse_version, quick_version_movie
from bpe.core.confirm_probe import VideoInfo, codec_label, probe_video
from bpe.core.confirm_standard import (
    ProjectStandard,
    load_standard,
    pick_preset,
    preset_names_for,
    read_presets,
)
from bpe.core.confirm_view_math import (
    CHANNEL_B,
    CHANNEL_G,
    CHANNEL_LUMA,
    CHANNEL_R,
    CHANNEL_RGB,
    VIEW_MODE_A,
    VIEW_MODE_DIFF,
)
from bpe.core.logging import get_logger
from bpe.core.lut_cube import CubeLut, load_cube
from bpe.core.mov_colorspace import DISPLAY_NAME, inspect_mov_color
from bpe.core.settings import (
    get_confirm_settings,
    get_feedback_frame_start,
    save_confirm_settings,
)
from bpe.gui.confirm import status_style, style
from bpe.gui.confirm.annotation_layer import (
    TOOL_ARROW,
    TOOL_ELLIPSE,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_SELECT,
    TOOL_TEXT,
    AnnotationLayer,
    paint_shapes,
)
from bpe.gui.confirm.parts import Grip, KeyButton
from bpe.gui.confirm.shot_drawer import ShotDrawer
from bpe.gui.confirm.side_panel import ConfirmSidePanel
from bpe.gui.confirm.timeline import ConfirmTimeline
from bpe.gui.confirm.viewer_gl import SLOT_A, SLOT_B, ConfirmGLView
from bpe.gui.workers.confirm_stream_worker import StreamDecodeWorker
from bpe.gui.workers.sg_worker import ShotGridWorker

logger = get_logger("gui.confirm.window")

KEY_ORG, KEY_PREV, KEY_CUR, KEY_EDIT = "org", "prev", "cur", "edit"
_BUFFER_DEFS: Tuple[Tuple[str, int, str], ...] = (
    (KEY_ORG, 1, "ORG plate"),
    (KEY_PREV, 2, "이전버전"),
    (KEY_CUR, 3, "현재버전"),
    (KEY_EDIT, 4, "edit"),
)
_DECODE_ORDER = (KEY_CUR, KEY_PREV, KEY_ORG, KEY_EDIT)
_SEGMENT_POS = {KEY_ORG: "first", KEY_PREV: "mid", KEY_CUR: "mid", KEY_EDIT: "last"}
_MAX_W, _MAX_H = 2048, 1556
_ONDEMAND_KEEP = 12
_GAIN_STEPS_PER_STOP = 4
_GAIN_STOPS = 5
_GAMMA_STEPS = 100  # 막대 한쪽 끝까지의 칸 수
_GAMMA_SPAN = 4.0  # 막대 끝의 감마 배수(1/4 ~ 4)
_SEND_DELAY_SECS = 5
_NOTE_IMAGE_MAX_EDGE = 1280
_WORKER_WAIT_MS = 5000
_HEADER_H = 36
_HINT_W = 184
_SCRUB_MIN_PX, _SCRUB_MAX_PX = 4.0, 16.0
_PIXEL_GAP = "&nbsp;&nbsp;&nbsp;"
_VIDEO_FILTER = "영상 (*.mov *.mp4 *.mxf *.mkv *.m4v);;모든 파일 (*)"
_CHANNELS: Tuple[Tuple[str, str], ...] = (
    ("RGB", CHANNEL_RGB),
    ("R", CHANNEL_R),
    ("G", CHANNEL_G),
    ("B", CHANNEL_B),
    ("A", CHANNEL_LUMA),
)
_CHANNEL_NAMES = {CHANNEL_R: "R", CHANNEL_G: "G", CHANNEL_B: "B", CHANNEL_LUMA: "밝기(A)"}
_TOOLS: Tuple[Tuple[str, str, str, str], ...] = (
    (TOOL_SELECT, "select", "선택", "V"),
    (TOOL_RECT, "rect", "네모", "N"),
    (TOOL_ELLIPSE, "ellipse", "원", "O"),
    (TOOL_PEN, "pen", "펜", "P"),
    (TOOL_ARROW, "arrow", "화살표", "W"),
    (TOOL_TEXT, "text", "글씨", "T"),
)
_SHORTCUTS: Tuple[Tuple[str, Tuple[Tuple[Tuple[str, ...], str], ...]], ...] = (
    (
        "보기",
        (
            (("1", "2", "3", "4"), "ORG plate / 이전버전 / 현재버전 / edit"),
            (("D",), "Difference (지금 보는 판 − 직전에 본 판)"),
            (("R", "G", "B", "A"), "채널 / 밝기만 — 한 번 더 누르면 RGB"),
            (("L",), "룩업 켜고 끄기"),
            (("F", "H"), "Fit / Fill"),
            (("휠", "Ctrl+끌기"), "확대"),
            (("Alt+끌기",), "화면 이동"),
        ),
    ),
    (
        "재생",
        (
            (("Space",), "재생 · 멈춤"),
            (("←", "→"), "한 프레임 앞 / 뒤"),
            (("영상 끌기",), "좌우로 끌어 프레임 넘기기 (선택 도구일 때)"),
            (("Home", "End"), "처음 / 끝 프레임"),
        ),
    ),
    (
        "그리기",
        (
            (("V", "N", "O", "P", "W", "T"), "선택 / 네모 / 원 / 펜 / 화살표 / 글씨"),
            (("Ctrl+Z", "Ctrl+Y"), "되돌리기 / 다시"),
            (("Delete",), "고른 그림 지우기"),
        ),
    ),
    (
        "창",
        (
            (("F11",), "Fullscreen (영상만 크게)"),
            (("Esc",), "닫기 · 취소"),
            (("?",), "이 표"),
        ),
    ),
)
_TOOL_HINTS = {
    TOOL_SELECT: "선택 · 옮기기",
    TOOL_RECT: "끌어서 네모 → 글 쓰고 Enter",
    TOOL_ELLIPSE: "끌어서 원 → 글 쓰고 Enter",
    TOOL_PEN: "펜 · 자유롭게 그리기",
    TOOL_ARROW: "끌어서 화살표 → 글 쓰고 Enter",
    TOOL_TEXT: "눌러서 글씨 쓰기",
}


class _Buffer:
    """번호 키 하나에 올라온 영상 한 판."""

    def __init__(self, key: str, number: int, title: str) -> None:
        self.key, self.number, self.title = key, number, title
        self.path: Optional[Path] = None
        self.info: Optional[VideoInfo] = None
        self.size: Tuple[int, int] = (0, 0)
        self.frames: Dict[int, Any] = {}
        self.full = False
        self.lut_baked = False
        self.version_label = ""
        self.error = ""

    @property
    def available(self) -> bool:
        return self.path is not None and self.info is not None and self.size[0] > 0

    def frame_count(self) -> int:
        return (self.info.frame_count or 0) if self.info else 0

    def button_label(self) -> str:
        return self.title if self.available else f"{self.title} 없음"

    def tip(self) -> str:
        """버튼에 마우스를 올리면 보이는 글 — 어느 파일(버전)인지."""
        name = self.path.name if self.path is not None else "파일 없음"
        return f"숫자 키 {self.number} · {name}"


def _btn(text: str = "", *, checkable: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def _icon_btn(icon: str, tip: str, *, checkable: bool = False, size: int = 16) -> QPushButton:
    b = _btn("", checkable=checkable, tip=tip)
    style.set_icon(b, icon, size=size)
    b.setStyleSheet(style.fixed_width_style(30))
    return b


def _divider() -> QWidget:
    w = QWidget()
    w.setFixedSize(1, 18)
    w.setStyleSheet(f"background: {style.EDGE};")
    return w


def _dim_label(text: str, *, mono: bool = False) -> QLabel:
    lbl = QLabel(text)
    extra = style.mono() if mono else ""
    lbl.setStyleSheet(f"color: {style.DIM}; {extra}")
    return lbl


def _bar_frame(name: str, bg: str, *, top: bool = False, bottom: bool = True) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"QFrame#{name} {{ {style.bar_style(bg, bottom=bottom, top=top)} }}")
    return f


class ConfirmWindow(QWidget):
    """컨펌 전용 창."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BPE 컨펌")
        self.resize(1680, 980)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._closed = False
        self._aumid_applied = False
        self._workers: List[Any] = []
        self._decoders: List[StreamDecodeWorker] = []
        self._decode_queue: List[str] = []
        self._decoding: Optional[StreamDecodeWorker] = None
        self._ondemand_pending: Dict[Tuple[str, int], StreamDecodeWorker] = {}
        self._bufs: Dict[str, _Buffer] = {k: _Buffer(k, n, t) for k, n, t in _BUFFER_DEFS}
        self._shown = KEY_CUR
        self._last_shown = KEY_ORG
        self._diff = False
        self._diff_note = ""
        self._channel = CHANNEL_RGB
        self._lut: Optional[CubeLut] = None
        self._lut_on = False
        self._lut_path = ""
        self._index = 0
        self._count = 0
        self._fps = 24.0
        self._frame_start = get_feedback_frame_start()
        self._playing = False
        self._loop = True
        self._movie = ""
        self._shot_root: Optional[Path] = None
        self._task: Dict[str, Any] = {}
        self._checks: List[CheckResult] = []
        self._load_token = 0
        self._hover: Tuple[int, int] = (-1, -1)
        self._color = style.DRAW_COLORS[0]
        self._recent_colors: List[str] = list(style.DRAW_COLORS)  # 띠에 보이는 세 색
        self._pending_status = ""
        self._pending_left = 0
        self._sent_note_id: Optional[int] = None
        self._last_status_code = ""
        self._submit_busy = False
        self._version_note = ""
        self._open_started = 0.0
        self._memo_lines: Dict[int, str] = {}  # 도형 id → 메모 칸에 적어 둔 그 도형의 글
        self._scrub_from = 0
        self._standard: Optional[ProjectStandard] = None
        self._preset_names: List[str] = []
        self._preset_why = ""
        self._status_styles_asked = False
        self._basis = ""
        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._send_timer = QTimer(self)
        self._send_timer.setInterval(1000)
        self._send_timer.timeout.connect(self._on_send_tick)
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(800)
        self._draft_timer.timeout.connect(self._save_draft)
        self._build_ui()
        self._sync_all()

    # ── 화면 구성 ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        style.apply_root(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._header_bar = self._build_header()
        root.addWidget(self._header_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        self._view_bar = self._build_bar()
        left.addWidget(self._view_bar)

        self._view = ConfirmGLView()
        self._view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._view.hover_pixel.connect(self._on_hover)
        self._layer = AnnotationLayer(self._view)
        self._layer.doc_changed.connect(self._on_doc_changed)
        self._build_overlays()
        left.addWidget(self._view, 1)

        self._info = QLabel("")
        self._info.setTextFormat(Qt.TextFormat.RichText)
        self._info.setStyleSheet(
            f"background: {style.INFO_BG}; color: {style.DIM}; padding: 4px 10px; "
            f"border-top: 1px solid {style.EDGE}; {style.mono(style.FONT_SMALL_PX)}"
        )
        left.addWidget(self._info)

        self._timeline = ConfirmTimeline()
        self._timeline.frame_picked.connect(self._on_frame_picked)
        left.addWidget(self._timeline)
        left.addWidget(self._build_transport())
        body.addLayout(left, 1)

        self._panel = ConfirmSidePanel()
        self._panel.status_requested.connect(self._on_status_requested)
        self._panel.cancel_requested.connect(self._cancel_pending)
        self._panel.retry_requested.connect(self._retry_status_only)
        self._panel.past_note_clicked.connect(self._on_past_note)
        self._panel.memo_edited.connect(self._draft_timer.start)
        self._panel.insert_failures_requested.connect(self._insert_failures)
        from bpe.shotgrid.tasks import BELUCA_TASK_STATUS_PRESETS

        self._panel.set_other_statuses(
            [(c, lbl) for c, lbl in BELUCA_TASK_STATUS_PRESETS if c not in ("retake", "cfrm")]
        )
        body.addWidget(self._panel)
        root.addLayout(body, 1)

        self._scrim = QPushButton(self)  # 서랍이 열렸을 때 나머지 화면을 가리는 막(누르면 닫힘)
        self._scrim.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scrim.setStyleSheet(
            "QPushButton, QPushButton:hover { background: rgba(0, 0, 0, 110); border: none; "
            "border-radius: 0px; }"
        )
        self._scrim.clicked.connect(self._toggle_drawer)
        self._scrim.hide()
        self._drawer = ShotDrawer(self)
        self._drawer.task_picked.connect(self._open_task)
        self._drawer.rows_changed.connect(self._sync_header)
        self._drawer.hide()
        self._panel.past_frame_clicked.connect(self._on_past_frame)
        self._panel.preset_picked.connect(self._on_preset_picked)
        self._view.view_changed.connect(self._sync_fit)
        self._view.scrub_started.connect(self._on_scrub_started)
        self._view.scrub_moved.connect(self._on_scrub_moved)
        for lbl in self.findChildren(QLabel):
            lbl.setIndent(0)  # 테두리 있는 글 칸이 스스로 넣는 들여쓰기를 없애 줄을 맞춘다

    def _build_header(self) -> QFrame:
        head = _bar_frame("confirm_header", style.HEADER)
        head.setFixedHeight(_HEADER_H)
        row = QHBoxLayout(head)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(10)
        self._btn_list = _btn(" 목록", checkable=True, tip="샷 목록 열기 · 닫기")
        style.set_icon(self._btn_list, "list", size=14)
        self._btn_list.setStyleSheet(
            style.segment_style("only", text_color=style.TEXT_STRONG)
            + "QPushButton { padding: 0px 8px; }"
        )
        self._btn_list.clicked.connect(self._toggle_drawer)
        row.addWidget(self._btn_list)
        self._crumb = QLabel("영상을 열어 주세요")
        self._crumb.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self._crumb)
        self._ver_chip = QLabel("")
        self._ver_chip.setStyleSheet(style.field_style(pad="2px 8px"))
        row.addWidget(self._ver_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self._who = QLabel("")
        self._who.setStyleSheet(f"color: {style.DIM};")
        row.addWidget(self._who)
        status = QHBoxLayout()
        status.setSpacing(5)
        self._status_dot = QLabel()  # 상태 색 네모 + 아이콘
        self._status_dot.setFixedSize(16, 16)
        status.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._status_lbl = QLabel("")
        status.addWidget(self._status_lbl)
        row.addLayout(status)
        row.addStretch(1)
        self._pos = QLabel("")
        self._pos.setStyleSheet(f"color: {style.DIM}; {style.mono()}")
        row.addWidget(self._pos)
        nav = QHBoxLayout()
        nav.setSpacing(0)
        self._btn_prev = _icon_btn("chev_left", "이전 샷", size=14)
        self._btn_next = _icon_btn("chev_right", "다음 샷", size=14)
        self._btn_prev.clicked.connect(lambda: self._nav_shot(-1))
        self._btn_next.clicked.connect(lambda: self._nav_shot(1))
        for b, pos in ((self._btn_prev, "first"), (self._btn_next, "last")):
            b.setStyleSheet(style.segment_style(pos) + style.fixed_width_style(31))
            nav.addWidget(b)
        row.addLayout(nav)
        row.addWidget(_divider())
        self._btn_open = _icon_btn("folder", "영상 파일 열기…")
        self._btn_open.clicked.connect(self._pick_file)
        row.addWidget(self._btn_open)
        self._btn_full = _icon_btn("fullscreen", "전체화면 (F11)", checkable=True)
        self._btn_full.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._btn_full)
        self._btn_help = _icon_btn("help", "단축키 (?)")
        self._btn_help.clicked.connect(self._toggle_help)
        row.addWidget(self._btn_help)
        return head

    def _build_bar(self) -> QFrame:
        """위 조작 띠. 두 줄의 왼쪽 묶음 폭을 같게 해서 채널 묶음과 LUT 묶음의 왼쪽 끝을 맞춘다."""
        bar = _bar_frame("confirm_bar", style.PANEL)
        grid = QGridLayout(bar)
        grid.setContentsMargins(8, 5, 8, 5)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)

        pick = QHBoxLayout()
        pick.setSpacing(10)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self._buf_btns: Dict[str, KeyButton] = {}
        self._buf_marks: Dict[str, str] = {}
        for key, number, _title in _BUFFER_DEFS:
            b = KeyButton(str(number))
            b.setToolTip(f"숫자 키 {number}")
            b.clicked.connect(lambda _c=False, k=key: self._show_buffer(k))
            self._buf_btns[key] = b
            seg.addWidget(b)
        style.make_segments(list(self._buf_btns.values()))
        pick.addLayout(seg)
        self._btn_diff = _btn(
            "Difference", checkable=True, tip="Difference: 지금 보는 판 − 직전에 본 판 (D)"
        )
        self._btn_diff.setMinimumWidth(122)
        style.set_icon(self._btn_diff, "diff", size=14)
        self._btn_diff.setStyleSheet(style.warn_toggle_style())
        self._btn_diff.clicked.connect(self._toggle_diff)
        pick.addWidget(self._btn_diff)
        grid.addLayout(pick, 0, 0)

        chans = QHBoxLayout()
        chans.setSpacing(10)
        cseg = QHBoxLayout()
        cseg.setSpacing(0)
        self._chan_btns: Dict[str, QPushButton] = {}
        for i, (label, ch) in enumerate(_CHANNELS):
            tip = "밝기만 보기 (A)" if ch == CHANNEL_LUMA else f"{label} (한 번 더 누르면 RGB)"
            b = _btn(label, checkable=True, tip=tip)
            pos = "first" if i == 0 else "last" if i == len(_CHANNELS) - 1 else "mid"
            warn = ch != CHANNEL_RGB
            b.setStyleSheet(
                style.segment_style(
                    pos,
                    on_color=style.WARN if warn else "",
                    text_color=style.CHANNEL_COLORS.get(label, ""),
                )
                + f"QPushButton {{ {style.mono(bold=True)} padding: 0px 9px; }}"
            )
            b.clicked.connect(lambda _c=False, c=ch: self._set_channel(c))
            self._chan_btns[ch] = b
            cseg.addWidget(b)
        chans.addLayout(cseg)
        chans.addStretch(1)
        fseg = QHBoxLayout()
        fseg.setSpacing(0)
        self._btn_fit = _btn("Fit (F)", checkable=True, tip="영상 전체가 보이게 맞춤")
        self._btn_fit.clicked.connect(self._view_fit)
        fseg.addWidget(self._btn_fit)
        self._btn_fill = _btn("Fill (H)", checkable=True, tip="빈 곳 없이 화면을 꽉 채움")
        self._btn_fill.clicked.connect(self._view_fill)
        fseg.addWidget(self._btn_fill)
        style.make_segments([self._btn_fit, self._btn_fill])
        chans.addLayout(fseg)
        self._btn_fullview = _btn(
            "Fullscreen (F11)", tip="영상만 화면 가득 — 나올 때는 Esc 또는 F11"
        )
        style.set_icon(self._btn_fullview, "fullscreen", size=14)
        self._btn_fullview.clicked.connect(self._toggle_fullscreen)
        chans.addWidget(self._btn_fullview)
        grid.addLayout(chans, 0, 1)

        tone = QHBoxLayout()
        tone.setSpacing(8)
        flat = (
            f"QPushButton {{ border: none; background: transparent; color: {style.DIM}; "
            f"padding: 0px 2px; }} "
            f"QPushButton:hover {{ color: {style.TEXT}; background: transparent; }}"
        )
        self._btn_gain = _btn("게인", tip="누르면 1.00 으로")
        self._btn_gain.setStyleSheet(flat)
        self._btn_gain.clicked.connect(lambda: self._gain.setValue(0))
        tone.addWidget(self._btn_gain)
        self._gain = QSlider(Qt.Orientation.Horizontal)
        self._gain.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 좌우 같은 폭 — 1.00 이 막대 한가운데
        self._gain.setRange(-_GAIN_STOPS * _GAIN_STEPS_PER_STOP, _GAIN_STOPS * _GAIN_STEPS_PER_STOP)
        self._gain.setMinimumWidth(80)
        self._gain.valueChanged.connect(self._sync_view)
        tone.addWidget(self._gain, 1)
        self._gain_val = QLabel("1.00")
        self._gain_val.setFixedWidth(46)
        self._gain_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tone.addWidget(self._gain_val)
        tone.addSpacing(4)
        self._btn_gamma = _btn("감마", tip="누르면 1.00 으로")
        self._btn_gamma.setStyleSheet(flat)
        self._btn_gamma.clicked.connect(lambda: self._gamma.setValue(0))
        tone.addWidget(self._btn_gamma)
        self._gamma = QSlider(Qt.Orientation.Horizontal)
        self._gamma.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 로그 눈금: 0 이 감마 1.00(한가운데), 양 끝이 1/4 배 · 4 배
        self._gamma.setRange(-_GAMMA_STEPS, _GAMMA_STEPS)
        self._gamma.setMinimumWidth(80)
        self._gamma.valueChanged.connect(self._sync_view)
        tone.addWidget(self._gamma, 1)
        self._gamma_val = QLabel("1.00")
        self._gamma_val.setFixedWidth(46)
        self._gamma_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tone.addWidget(self._gamma_val)
        grid.addLayout(tone, 1, 0)

        look = QHBoxLayout()
        look.setSpacing(10)
        lseg = QHBoxLayout()
        lseg.setSpacing(0)
        self._btn_lut = _btn("LUT", checkable=True, tip="룩업 켜고 끄기 (L)")
        self._btn_lut.setStyleSheet(style.lut_toggle_style(loaded=False))
        self._btn_lut.clicked.connect(self._toggle_lut)
        lseg.addWidget(self._btn_lut)
        self._btn_lut_pick = _btn("", tip=".cube 파일 고르기 — 프로젝트별로 기억합니다")
        self._btn_lut_pick.setStyleSheet(
            style.segment_style("last") + f"QPushButton {{ background: {style.FIELD}; }}"
        )
        self._btn_lut_pick.clicked.connect(self._pick_lut)
        lseg.addWidget(self._btn_lut_pick)
        look.addLayout(lseg)
        self._btn_reset = _btn("보기 원래대로")
        self._btn_reset.setStyleSheet(style.warn_button_style())
        self._btn_reset.clicked.connect(self._reset_view)
        self._btn_reset.hide()
        look.addWidget(self._btn_reset)
        look.addStretch(1)
        grid.addLayout(look, 1, 1)
        return bar

    def _build_overlays(self) -> None:
        """뷰어 위에 뜨는 글자·도구 띠(그리기 층보다 위)."""
        self._hud = QLabel("", self._view)
        self._hud.setStyleSheet(
            f"background: #000000; color: #e6e6e6; padding: 2px 6px; "
            f"{style.mono(style.FONT_SMALL_PX)}"
        )
        self._hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._state = QLabel("", self._view)
        self._state.setStyleSheet(
            f"background: #000000; color: {style.WARN}; padding: 2px 6px; "
            f"{style.mono(style.FONT_SMALL_PX)}"
        )
        self._state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._banner = QLabel("", self._view)
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner.setStyleSheet(
            "background: #a32d2d; color: #ffffff; font-weight: bold; padding: 6px 14px; "
            f"font-size: {style.FONT_PX + 2}px;"
        )
        self._banner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._banner.hide()
        self._hud.hide()  # 글이 생길 때만 보인다(빈 검은 칸이 뜨지 않게)
        self._state.hide()
        self._btn_exit_full = QPushButton("Exit Fullscreen (Esc)", self._view)
        self._btn_exit_full.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_exit_full.setCursor(Qt.CursorShape.PointingHandCursor)
        style.set_icon(self._btn_exit_full, "fullscreen", size=14)
        self._btn_exit_full.clicked.connect(self._toggle_fullscreen)
        self._btn_exit_full.hide()
        self._busy = QLabel("", self._view)
        self._busy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._busy.setTextFormat(Qt.TextFormat.RichText)
        self._busy.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._busy.hide()
        self._help = QLabel(self._help_text(), self._view)
        self._help.setStyleSheet(
            f"background: {style.PANEL}; color: {style.TEXT}; padding: 12px 16px; "
            f"border: 1px solid {style.EDGE}; border-radius: 6px;"
        )
        self._help.hide()

        self._pill = QFrame(self._view)
        self._pill.setObjectName("confirm_pill")
        self._pill.setStyleSheet(
            f"QFrame#confirm_pill {{ background: {style.PANEL}; border: 1px solid {style.EDGE}; "
            f"border-radius: 6px; }}"
        )
        prow = QHBoxLayout(self._pill)
        prow.setContentsMargins(4, 4, 4, 4)
        prow.setSpacing(2)
        prow.addWidget(Grip())
        self._tool_btns: Dict[str, QPushButton] = {}
        for tool, icon, label, key in _TOOLS:
            b = _btn("", checkable=True, tip=f"{label} ({key})")
            style.set_icon(b, icon, size=16)
            b.setStyleSheet(style.icon_button_style(30))
            b.clicked.connect(lambda _c=False, t=tool: self._set_tool(t))
            self._tool_btns[tool] = b
            prow.addWidget(b)
        self._btn_erase = _btn("", tip="고른 그림 지우기 (Delete)")
        style.set_icon(self._btn_erase, "eraser", size=16)
        self._btn_erase.setStyleSheet(style.icon_button_style(30))
        self._btn_erase.clicked.connect(lambda: self._layer.delete_selected())
        prow.addWidget(self._btn_erase)
        prow.addSpacing(4)
        prow.addWidget(_divider())
        prow.addSpacing(6)
        self._swatch_btns: List[QPushButton] = []
        for i in range(len(self._recent_colors)):
            b = _btn("", tip="그리기 색 (최근에 쓴 색)")
            b.clicked.connect(lambda _c=False, n=i: self._set_color(self._recent_colors[n]))
            self._swatch_btns.append(b)
            prow.addWidget(b)
            prow.addSpacing(3)
        self._btn_palette = _btn("", checkable=True, tip="색 더 고르기")
        style.set_icon(self._btn_palette, "palette", size=16)
        self._btn_palette.setStyleSheet(style.icon_button_style(30))
        self._btn_palette.clicked.connect(self._toggle_palette)
        prow.addWidget(self._btn_palette)
        prow.addSpacing(3)
        prow.addWidget(_divider())
        prow.addSpacing(4)
        actions: Tuple[Tuple[str, str, Callable[[], Any]], ...] = (
            ("undo", "되돌리기 (Ctrl+Z)", self._layer.undo),
            ("redo", "다시 (Ctrl+Y)", self._layer.redo),
            ("range", "고른 그림을 지금 프레임까지 이어지는 구간으로", self._extend_selected),
        )
        for icon, tip, slot in actions:
            b = _btn("", tip=tip)
            style.set_icon(b, icon, size=16)
            b.setStyleSheet(style.icon_button_style(30))
            b.clicked.connect(lambda _c=False, f=slot: f())
            prow.addWidget(b)
        prow.addSpacing(6)
        self._tool_hint = QLabel("")
        self._tool_hint.setStyleSheet(f"color: {style.DIM};")
        self._tool_hint.setFixedWidth(_HINT_W)
        prow.addWidget(self._tool_hint)
        prow.addSpacing(6)
        self._palette = QFrame(self._view)
        self._palette.setObjectName("confirm_palette")
        self._palette.setStyleSheet(
            f"QFrame#confirm_palette {{ background: {style.PANEL}; "
            f"border: 1px solid {style.EDGE}; border-radius: 6px; }}"
        )
        grid = QGridLayout(self._palette)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)
        self._palette_btns: Dict[str, QPushButton] = {}
        for i, color in enumerate(style.PALETTE):
            b = _btn("", tip=color)
            b.clicked.connect(lambda _c=False, c=color: self._set_color(c))
            self._palette_btns[color] = b
            grid.addWidget(b, i // style.PALETTE_COLUMNS, i % style.PALETTE_COLUMNS)
        self._palette.hide()
        self._view.view_changed.connect(self._place_overlays)

    def _build_transport(self) -> QFrame:
        bar = _bar_frame("confirm_transport", style.PANEL, bottom=False)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 6)
        row.setSpacing(8)
        left = QHBoxLayout()
        left.setSpacing(6)
        self._fps_lbl = QLabel("")
        self._fps_lbl.setStyleSheet(style.field_style())
        left.addWidget(self._fps_lbl)
        left.addWidget(_dim_label("fps", mono=True))
        left.addSpacing(8)
        self._start_lbl = QLabel("")
        self._start_lbl.setStyleSheet(style.field_style())
        left.addWidget(self._start_lbl)
        left.addWidget(_dim_label("–", mono=True))
        self._end_lbl = QLabel("")
        self._end_lbl.setStyleSheet(style.field_style())
        left.addWidget(self._end_lbl)
        left.addStretch(1)
        row.addLayout(left, 1)

        seg = QHBoxLayout()
        seg.setSpacing(0)
        specs: Tuple[Tuple[str, str, Callable[[], Any]], ...] = (
            ("first", "처음 프레임 (Home)", self._go_first),
            ("step_back", "한 프레임 앞 (←)", lambda: self._step(-1)),
            ("play", "재생 · 멈춤 (Space)", self._toggle_play),
            ("step_fwd", "한 프레임 뒤 (→)", lambda: self._step(1)),
            ("last", "마지막 프레임 (End)", self._go_last),
        )
        buttons: List[QPushButton] = []
        for icon, tip, slot in specs:
            b = _btn("", tip=tip)
            style.set_icon(b, icon, size=14)
            b.clicked.connect(lambda _c=False, f=slot: f())
            buttons.append(b)
            seg.addWidget(b)
        style.make_segments(buttons)
        for b in buttons:
            b.setStyleSheet(b.styleSheet() + style.fixed_width_style(34))
        self._btn_play = buttons[2]
        self._btn_play.setStyleSheet(
            self._btn_play.styleSheet()
            + style.fixed_width_style(46)
            + f"QPushButton {{ background: {style.ON}; }}"
        )
        row.addLayout(seg)

        right = QHBoxLayout()
        right.setSpacing(6)
        self._btn_loop = _btn("", checkable=True, tip="반복 재생")
        style.set_icon(self._btn_loop, "loop", size=14)
        self._btn_loop.setChecked(True)
        self._btn_loop.setStyleSheet(style.segment_style("only") + style.fixed_width_style(34))
        self._btn_loop.clicked.connect(lambda c: setattr(self, "_loop", bool(c)))
        right.addWidget(self._btn_loop)
        right.addStretch(1)
        self._frame_edit = QLineEdit()
        self._frame_edit.setFixedWidth(64)
        self._frame_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._frame_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_edit.setStyleSheet(
            f"QLineEdit {{ color: {style.TEXT_STRONG}; {style.mono(14, bold=True)} }}"
        )
        self._frame_edit.returnPressed.connect(self._on_frame_typed)
        right.addWidget(self._frame_edit)
        self._total_lbl = _dim_label("", mono=True)
        right.addWidget(self._total_lbl)
        row.addLayout(right, 1)
        return bar

    @staticmethod
    def _help_text() -> str:
        key_style = (
            f"padding: 1px 6px; background-color: {style.FIELD}; color: {style.TEXT_STRONG}; "
            f"{style.mono(style.FONT_SMALL_PX)}"
        )
        rows: List[str] = []
        for group, items in _SHORTCUTS:
            rows.append(
                f'<tr><td colspan="2" style="padding: 8px 0 3px 0; color:{style.LABEL}; '
                f'font-size:{style.FONT_SMALL_PX}px; font-weight:bold">{escape(group)}</td></tr>'
            )
            for keys, what in items:
                chips = "&nbsp;".join(
                    f'<span style="{key_style}">&nbsp;{escape(k)}&nbsp;</span>' for k in keys
                )
                rows.append(
                    f'<tr><td style="padding: 3px 20px 3px 0">{chips}</td>'
                    f'<td style="padding: 3px 0; color:{style.TEXT}">{escape(what)}</td></tr>'
                )
        return (
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="font-weight:bold; color:{style.TEXT_STRONG}">단축키</td>'
            f'<td align="right" style="color:{style.DIM}; font-size:{style.FONT_SMALL_PX}px">'
            f"Esc 닫기</td></tr></table>"
            f'<table cellspacing="0" cellpadding="0">{"".join(rows)}</table>'
        )

    # ── 영상 열기 ────────────────────────────────────────────────

    def is_closed(self) -> bool:
        return self._closed

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "영상 파일 고르기", "", _VIDEO_FILTER)
        if path:
            self.open_movie(path)

    def open_movie(self, movie: str, task: Optional[Dict[str, Any]] = None) -> None:
        """작업본 영상 하나에서 출발해 같은 샷의 재료를 찾아 올린다."""
        self._save_draft()
        self._stop_decoders()
        self._cancel_pending()
        self._pause()
        self._load_token += 1
        token = self._load_token
        self._movie = movie
        self._shot_root = None
        self._task = dict(task or {})
        self._drawer.set_current_task(self._task.get("task_id"))
        self._sent_note_id = None
        self._version_note = ""
        for buf in self._bufs.values():
            buf.path, buf.info, buf.size, buf.frames = None, None, (0, 0), {}
            buf.full, buf.lut_baked, buf.version_label, buf.error = False, False, "", ""
        self._index, self._count = 0, 0
        self._checks = []
        self._standard, self._preset_names, self._basis = None, [], ""
        self._shown, self._last_shown, self._diff = KEY_CUR, KEY_ORG, False
        self._layer.set_doc(AnnotationDoc())
        self._layer.set_ghosts([])
        self._timeline.set_range(self._frame_start, 0)
        self._panel.set_result("", True)
        self._panel.set_checks([])
        self._panel.set_standard("", "", [], "")
        self._panel.set_past_notes([])
        self._hud.setText(Path(movie).stem)
        self._hud.adjustSize()
        self._hud.show()
        self._set_busy(f"{Path(movie).stem} 여는 중…", "원본 · 전 버전 · 편집본 찾는 중")
        if self._open_started <= 0:
            self._open_started = time.perf_counter()
        logger.info("confirm open: movie resolved +%.2fs", time.perf_counter() - self._open_started)
        self._sync_all()

        project = self._project_key()
        picked = dict(get_confirm_settings()["presets"])

        def _prepare() -> Dict[str, Any]:
            media = find_shot_media(Path(movie))
            paths = {
                KEY_CUR: media.current.path if media.current else None,
                KEY_PREV: media.previous.path if media.previous else None,
                KEY_ORG: media.org,
                KEY_EDIT: media.edit,
            }
            infos = {k: (probe_video(str(p)) if p else None) for k, p in paths.items()}
            # 검사 기준: 이 프로젝트의 프리셋. 여러 개면 플레이트 색(Rec.709/Gamma — 샷 빌더와
            # 같은 판별)과 올라온 영상 크기(AI 프리셋 / 일반 프리셋)로 고르고, 그래도 못 정하면
            # 전에 고른 것 → 일반 프리셋.
            names = preset_names_for(read_presets(), project, Path(movie).parts)
            name, why = (names[0] if names else ""), ""
            standards = {n: load_standard(n) for n in names} if len(names) > 1 else {}
            if len(names) > 1:
                color = inspect_mov_color(media.org).result if media.org else None
                cur = infos.get(KEY_CUR)
                size = (cur.width, cur.height) if cur and cur.width and cur.height else None
                name, decided = pick_preset(
                    names,
                    plate_color=color,
                    work_size=size,
                    sizes={n: st.mov_sizes for n, st in standards.items() if st is not None},
                )
                parts = []
                if color:
                    parts.append(f"플레이트 {DISPLAY_NAME.get(color, color)}")
                if size:
                    parts.append(f"영상 크기 {size[0]}×{size[1]}")
                if decided:
                    why = "자동: " + " · ".join(parts)
                else:
                    saved = picked.get(names[0], "")
                    name = saved if saved in names else name
                    why = "자동으로 못 정함 — 아래에서 골라 주세요"
            standard = standards.get(name)
            if standard is None and name:
                standard = load_standard(name)
            return {
                "media": media,
                "paths": paths,
                "infos": infos,
                "standard": standard,
                "preset_names": names,
                "preset_why": why,
            }

        w = ShotGridWorker(_prepare)
        w.finished.connect(lambda r, t=token: self._on_prepared(r, t))
        w.error.connect(lambda e, t=token: self._on_prepare_failed(e, t))
        w.start()
        self._workers.append(w)

    def _on_prepare_failed(self, msg: str, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        self._set_busy("영상을 열지 못했습니다", msg, error=True)

    def _on_prepared(self, result: object, token: int) -> None:
        if token != self._load_token or self._closed or not isinstance(result, dict):
            return
        media = result["media"]
        paths: Dict[str, Optional[Path]] = result["paths"]
        infos: Dict[str, Optional[VideoInfo]] = result["infos"]
        cur_info = infos.get(KEY_CUR)
        if cur_info is None:
            self._set_busy("영상 규격을 읽지 못했습니다", Path(self._movie).name, error=True)
            return
        self._shot_root = media.shot_root
        cur_size = fit_decode_size(cur_info.width, cur_info.height, _MAX_W, _MAX_H)
        self._count = max(1, cur_info.frame_count or 1)
        self._fps = cur_info.fps or 24.0
        budget = int(get_confirm_settings()["cache_mb"]) * 1024 * 1024
        for key in _DECODE_ORDER:
            buf = self._bufs[key]
            buf.path, buf.info = paths.get(key), infos.get(key)
            if buf.path is None or buf.info is None:
                continue
            if key == KEY_CUR:
                buf.size = cur_size
            else:
                buf.size = fit_decode_size(buf.info.width, buf.info.height, *cur_size)
            need = frame_byte_size(*buf.size) * min(self._count, buf.frame_count() or self._count)
            buf.full = key == KEY_CUR or need <= budget
            if buf.full:
                budget -= need
        if media.current:
            self._bufs[KEY_CUR].version_label = media.current.label
            self._bufs[KEY_CUR].lut_baked = media.current.has_lut_baked
        if media.previous:
            self._bufs[KEY_PREV].version_label = media.previous.label
            self._bufs[KEY_PREV].lut_baked = media.previous.has_lut_baked
        # 노트는 샷그리드의 최신 버전에 붙는다 — 보고 있는 파일이 그 버전이 아니면 알린다
        want = parse_version(str(self._task.get("latest_version_code") or ""))
        if want is not None and media.current and media.current.version != want:
            self._version_note = (
                f"보는 파일은 {media.current.label}, 샷그리드 최신은 v{want:03d} 입니다 — "
                f"노트는 v{want:03d} 에 붙습니다"
            )
            self._panel.set_result(self._version_note, False)

        standard = result.get("standard")
        self._standard = standard if isinstance(standard, ProjectStandard) else None
        self._preset_names = list(result.get("preset_names") or [])
        self._preset_why = str(result.get("preset_why") or "")
        self._run_checks()
        self._timeline.set_range(self._frame_start, self._count)
        self._last_shown = KEY_ORG if self._bufs[KEY_ORG].available else KEY_PREV
        self._load_draft()
        self._load_project_lut()
        self._fill_work_info()
        self._decode_queue = [
            k for k in _DECODE_ORDER if self._bufs[k].available and self._bufs[k].full
        ]
        self._set_busy(f"{Path(self._movie).stem} 올리는 중…", f"0 / {self._count} 프레임")
        logger.info("confirm open: media ready +%.2fs", time.perf_counter() - self._open_started)
        self._start_next_decode()
        self._sync_all()
        self._load_sg_context()

    # ── 상태 색·아이콘 ───────────────────────────────────────────

    def _ensure_status_styles(self) -> None:
        """샷그리드에 정해 둔 상태별 색·아이콘을 한 번만 읽어 온다."""
        if self._status_styles_asked:
            return
        self._status_styles_asked = True

        def _fetch() -> Dict[str, Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.confirm_status import fetch_status_styles

            return fetch_status_styles(get_default_sg())

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_status_styles)
        w.error.connect(self._on_status_styles_failed)
        w.start()
        self._workers.append(w)

    def _on_status_styles_failed(self, msg: str) -> None:
        self._status_styles_asked = False  # 다음에 다시 읽어 본다
        logger.warning("confirm: status styles load failed: %s", msg)

    def _on_status_styles(self, result: object) -> None:
        if self._closed or not isinstance(result, dict) or not result:
            return
        status_style.set_styles(result)
        self._panel.refresh_status_styles()
        self._drawer.refresh_rows()
        self._sync_header()

    # ── 검사 기준(프리셋) ────────────────────────────────────────

    def _run_checks(self) -> None:
        """현재버전을 판정하고 패널에 알린다. 프레임 수는 edit(없으면 ORG plate),

        나머지는 프리셋 기준이다(edit 은 길이만 참고한다).
        """
        ref_key = KEY_EDIT if self._bufs[KEY_EDIT].info else KEY_ORG
        ref = self._bufs[ref_key]
        plate = self._bufs[KEY_ORG]
        self._checks = check_work_against_reference(
            self._bufs[KEY_CUR].info,
            ref.info,
            ref.title,
            standard=self._standard,
            plate=plate.info,
            plate_label=plate.title,
        )
        self._basis = basis_text(ref.title, ref.info is not None, self._standard)
        self._panel.set_checks(self._checks)
        s = self._standard
        if s is None:
            look = ""
        elif s.look:
            look = f"{s.look} 입혀진 MOV — 룩업 안 씌움"
        elif s.viewer:
            look = f"MOV 에 룩 없음 · 프리셋 뷰어 {s.viewer} — 룩업 파일을 골라 주세요"
        else:
            look = ""
        self._panel.set_standard(
            f"{self._basis} ({self._preset_why})" if self._preset_why else self._basis,
            look,
            self._preset_names,
            s.preset if s is not None else "",
        )

    def _look_baked(self, buf: _Buffer) -> bool:
        """이 판에 룩이 이미 입혀져 있나 — 파일 이름(_lut) 또는 프리셋이 그렇게 내보내는 작업본."""
        by_preset = bool(self._standard and self._standard.look)
        return buf.lut_baked or (by_preset and buf.key in (KEY_CUR, KEY_PREV))

    def _on_preset_picked(self, name: str) -> None:
        if not self._preset_names or name not in self._preset_names:
            return
        picked = dict(get_confirm_settings()["presets"])
        picked[self._preset_names[0]] = name
        save_confirm_settings({"presets": picked})
        self._preset_why = "직접 고름"
        token = self._load_token
        w = ShotGridWorker(lambda: load_standard(name))
        w.finished.connect(lambda r, t=token: self._on_standard_loaded(r, t))
        w.error.connect(lambda e: logger.warning("confirm: preset load failed: %s", e))
        w.start()
        self._workers.append(w)

    def _on_standard_loaded(self, result: object, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        self._standard = result if isinstance(result, ProjectStandard) else None
        self._run_checks()
        self._sync_all()

    # ── 목록에서 열기 ────────────────────────────────────────────

    def _toggle_drawer(self) -> None:
        show = not self._drawer.isVisible()
        self._drawer.setVisible(show)
        self._scrim.setVisible(show)
        if show:
            self._place_drawer()
            self._scrim.raise_()
            self._drawer.raise_()
            self._drawer.load_projects()
            self._ensure_status_styles()
        self._btn_list.setChecked(show)

    def _place_drawer(self) -> None:
        h = self.height() - _HEADER_H
        self._drawer.setGeometry(0, _HEADER_H, self._drawer.width(), h)
        self._scrim.setGeometry(
            self._drawer.width(), _HEADER_H, self.width() - self._drawer.width(), h
        )

    def _open_task(self, task: Dict[str, Any]) -> None:
        """목록에서 고른 샷 — 바로 반응을 보이고, 서버에서 작업본 영상을 찾아 연다."""
        row = dict(task)
        shot = str(row.get("shot_code") or "")
        if self._drawer.isVisible():
            self._toggle_drawer()
        self._pause()
        self._task = row  # 위 막대가 바로 고른 샷으로 바뀐다
        self._shot_root = None
        self._drawer.set_current_task(row.get("task_id"))
        self._sync_header()
        self._set_busy(f"{shot} 여는 중…", "서버에서 영상 파일 찾는 중")
        self._open_started = time.perf_counter()
        self._load_token += 1
        token = self._load_token

        def _resolve() -> str:
            from bpe.core.feedback_project_paths import effective_project_for_paths
            from bpe.core.nk_finder import (
                find_server_root_auto,
                resolve_local_comp_mov_for_feedback,
            )
            from bpe.core.nuke_render_paths import normalize_path_str

            proj = effective_project_for_paths(row)
            root = (os.environ.get("BPE_FEEDBACK_SERVER_ROOT") or "").strip()
            if not root:
                auto = find_server_root_auto(proj)
                root = str(auto) if auto else (os.environ.get("BPE_SERVER_ROOT") or "").strip()
            root = normalize_path_str(root).strip() if root else ""
            sg_path = row.get("latest_version_sg_path") or ""
            version_code = (row.get("latest_version_code") or "").strip()
            if not sg_path:  # 내부 샷: 늘 있는 자리부터 본다(넓게 찾기는 몇 초 걸림)
                quick = quick_version_movie(
                    root,
                    proj,
                    row.get("shot_code") or "",
                    version_code,
                    (str(row.get("task_content") or ""), "comp", "precomp"),
                )
                if quick is not None:
                    return normalize_path_str(str(quick))
            mov, _tried, _warn = resolve_local_comp_mov_for_feedback(
                row.get("shot_code") or "",
                proj,
                root,
                sg_movie_raw=sg_path,
                version_code=version_code or None,
            )
            return normalize_path_str(str(mov)) if mov is not None else ""

        w = ShotGridWorker(_resolve)
        w.finished.connect(lambda r, t=token, tk=row: self._on_task_resolved(r, t, tk))
        w.error.connect(lambda e, t=token: self._on_prepare_failed(e, t))
        w.start()
        self._workers.append(w)

    def _on_task_resolved(self, result: object, token: int, task: Dict[str, Any]) -> None:
        if token != self._load_token or self._closed:
            return
        if not isinstance(result, str) or not result:
            ver = str(task.get("latest_version_code") or task.get("shot_code") or "")
            self._set_busy(
                "영상 파일을 찾지 못했습니다",
                f"{ver} — 서버에 MOV 가 아직 없거나 폴더 모양이 다릅니다",
                error=True,
            )
            return
        self.open_movie(result, task)

    def _nav_shot(self, delta: int) -> None:
        rows = self._drawer.shown_rows()
        cur = self._task.get("task_id")
        idx = next((i for i, r in enumerate(rows) if r.get("task_id") == cur), -1)
        nxt = idx + delta
        if rows and 0 <= nxt < len(rows):
            self._open_task(rows[nxt])

    # ── 풀기(디코드) ─────────────────────────────────────────────

    def _start_next_decode(self) -> None:
        if self._decoding is not None or not self._decode_queue or self._closed:
            return
        key = self._decode_queue.pop(0)
        buf = self._bufs[key]
        w = StreamDecodeWorker(
            key, str(buf.path), buf.size[0], buf.size[1], frame_count=self._count
        )
        token = self._load_token
        w.frame_ready.connect(lambda k, i, d, t=token: self._on_frame(k, i, d, t))
        w.finished_ok.connect(lambda _k, _n, t=token: self._on_decode_done(t))
        w.failed.connect(lambda k, m, t=token: self._on_decode_failed(k, m, t))
        self._decoding = w
        self._decoders.append(w)
        w.start()

    def _on_frame(self, key: str, index: int, data: object, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        buf = self._bufs[key]
        buf.frames[index] = data
        self._ondemand_pending.pop((key, index), None)
        if not buf.full and len(buf.frames) > _ONDEMAND_KEEP:
            far = sorted(buf.frames, key=lambda i: abs(i - self._index), reverse=True)
            for old in far[: len(buf.frames) - _ONDEMAND_KEEP]:
                buf.frames.pop(old, None)
        if key == KEY_CUR:
            self._timeline.add_cached(index)
            if self._busy.isVisible():
                if self._buffer_index(buf) in buf.frames:
                    self._set_busy("")  # 지금 프레임이 올라왔다 — 그림이 보인다
                    logger.info(
                        "confirm open: first picture +%.2fs",
                        time.perf_counter() - self._open_started,
                    )
                    self._open_started = 0.0
                else:
                    name = Path(self._movie).stem
                    self._set_busy(
                        f"{name} 올리는 중…", f"{len(buf.frames)} / {self._count} 프레임"
                    )
        if index == self._buffer_index(buf) and key in (self._shown, self._diff_base()):
            self._refresh_view()

    def _on_decode_done(self, token: int) -> None:
        if token != self._load_token:
            return
        self._decoding = None
        self._start_next_decode()

    def _on_decode_failed(self, key: str, msg: str, token: int) -> None:
        if token != self._load_token:
            return
        self._bufs[key].error = msg
        if self._decoding is not None and self._decoding.key == key:
            self._decoding = None
        self._ondemand_pending = {k: v for k, v in self._ondemand_pending.items() if k[0] != key}
        self._start_next_decode()
        self._sync_all()

    def _request_frame(self, buf: _Buffer, index: int) -> None:
        """메모리에 다 못 올린 판 — 필요한 프레임 한 장만 그때 푼다."""
        if buf.full or (buf.key, index) in self._ondemand_pending or not buf.available:
            return
        w = StreamDecodeWorker(
            buf.key, str(buf.path), buf.size[0], buf.size[1], start_index=index, frame_count=1
        )
        token = self._load_token
        w.frame_ready.connect(lambda k, i, d, t=token: self._on_frame(k, i, d, t))
        w.failed.connect(lambda k, _m, i=index: self._ondemand_pending.pop((k, i), None))
        self._ondemand_pending[(buf.key, index)] = w
        self._decoders.append(w)
        w.start()

    def _stop_decoders(self) -> None:
        for w in self._decoders:
            w.stop()
        for w in self._decoders:
            w.wait(_WORKER_WAIT_MS)
        self._decoders.clear()
        self._decode_queue = []
        self._decoding = None
        self._ondemand_pending = {}

    # ── 보기 ────────────────────────────────────────────────────

    def _buffer_index(self, buf: _Buffer) -> int:
        n = buf.frame_count() or self._count
        return max(0, min(self._index, n - 1))

    def _diff_base(self) -> str:
        return self._last_shown if self._diff else ""

    def _gain_value(self) -> float:
        return float(2.0 ** (self._gain.value() / _GAIN_STEPS_PER_STOP))

    def _gamma_value(self) -> float:
        return float(_GAMMA_SPAN ** (self._gamma.value() / _GAMMA_STEPS))

    def _set_gamma(self, gamma: float) -> None:
        steps = math.log(max(gamma, 1e-6)) / math.log(_GAMMA_SPAN) * _GAMMA_STEPS
        self._gamma.setValue(int(round(steps)))

    def frame_number(self) -> int:
        return self._frame_start + self._index

    def _refresh_view(self) -> None:
        buf = self._bufs[self._shown]
        if not buf.available:
            return
        idx = self._buffer_index(buf)
        data = buf.frames.get(idx)
        if data is None:
            self._request_frame(buf, idx)
            self._sync_labels()
            return
        mode = VIEW_MODE_A
        self._diff_note = ""
        if self._diff:
            other = self._bufs.get(self._last_shown)
            other_data = None
            if other is not None and other.available:
                oi = self._buffer_index(other)
                other_data = other.frames.get(oi)
                if other_data is None:
                    self._request_frame(other, oi)
            if other is None or other_data is None:
                self._diff_note = "비교할 판을 올리는 중"
            elif other.size != buf.size:
                self._diff_note = "화면 크기가 달라 Difference 를 볼 수 없음"
            else:
                self._view.set_image(SLOT_B, other_data, other.size[0], other.size[1])
                mode = VIEW_MODE_DIFF
        self._view.set_image(SLOT_A, data, buf.size[0], buf.size[1])
        self._view.set_view(
            gain=self._gain_value(),
            gamma=self._gamma_value(),
            mode=mode,
            channel=self._channel,
            lut_on=self._lut_on and self._lut is not None and not self._look_baked(buf),
        )
        self._layer.set_frame(self.frame_number())
        self._sync_labels()

    def _sync_view(self) -> None:
        gain, gamma = self._gain_value(), self._gamma_value()
        self._gain_val.setText(f"{gain:.2f}")
        self._gamma_val.setText(f"{gamma:.2f}")
        self._gain_val.setStyleSheet(style.field_style(changed=abs(gain - 1.0) > 1e-6))
        self._gamma_val.setStyleSheet(style.field_style(changed=abs(gamma - 1.0) > 1e-6))
        self._refresh_view()

    def _diff_label(self) -> str:
        a, b = self._bufs[self._shown].number, self._bufs[self._last_shown].number
        return f"Difference {a}−{b}"

    def _view_changes(self) -> List[str]:
        out: List[str] = []
        if self._diff:
            out.append(self._diff_label())
        if self._channel != CHANNEL_RGB:
            out.append(_CHANNEL_NAMES.get(self._channel, self._channel) + " 채널")
        if abs(self._gain_value() - 1.0) > 1e-6:
            out.append(f"게인 {self._gain_value():.2f}")
        if abs(self._gamma_value() - 1.0) > 1e-6:
            out.append(f"감마 {self._gamma_value():.2f}")
        return out

    def _sync_labels(self) -> None:
        buf = self._bufs[self._shown]
        if buf.available:
            name = buf.path.stem if buf.path else ""
            ready = buf.frames.get(self._buffer_index(buf)) is not None
            loading = "" if ready else "  올리는 중…"
            self._hud.setText(f"{buf.number} {buf.title}  {name}  {self.frame_number()}{loading}")
            self._hud.adjustSize()
            self._hud.show()
        changes = self._view_changes()
        notes = list(changes)
        if self._diff_note:
            notes.append(self._diff_note)
        if self._lut_on and self._look_baked(buf):
            notes.append("룩업이 이미 입혀진 파일 — 룩업 안 씌움")
        cur = self._bufs[KEY_CUR]
        if buf.key != KEY_CUR and buf.info and cur.info:
            if (buf.info.width * cur.info.height) != (cur.info.width * buf.info.height):
                notes.append(f"화면 비율이 작업본과 다름 ({buf.info.width}×{buf.info.height})")
        self._state.setText("보는 중: " + " · ".join(notes) if notes else "")
        self._state.setVisible(bool(notes))
        self._state.adjustSize()
        self._btn_reset.setVisible(bool(changes))
        self._btn_diff.setText(self._diff_label())
        self._timeline.set_current(self._index)
        if not self._frame_edit.hasFocus():
            self._frame_edit.setText(str(self.frame_number()))
        self._place_overlays()
        self._sync_info()

    def _sync_info(self) -> None:
        # 통과한 항목은 개수로 줄이고, 실패·모름만 글로 보여 준다(줄이 넘치지 않게)
        colors = {STATE_FAIL: style.FAIL}
        passed = sum(1 for r in self._checks if r.state == STATE_PASS)
        left: List[str] = []
        if passed:
            left.append(
                f'<span style="color:{style.OK}">검사 {passed}/{len(self._checks)} 통과</span>'
            )
        left += [
            f'<span style="color:{colors.get(r.state, style.DIM)}">{escape(r.message)}</span>'
            for r in self._checks
            if r.state != STATE_PASS
        ]
        if self._checks:
            left.append(escape(self._basis))
        right: List[str] = []
        buf = self._bufs[self._shown]
        if buf.info:
            i = buf.info
            fps = f"{i.fps:.3f}" if i.fps else "?"
            right.append(f"{i.width}×{i.height} · {escape(codec_label(i))} · {fps}")
        # 마우스 위치·픽셀 값 칸은 늘 같은 글자 수 — 값이 생겨도 줄이 밀리지 않는다
        x, y = self._hover
        data = buf.frames.get(self._buffer_index(buf)) if buf.available else None
        rgb: Optional[Tuple[int, int, int]] = None
        if data is not None and x >= 0:
            off = (y * buf.size[0] + x) * 6
            if 0 <= off <= len(data) - 6:
                rgb = struct.unpack_from("<HHH", data, off)
        cc = style.CHANNEL_COLORS
        if rgb is not None:
            pos = f"x {x:>4} y {y:>4}".replace(" ", "&nbsp;")
            vals = [f"{v / 65535:.4f}" for v in rgb]
            tone = style.DIM
        else:
            pos = "x&nbsp;&nbsp;&nbsp;&nbsp;– y&nbsp;&nbsp;&nbsp;&nbsp;–"
            vals = ["&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;–"] * 3
            tone = style.GHOST
        right.append(f'<span style="color:{tone}">{pos}</span>')
        right.append(
            f'<span style="color:{tone}">'
            + " ".join(
                f'<span style="color:{cc[ch]}">{ch}</span> {v}' for ch, v in zip("RGB", vals)
            )
            + "</span>"
        )
        self._info.setText(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f"<td>{_PIXEL_GAP.join(left)}</td>"
            f'<td align="right">{_PIXEL_GAP.join(right)}</td></tr></table>'
        )

    def _sync_header(self) -> None:
        cur = self._bufs[KEY_CUR]
        t = self._task
        parts: List[str] = []
        if self._shot_root is not None:
            proj = (t.get("project_code") or t.get("project_name") or "").strip()
            parts = [x for x in (proj, self._shot_root.parent.name, self._shot_root.name) if x]
        elif (t.get("shot_code") or "").strip():  # 목록에서 막 고른 샷 — 아직 여는 중
            proj = (t.get("project_code") or t.get("project_name") or "").strip()
            parts = [x for x in (proj, str(t["shot_code"]).strip()) if x]
        elif cur.path is not None:
            parts = [cur.path.parent.name, cur.path.stem]
        if parts:
            sep = f' <span style="color:{style.DIM}">/</span> '
            head = [f'<span style="color:{style.DIM}">{escape(p)}</span>' for p in parts[:-1]]
            last = f'<b style="color:{style.TEXT_STRONG}">{escape(parts[-1])}</b>'
            self._crumb.setText(f'<span style="{style.mono()}">{sep.join(head + [last])}</span>')
        else:
            self._crumb.setText(f'<span style="color:{style.DIM}">영상을 열어 주세요</span>')
        step = (t.get("task_content") or "comp").strip()
        self._ver_chip.setText(f"{step} {cur.version_label}".strip() if cur.available else "")
        self._ver_chip.setVisible(cur.available)
        who = (t.get("uploader_name") or t.get("version_uploader_name") or "").strip()
        self._who.setText(who)
        status = (t.get("task_status") or "").strip()
        self._status_lbl.setText(status)
        self._status_lbl.setStyleSheet(f"color: {status_style.text_color(status)};")
        self._status_dot.setVisible(bool(status))
        if status:
            self._status_dot.setPixmap(status_style.chip(status, 16))
        rows = self._drawer.shown_rows()
        idx = next((i for i, r in enumerate(rows) if r.get("task_id") == t.get("task_id")), -1)
        self._pos.setText(f"{idx + 1} / {len(rows)}" if idx >= 0 else "")
        self._btn_prev.setEnabled(idx > 0)
        self._btn_next.setEnabled(0 <= idx < len(rows) - 1)
        self._btn_list.setText(" " + (self._drawer.summary() or "목록"))

    def _sync_all(self) -> None:
        for key, btn in self._buf_btns.items():
            buf = self._bufs[key]
            btn.set_label(buf.button_label())
            btn.setEnabled(buf.available)
            btn.setToolTip(buf.tip())
            btn.setChecked(key == self._shown)
            mark = style.WARN if self._diff and key == self._last_shown else ""
            if self._buf_marks.get(key, "") != mark:
                self._buf_marks[key] = mark
                btn.setStyleSheet(style.segment_style(_SEGMENT_POS[key], mark_color=mark))
        self._btn_diff.setChecked(self._diff)
        for ch, btn in self._chan_btns.items():
            btn.setChecked(ch == self._channel)
        self._btn_lut.setChecked(self._lut_on)
        self._btn_lut.setEnabled(self._lut is not None)
        self._btn_lut.setStyleSheet(style.lut_toggle_style(loaded=self._lut is not None))
        self._btn_lut_pick.setText(
            f"{Path(self._lut_path).stem}  ▾" if self._lut_path else "룩업 고르기  ▾"
        )
        self._sync_fit()
        for tool, btn in self._tool_btns.items():
            btn.setChecked(tool == self._layer.tool())
        for btn, color in zip(self._swatch_btns, self._recent_colors):
            btn.setStyleSheet(style.swatch_style(color, color == self._color))
        for color, btn in self._palette_btns.items():
            btn.setStyleSheet(style.swatch_style(color, color == self._color))
        self._btn_palette.setChecked(self._palette.isVisible())
        self._tool_hint.setText(_TOOL_HINTS.get(self._layer.tool(), ""))
        cur = self._bufs[KEY_CUR]
        self._fps_lbl.setText(f"{self._fps:.3f}" if cur.available else "–")
        self._start_lbl.setText(str(self._frame_start) if cur.available else "–")
        self._end_lbl.setText(str(self._frame_start + self._count - 1) if cur.available else "–")
        self._total_lbl.setText(f"/ {self._count}f" if cur.available else "")
        fail = has_failure(self._checks)
        self._banner.setVisible(fail)
        if fail:
            self._banner.setText("  /  ".join(failure_lines(self._checks)))
            self._banner.adjustSize()
        style.set_icon(self._btn_play, "pause" if self._playing else "play", size=14)
        ready = bool(self._task.get("shot_id")) and cur.available
        self._panel.set_sendable(
            ready and not self._submit_busy,
            "" if ready else "샷그리드 정보가 있는 샷에서만 보낼 수 있습니다",
        )
        self._sync_header()
        self._sync_memo()
        self._sync_view()

    def _place_overlays(self) -> None:
        vw, vh = self._view.width(), self._view.height()
        self._hud.move(10, 8)
        state_y = 8 + (self._btn_exit_full.height() + 6 if self.isFullScreen() else 0)
        self._state.move(max(10, vw - self._state.width() - 10), state_y)
        self._banner.move(max(0, (vw - self._banner.width()) // 2), 36)
        self._pill.adjustSize()
        self._pill.move(
            max(0, (vw - self._pill.width()) // 2), max(0, vh - self._pill.height() - 12)
        )
        self._help.adjustSize()
        self._help.move(
            max(0, (vw - self._help.width()) // 2), max(0, (vh - self._help.height()) // 2)
        )
        self._btn_exit_full.adjustSize()
        self._btn_exit_full.move(max(0, vw - self._btn_exit_full.width() - 10), 8)
        self._palette.adjustSize()
        bx = self._pill.x() + self._btn_palette.x() + self._btn_palette.width() // 2
        self._palette.move(
            max(0, min(vw - self._palette.width(), bx - self._palette.width() // 2)),
            max(0, self._pill.y() - self._palette.height() - 6),
        )
        self._busy.adjustSize()
        self._busy.move(
            max(0, (vw - self._busy.width()) // 2), max(0, (vh - self._busy.height()) // 2)
        )
        for wdg in (
            self._hud,
            self._state,
            self._banner,
            self._pill,
            self._palette,
            self._btn_exit_full,
            self._busy,
            self._help,
        ):
            wdg.raise_()

    def _set_busy(self, title: str, detail: str = "", *, error: bool = False) -> None:
        """뷰어 한가운데의 진행 알림. 빈 글이면 감춘다."""
        if not title:
            self._busy.hide()
            return
        edge = style.FAIL if error else style.EDGE
        self._busy.setStyleSheet(
            f"background: {style.PANEL}; border: 1px solid {edge}; border-radius: 6px; "
            f"padding: 14px 22px;"
        )
        color = style.FAIL if error else style.TEXT_STRONG
        sub_line = (
            f'<br><span style="color:{style.DIM}; font-size:{style.FONT_PX}px">'
            f"{escape(detail)}</span>"
            if detail
            else ""
        )
        self._busy.setText(
            f'<span style="color:{color}; font-size:{style.FONT_PX + 2}px; font-weight:bold">'
            f"{escape(title)}</span>{sub_line}"
        )
        self._busy.show()
        self._place_overlays()

    def _on_hover(self, x: int, y: int) -> None:
        if (x, y) != self._hover:
            self._hover = (x, y)
            self._sync_info()

    # ── 조작 ────────────────────────────────────────────────────

    def _show_buffer(self, key: str) -> None:
        if not self._bufs[key].available:
            self._sync_all()
            return
        if key != self._shown:
            self._last_shown = self._shown
        self._shown = key
        self._diff = False
        self._sync_all()

    def _toggle_diff(self) -> None:
        self._diff = not self._diff
        self._sync_all()

    def _set_channel(self, channel: str) -> None:
        self._channel = CHANNEL_RGB if channel == self._channel else channel
        self._sync_all()

    def _reset_view(self) -> None:
        self._diff = False
        self._channel = CHANNEL_RGB
        self._gain.blockSignals(True)
        self._gamma.blockSignals(True)
        self._gain.setValue(0)
        self._gamma.setValue(0)
        self._gain.blockSignals(False)
        self._gamma.blockSignals(False)
        self._sync_all()

    def _view_fit(self) -> None:
        self._view.fit()
        self._sync_fit()

    def _view_fill(self) -> None:
        self._view.fill()
        self._sync_fit()

    def _sync_fit(self) -> None:
        state = self._view.fit_state()
        self._btn_fit.setChecked(state == "fit")
        self._btn_fill.setChecked(state == "fill")

    def _on_past_frame(self, frame: int) -> None:
        """지난 지적 안의 프레임 번호를 누르면 그 프레임으로 간다."""
        self._pause()
        self._set_index(frame - self._frame_start)

    def _toggle_fullscreen(self) -> None:
        """영상 전체화면 — 영상·그리기 도구·시간 막대만 남기고 나머지 띠와 패널을 감춘다."""
        full = not self.isFullScreen()
        for bar in (self._header_bar, self._view_bar, self._info, self._panel):
            bar.setVisible(not full)
        if full:
            if self._drawer.isVisible():
                self._toggle_drawer()
            self.showFullScreen()
        else:
            self.showNormal()
        self._btn_exit_full.setVisible(full)
        self._btn_full.setChecked(full)
        self._place_overlays()

    def _toggle_help(self) -> None:
        self._help.setVisible(not self._help.isVisible())
        self._place_overlays()

    def _set_tool(self, tool: str) -> None:
        self._palette.hide()
        self._layer.set_tool(tool)
        self._sync_all()

    def _set_color(self, color: str) -> None:
        """그리기 색을 바꾼다. 고른 그림이 있으면 그 그림의 색도 바꾼다."""
        self._color = color
        if color not in self._recent_colors:  # 팔레트에서 고른 새 색 — 띠의 맨 앞 칸으로
            self._recent_colors = [color] + self._recent_colors[:-1]
        self._layer.set_color(color)
        selected = self._layer.selected_id()
        if selected is not None and self._layer.doc().update(selected, color=color):
            self._layer.update()
            self._on_doc_changed()
        self._palette.hide()
        self._sync_all()

    def _toggle_palette(self) -> None:
        self._palette.setVisible(not self._palette.isVisible())
        self._place_overlays()
        self._sync_all()

    def _extend_selected(self) -> None:
        self._layer.extend_selected_to(self.frame_number())

    # ── 룩업 ────────────────────────────────────────────────────

    def _project_key(self) -> str:
        return (self._task.get("project_code") or self._task.get("project_name") or "").strip()

    def _load_project_lut(self) -> None:
        if self._lut is not None:
            return
        path = str(get_confirm_settings()["luts"].get(self._project_key() or "_default") or "")
        if path:
            self._apply_lut_file(path, remember=False)

    def _pick_lut(self) -> None:
        start = str(Path(self._lut_path).parent) if self._lut_path else ""
        path, _ = QFileDialog.getOpenFileName(self, "룩업 파일 고르기", start, "룩업 (*.cube)")
        if path:
            self._apply_lut_file(path, remember=True)

    def _apply_lut_file(self, path: str, *, remember: bool) -> None:
        lut = load_cube(Path(path))
        if lut is None:
            self._panel.set_result(f"룩업을 읽지 못했습니다: {Path(path).name}", False)
            return
        self._lut, self._lut_path, self._lut_on = lut, path, True
        self._view.set_lut(lut)
        if remember:
            luts = dict(get_confirm_settings()["luts"])
            luts[self._project_key() or "_default"] = path
            save_confirm_settings({"luts": luts})
        self._sync_all()

    def _toggle_lut(self) -> None:
        if self._lut is None:
            self._pick_lut()
            return
        self._lut_on = not self._lut_on
        self._sync_all()

    # ── 재생·이동 ────────────────────────────────────────────────

    def _set_index(self, index: int) -> None:
        if self._count <= 0:
            return
        index = max(0, min(self._count - 1, index))
        if index != self._index:
            self._index = index
            self._refresh_view()

    def _on_frame_picked(self, index: int) -> None:
        self._pause()
        self._set_index(index)

    def _on_frame_typed(self) -> None:
        try:
            frame = int(self._frame_edit.text().strip())
        except ValueError:
            frame = self.frame_number()
        self._pause()
        self._set_index(frame - self._frame_start)
        self.setFocus()
        self._sync_labels()

    def _on_scrub_started(self) -> None:
        self._scrub_from = self._index

    def _on_scrub_moved(self, dx: float) -> None:
        """영상을 누른 채 좌우로 끌면 프레임을 넘긴다(RV 처럼). 한 프레임 = 화면 몇 픽셀."""
        if self._count <= 1:
            return
        per_frame = max(_SCRUB_MIN_PX, min(_SCRUB_MAX_PX, self._view.width() / self._count))
        self._pause()
        self._set_index(self._scrub_from + int(dx / per_frame))

    def _step(self, delta: int) -> None:
        self._pause()
        self._set_index(self._index + delta)

    def _go_first(self) -> None:
        self._pause()
        self._set_index(0)

    def _go_last(self) -> None:
        self._pause()
        self._set_index(self._count - 1)

    def _toggle_play(self) -> None:
        if self._playing:
            self._pause()
        elif self._count > 1:
            if self._index >= self._count - 1:
                self._index = 0
            self._playing = True
            self._play_timer.start(max(1, int(round(1000.0 / (self._fps or 24.0)))))
            style.set_icon(self._btn_play, "pause", size=14)

    def _pause(self) -> None:
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            style.set_icon(self._btn_play, "play", size=14)

    def _on_play_tick(self) -> None:
        nxt = self._index + 1
        if nxt >= self._count:
            if not self._loop:
                self._pause()
                return
            nxt = 0
        buf = self._bufs[self._shown]
        if buf.full and buf.frames.get(min(nxt, (buf.frame_count() or self._count) - 1)) is None:
            return  # 아직 메모리에 안 올라온 프레임 — 올라올 때까지 기다린다
        self._index = nxt
        self._refresh_view()

    # ── 그림·메모 ────────────────────────────────────────────────

    def _on_doc_changed(self) -> None:
        self._timeline.set_marks(self._layer.doc().marked_frames())
        self._sync_memo()
        self._draft_timer.start()

    def _sync_memo(self) -> None:
        """화면에 쓴 글을 메모 칸에 그대로 적는다.

        새 글은 끝에 한 줄로 붙이고, 고친 글은 그 줄을 바꾸고, 지운 그림의 줄은 뺀다.
        사용자가 메모 칸에서 그 줄을 직접 고쳐 놨으면 건드리지 않는다.
        """
        doc = self._layer.doc()
        shapes = sorted(doc.shapes(), key=lambda s: (s["frame"], s["id"]))
        texts = {int(s["id"]): s["text"].strip() for s in shapes if (s.get("text") or "").strip()}
        memo = self._panel.memo_text()
        lines = memo.split("\n") if memo else []
        changed = False
        for sid, old in list(self._memo_lines.items()):
            new = texts.get(sid)
            if new == old:
                continue
            if old in lines:
                i = lines.index(old)
                if new is None:
                    del lines[i]
                else:
                    lines[i] = new
            elif new is not None:
                lines.append(new)
            if new is None:
                del self._memo_lines[sid]
            else:
                self._memo_lines[sid] = new
            changed = True
        for sid, text in texts.items():
            if sid not in self._memo_lines:
                lines.append(text)
                self._memo_lines[sid] = text
                changed = True
        if changed:
            self._panel.set_memo_text("\n".join(lines))
        frames = self._attachment_frames()
        self._panel.set_attach_text(
            f"그림 {len(frames)}장 첨부 · 샷 이름·버전·프레임 번호가 찍힘"
            if frames
            else "그림을 그리면 여기 첨부됩니다"
        )

    def _insert_failures(self) -> None:
        for line in failure_lines(self._checks):
            self._panel.append_memo(line)

    def _attachment_frames(self) -> List[int]:
        return self._layer.doc().marked_frames()

    def _draft_path(self) -> Optional[Path]:
        cur = self._bufs[KEY_CUR]
        if cur.path is None:
            return None
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in cur.path.stem)
        return cfg.APP_DIR / "confirm_drafts" / f"{safe}.json"

    def _save_draft(self) -> None:
        path = self._draft_path()
        if path is None:
            return
        doc = self._layer.doc()
        memo = self._panel.memo_text()
        try:
            if doc.is_empty() and not memo.strip():
                if path.is_file():
                    path.unlink()
            else:
                write_json_file(
                    path,
                    {
                        "movie": self._movie,
                        "shapes": doc.to_list(),
                        "memo": memo,
                        "memo_lines": {str(k): v for k, v in self._memo_lines.items()},
                    },
                )
        except OSError as e:
            logger.warning("confirm draft save failed: %s", e)

    def _load_draft(self) -> None:
        path = self._draft_path()
        doc = AnnotationDoc()
        memo, lines = "", {}
        if path is not None:
            data = read_json_file(path, {})
            if isinstance(data, dict):
                doc.load_list(data.get("shapes"))
                memo = str(data.get("memo") or "")
                stored = data.get("memo_lines")
                if isinstance(stored, dict):
                    lines = {int(k): str(v) for k, v in stored.items() if str(k).isdigit()}
        self._memo_lines = lines
        self._panel.set_memo_text(memo)
        self._layer.set_doc(doc)
        self._timeline.set_marks(doc.marked_frames())
        self._sync_memo()

    def _render_note_images(self) -> List[str]:
        """그림을 남긴 프레임마다 노트용 PNG 를 임시 폴더에 만든다."""
        cur = self._bufs[KEY_CUR]
        doc = self._layer.doc()
        out: List[str] = []
        shot = (self._task.get("shot_code") or (cur.path.stem if cur.path else "")).strip()
        for frame in self._attachment_frames():
            data = cur.frames.get(frame - self._frame_start)
            if data is None:
                continue
            img = self._view.render_frame_image(
                data,
                cur.size[0],
                cur.size[1],
                lut_on=self._lut is not None and not self._look_baked(cur),
            )
            if img is None:
                continue
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            p = QPainter(img)
            rect = (0.0, 0.0, float(img.width()), float(img.height()))
            paint_shapes(p, [s for s in doc.shapes() if s["frame"] == frame], rect)
            label = f"{shot}  {cur.version_label}  프레임 {frame}"
            font = p.font()
            font.setBold(True)
            font.setPixelSize(max(14, img.height() // 40))
            p.setFont(font)
            w = p.fontMetrics().horizontalAdvance(label) + 20
            h = p.fontMetrics().height() + 10
            p.fillRect(0, 0, w, h, QColor(0, 0, 0, 200))
            p.setPen(QColor("#ffffff"))
            p.drawText(10, h - 8, label)
            p.end()
            if max(img.width(), img.height()) > _NOTE_IMAGE_MAX_EDGE:
                img = img.scaled(
                    _NOTE_IMAGE_MAX_EDGE,
                    _NOTE_IMAGE_MAX_EDGE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            fd, tmp = tempfile.mkstemp(prefix=f"bpe_confirm_{frame}_", suffix=".png")
            os.close(fd)
            if img.save(tmp, "PNG"):
                out.append(tmp)
        self._refresh_view()
        return out

    # ── 샷그리드 ────────────────────────────────────────────────

    def _fill_work_info(self) -> None:
        t = self._task
        cur = self._bufs[KEY_CUR]
        who = (t.get("uploader_name") or t.get("version_uploader_name") or "").strip()
        meta = " · ".join(x for x in (who, cur.version_label, t.get("task_status") or "") if x)
        self._panel.set_work_info(
            (t.get("vfx_work_order") or "").strip(),
            (t.get("shot_description") or "").strip(),
            meta if t else "샷그리드 정보 없음 — 파일만 열었습니다",
        )

    def _load_sg_context(self) -> None:
        shot_id = self._task.get("shot_id")
        if shot_id is None:
            self._panel.set_past_notes([])
            return
        token = self._load_token
        task_id = self._task.get("task_id")
        self._ensure_status_styles()

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.confirm_context import list_shot_history

            return list_shot_history(get_default_sg(), int(shot_id), task_id=task_id)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, t=token: self._on_notes(r, t))
        w.error.connect(lambda e: logger.warning("confirm: notes load failed: %s", e))
        w.start()
        self._workers.append(w)

    def _on_notes(self, result: object, token: int) -> None:
        if token != self._load_token or self._closed or not isinstance(result, list):
            return
        cur_code = (self._task.get("latest_version_code") or "").strip()
        self._panel.set_past_notes(result, cur_code)

    def _on_past_note(self, note: Dict[str, Any]) -> None:
        """지난 지적을 누르면 — 그 버전(전 버전 판에 있으면)과 지금 버전을 바로 비교하게 한다."""
        code = str(note.get("version_code") or "")
        prev = self._bufs[KEY_PREV]
        if prev.available and prev.path is not None and code and code in prev.path.stem:
            self._last_shown = KEY_CUR
            self._shown = KEY_PREV
            self._diff = False
            self._sync_all()

    def _on_status_requested(self, code: str) -> None:
        if self._submit_busy or not self._task.get("shot_id"):
            return
        self._pending_status = code
        self._pending_left = _SEND_DELAY_SECS
        self._sent_note_id = None
        self._panel.set_result("", True)
        self._show_pending()
        self._send_timer.start()

    def _pending_summary(self) -> str:
        lines = sum(1 for ln in self._panel.memo_text().split("\n") if ln.strip())
        frames = len(self._attachment_frames())
        if not lines and not frames:
            return f"상태만 {self._pending_status} 로 바꿈"
        warn = f" · {self._version_note}" if self._version_note else ""
        return f"노트(메모 {lines}줄, 그림 {frames}장) 보내고 상태 {self._pending_status}{warn}"

    def _show_pending(self) -> None:
        self._panel.set_pending(f"{self._pending_left}초 뒤 실행: {self._pending_summary()}")

    def _on_send_tick(self) -> None:
        self._pending_left -= 1
        if self._pending_left > 0:
            self._show_pending()
            return
        self._send_timer.stop()
        self._panel.set_pending(None)
        code, self._pending_status = self._pending_status, ""
        self._submit(code)

    def _cancel_pending(self) -> None:
        if self._send_timer.isActive():
            self._send_timer.stop()
            self._pending_status = ""
            self._panel.set_pending(None)
            self._panel.set_result("보내기를 취소했습니다", False)

    def _retry_status_only(self) -> None:
        code = self._last_status_code
        if code and self._sent_note_id is not None:
            self._submit(code, existing_note_id=self._sent_note_id)

    def _submit(self, code: str, existing_note_id: Optional[int] = None) -> None:
        t = dict(self._task)
        body = self._panel.memo_text().strip()
        frames = self._attachment_frames() if existing_note_id is None else []
        images = self._render_note_images() if existing_note_id is None else []
        if len(images) < len(frames):
            # 그림을 남긴 프레임이 아직 메모리에 안 올라왔다 — 그림이 빠진 노트를 보내지 않는다
            self._remove_files(images)
            self._panel.set_result(
                f"그림 {len(frames)}장 중 {len(images)}장만 만들어져 보내지 않았습니다. "
                "영상이 다 올라온 뒤 다시 눌러 주세요",
                False,
            )
            return
        self._last_status_code = code
        self._submit_busy = True
        self._panel.set_result("보내는 중…", True)
        self._sync_all()
        cur_code = (t.get("latest_version_code") or "").strip()

        def _work() -> Any:
            from bpe.shotgrid.confirm_submit import (
                addressings_for_confirm,
                note_subject,
                open_submit_session,
                submit_confirm,
            )

            sg, me = open_submit_session()
            return submit_confirm(
                sg,
                project_id=int(t["project_id"]),
                shot_id=int(t["shot_id"]),
                version_id=t.get("latest_version_id"),
                task_id=t.get("task_id"),
                status_code=code,
                status_field=(t.get("status_field") or None),
                subject=note_subject(me, cur_code, (t.get("shot_code") or "").strip()),
                content=body,
                attachment_paths=images,
                author_user=me,
                addressings_to=addressings_for_confirm(t.get("task_assignees")),
                existing_note_id=existing_note_id,
            )

        w = ShotGridWorker(_work)
        w.finished.connect(lambda r, imgs=images: self._on_submitted(r, imgs))
        w.error.connect(lambda e, imgs=images: self._on_submit_error(e, imgs))
        w.start()
        self._workers.append(w)

    @staticmethod
    def _remove_files(paths: List[str]) -> None:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def _on_submit_error(self, msg: str, images: List[str]) -> None:
        self._remove_files(images)
        self._submit_busy = False
        self._panel.set_result(f"보내지 못했습니다: {msg}", False)
        self._sync_all()

    def _on_submitted(self, res: Any, images: List[str]) -> None:
        self._remove_files(images)
        self._submit_busy = False
        parts: List[str] = []
        if res.note_needed:
            if res.note_ok:
                self._sent_note_id = res.note_id
                parts.append(
                    "노트 보냄"
                    if res.attachment_ok
                    else f"노트 보냄(그림 실패: {res.attachment_error})"
                )
                self._memo_lines = {}
                self._panel.clear_memo()
                self._layer.set_doc(AnnotationDoc())
                self._on_doc_changed()
            else:
                parts.append(f"노트 실패: {res.note_error}")
        if res.status_needed:
            if res.status_ok:
                parts.append(f"상태 {self._last_status_code} 로 바꿈")
                self._task["task_status"] = self._last_status_code
            else:
                parts.append(f"상태 실패: {res.status_error}")
        can_retry = bool(res.status_needed and not res.status_ok and res.note_ok)
        self._panel.set_result(
            " · ".join(parts) or "보낼 것이 없습니다", res.all_ok, can_retry=can_retry
        )
        self._fill_work_info()
        self._sync_all()

    # ── 키보드 ───────────────────────────────────────────────────

    def _typing(self) -> bool:
        w = self.focusWidget()
        return isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Escape:
            if self._layer.is_editing_text():
                self._layer.cancel_text_edit()
            elif self._help.isVisible():
                self._toggle_help()
            elif self._palette.isVisible():
                self._toggle_palette()
            elif self._send_timer.isActive():
                self._cancel_pending()
            elif self._drawer.isVisible():
                self._toggle_drawer()
            elif self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.setFocus()
            return
        if self._typing():
            super().keyPressEvent(event)
            return
        # 한글 입력 상태에서도 먹도록 글자 대신 키 자리(가상 키)로 본다.
        vk = event.nativeVirtualKey()
        letter = chr(vk) if 0x41 <= vk <= 0x5A else ""
        if not letter and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            letter = chr(key)
        if ctrl and letter == "Z":
            self._layer.undo()
        elif ctrl and letter == "Y":
            self._layer.redo()
        elif ctrl:
            super().keyPressEvent(event)
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_4:
            self._show_buffer(_BUFFER_DEFS[key - Qt.Key.Key_1][0])
        elif key == Qt.Key.Key_Space:
            self._toggle_play()
        elif key == Qt.Key.Key_Left:
            self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step(1)
        elif key == Qt.Key.Key_Home:
            self._go_first()
        elif key == Qt.Key.Key_End:
            self._go_last()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._layer.delete_selected()
        elif key == Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_Question:
            self._toggle_help()
        elif letter == "D":
            self._toggle_diff()
        elif letter in ("R", "G", "B"):
            self._set_channel({"R": CHANNEL_R, "G": CHANNEL_G, "B": CHANNEL_B}[letter])
        elif letter in ("A", "Y"):
            self._set_channel(CHANNEL_LUMA)
        elif letter == "L":
            self._toggle_lut()
        elif letter == "F":
            self._view_fit()
        elif letter == "H":
            self._view_fill()
        elif letter in ("V", "N", "O", "P", "W", "T"):
            self._set_tool(next(t for t, _i, _l, k in _TOOLS if k == letter))
        else:
            super().keyPressEvent(event)

    # ── 창 수명 ──────────────────────────────────────────────────

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._aumid_applied:
            self._aumid_applied = True
            if sys.platform == "win32":
                from bpe.core.windows_app_id import apply_app_user_model_id_to_hwnd

                apply_app_user_model_id_to_hwnd(int(self.winId()))
            self.setFocus()
        self._place_overlays()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._drawer.isVisible():
            self._place_drawer()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closed = True
        self._pause()
        self._send_timer.stop()
        self._save_draft()
        self._stop_decoders()
        self._drawer.shutdown()
        for buf in self._bufs.values():
            buf.frames = {}
        for w in self._workers:
            try:
                if w.isRunning():
                    w.wait(_WORKER_WAIT_MS)
            except RuntimeError:
                pass
        self._workers.clear()
        super().closeEvent(event)
