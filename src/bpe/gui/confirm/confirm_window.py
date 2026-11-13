"""BPE 컨펌 전용 창 — 누크 없이 쓰는 뷰어 + 그림 메모 + 작업 비하인드.

기존 피드백 탭과 따로 뜨는 독립 창이다. 영상을 프레임 단위로 메모리에 올려 재생하고,
원본·전 버전·지금 버전·편집본을 번호 키로 번갈아 본다.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QImage, QKeyEvent, QPainter, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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
from bpe.core.confirm_annotations import AnnotationDoc, compose_note_body, memo_lines
from bpe.core.confirm_checks import (
    CheckResult,
    check_work_against_reference,
    failure_lines,
    has_failure,
)
from bpe.core.confirm_decode import fit_decode_size, frame_byte_size
from bpe.core.confirm_media import find_shot_media
from bpe.core.confirm_probe import VideoInfo, probe_video
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
from bpe.core.settings import (
    get_confirm_settings,
    get_feedback_frame_start,
    save_confirm_settings,
)
from bpe.gui import theme
from bpe.gui.confirm.annotation_layer import (
    TOOL_ARROW,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_SELECT,
    TOOL_TEXT,
    AnnotationLayer,
    paint_shapes,
)
from bpe.gui.confirm.side_panel import ConfirmSidePanel
from bpe.gui.confirm.timeline import ConfirmTimeline
from bpe.gui.confirm.viewer_gl import SLOT_A, SLOT_B, ConfirmGLView
from bpe.gui.workers.confirm_stream_worker import StreamDecodeWorker
from bpe.gui.workers.sg_worker import ShotGridWorker

logger = get_logger("gui.confirm.window")

KEY_ORG, KEY_PREV, KEY_CUR, KEY_EDIT = "org", "prev", "cur", "edit"
_BUFFER_DEFS: Tuple[Tuple[str, int, str], ...] = (
    (KEY_ORG, 1, "원본"),
    (KEY_PREV, 2, "전 버전"),
    (KEY_CUR, 3, "지금"),
    (KEY_EDIT, 4, "편집본"),
)
_DECODE_ORDER = (KEY_CUR, KEY_PREV, KEY_ORG, KEY_EDIT)
_MAX_W, _MAX_H = 2048, 1556
_ONDEMAND_KEEP = 12
_GAIN_STEPS_PER_STOP = 4
_GAMMA_SCALE = 100
_SEND_DELAY_SECS = 5
_NOTE_IMAGE_MAX_EDGE = 1280
_WORKER_WAIT_MS = 5000
_WARN = "#f0c060"
_VIDEO_FILTER = "영상 (*.mov *.mp4 *.mxf *.mkv *.m4v);;모든 파일 (*)"
_CHANNELS: Tuple[Tuple[str, str], ...] = (
    ("RGB", CHANNEL_RGB),
    ("R", CHANNEL_R),
    ("G", CHANNEL_G),
    ("B", CHANNEL_B),
    ("밝기", CHANNEL_LUMA),
)
_TOOLS: Tuple[Tuple[str, str, str], ...] = (
    (TOOL_SELECT, "선택", "V"),
    (TOOL_RECT, "네모", "N"),
    (TOOL_PEN, "펜", "P"),
    (TOOL_ARROW, "화살표", "W"),
    (TOOL_TEXT, "글씨", "T"),
)
_COLORS = ("#ff5a52", "#f2c94c", "#ffffff", "#4fc3f7")


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

    def button_text(self) -> str:
        return (
            f"{self.number} {self.title}{(' ' + self.version_label) if self.version_label else ''}"
        )


_BASE_BTN = (
    f"QPushButton {{ min-width: 0px; padding: 4px 10px; border: 1px solid {theme.BORDER}; "
    f"border-radius: 3px; background: {theme.INPUT_BG}; color: {theme.TEXT}; }}"
    f"QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}"
    f"QPushButton:disabled {{ color: {theme.TEXT_DIM}; }}"
)


def _btn(text: str, *, checkable: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    b.setStyleSheet(_BASE_BTN)
    return b


def _toggle_style(color: str = "") -> str:
    on = color or theme.ACCENT
    return (
        f"{_BASE_BTN}"
        f"QPushButton:checked {{ border-color: {on}; border-bottom: 3px solid {on}; "
        f"color: #ffffff; }}"
        f"QPushButton:disabled {{ color: {theme.TEXT_DIM}; }}"
    )


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
        self._task: Dict[str, Any] = {}
        self._checks: List[CheckResult] = []
        self._load_token = 0
        self._hover: Tuple[int, int] = (-1, -1)
        self._pending_status = ""
        self._pending_left = 0
        self._sent_note_id: Optional[int] = None
        self._submit_busy = False
        self._diff_note = ""
        self._last_status_code = ""
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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(10, 6, 10, 6)
        head.setSpacing(8)
        self._btn_open = _btn("영상 열기…")
        self._btn_open.clicked.connect(self._pick_file)
        head.addWidget(self._btn_open)
        self._title = QLabel("영상을 열어 주세요")
        self._title.setStyleSheet("font-weight: bold;")
        head.addWidget(self._title, 1)
        self._btn_full = _btn("전체화면", checkable=True, tip="F11")
        self._btn_full.clicked.connect(self._toggle_fullscreen)
        head.addWidget(self._btn_full)
        self._btn_help = _btn("단축키", tip="?")
        self._btn_help.clicked.connect(self._toggle_help)
        head.addWidget(self._btn_help)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addLayout(self._build_bar1())
        left.addLayout(self._build_bar2())

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
            f"background: {theme.SIDEBAR_BG}; color: {theme.TEXT_LABEL}; padding: 3px 10px; "
            f"font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        left.addWidget(self._info)

        self._timeline = ConfirmTimeline()
        self._timeline.frame_picked.connect(self._on_frame_picked)
        left.addWidget(self._timeline)
        left.addLayout(self._build_transport())
        body.addLayout(left, 1)

        self._panel = ConfirmSidePanel()
        self._panel.status_requested.connect(self._on_status_requested)
        self._panel.cancel_requested.connect(self._cancel_pending)
        self._panel.retry_requested.connect(self._retry_status_only)
        self._panel.past_note_clicked.connect(self._on_past_note)
        self._panel.memo_toggled.connect(self._on_memo_toggled)
        self._panel.insert_failures_requested.connect(self._insert_failures)
        from bpe.shotgrid.tasks import BELUCA_TASK_STATUS_PRESETS

        self._panel.set_other_statuses(
            [(c, lbl) for c, lbl in BELUCA_TASK_STATUS_PRESETS if c not in ("retake", "cfrm")]
        )
        body.addWidget(self._panel)
        root.addLayout(body, 1)

    def _build_bar1(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(10, 4, 10, 2)
        row.setSpacing(4)
        self._buf_btns: Dict[str, QPushButton] = {}
        for key, number, _title in _BUFFER_DEFS:
            b = _btn("", checkable=True, tip=f"숫자 키 {number}")
            b.setStyleSheet(_toggle_style())
            b.clicked.connect(lambda _c=False, k=key: self._show_buffer(k))
            self._buf_btns[key] = b
            row.addWidget(b)
        row.addSpacing(10)
        self._btn_diff = _btn("차이", checkable=True, tip="지금 보는 판 − 직전에 본 판 (D)")
        self._btn_diff.setStyleSheet(_toggle_style(_WARN))
        self._btn_diff.clicked.connect(self._toggle_diff)
        row.addWidget(self._btn_diff)
        row.addSpacing(10)
        self._chan_btns: Dict[str, QPushButton] = {}
        colors = {CHANNEL_R: "#ff7b7b", CHANNEL_G: "#7fcf7f", CHANNEL_B: "#7fb0ff"}
        for label, ch in _CHANNELS:
            b = _btn(label, checkable=True)
            b.setStyleSheet(_toggle_style(colors.get(ch, "")))
            b.clicked.connect(lambda _c=False, c=ch: self._set_channel(c))
            self._chan_btns[ch] = b
            row.addWidget(b)
        row.addStretch(1)
        self._btn_fit = _btn("화면 맞춤", tip="F")
        self._btn_fit.clicked.connect(self._view_fit)
        row.addWidget(self._btn_fit)
        self._btn_fill = _btn("꽉 채움", tip="H")
        self._btn_fill.clicked.connect(self._view_fill)
        row.addWidget(self._btn_fill)
        return row

    def _build_bar2(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(10, 2, 10, 6)
        row.setSpacing(6)
        self._btn_gain = _btn("게인", tip="누르면 1.00 으로")
        self._btn_gain.setFlat(True)
        self._btn_gain.clicked.connect(lambda: self._gain.setValue(0))
        row.addWidget(self._btn_gain)
        self._gain = QSlider(Qt.Orientation.Horizontal)
        self._gain.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._gain.setRange(-4 * _GAIN_STEPS_PER_STOP, 6 * _GAIN_STEPS_PER_STOP)
        self._gain.setFixedWidth(160)
        self._gain.valueChanged.connect(self._sync_view)
        row.addWidget(self._gain)
        self._gain_val = QLabel("1.00")
        self._gain_val.setFixedWidth(46)
        row.addWidget(self._gain_val)
        self._btn_gamma = _btn("감마", tip="누르면 1.00 으로")
        self._btn_gamma.setFlat(True)
        self._btn_gamma.clicked.connect(lambda: self._gamma.setValue(_GAMMA_SCALE))
        row.addWidget(self._btn_gamma)
        self._gamma = QSlider(Qt.Orientation.Horizontal)
        self._gamma.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._gamma.setRange(20, 400)
        self._gamma.setValue(_GAMMA_SCALE)
        self._gamma.setFixedWidth(160)
        self._gamma.valueChanged.connect(self._sync_view)
        row.addWidget(self._gamma)
        self._gamma_val = QLabel("1.00")
        self._gamma_val.setFixedWidth(46)
        row.addWidget(self._gamma_val)
        row.addSpacing(10)
        self._btn_lut = _btn("LUT", checkable=True, tip="룩업 켜고 끄기 (L)")
        self._btn_lut.setStyleSheet(_toggle_style())
        self._btn_lut.clicked.connect(self._toggle_lut)
        row.addWidget(self._btn_lut)
        self._btn_lut_pick = _btn("룩업 고르기…")
        self._btn_lut_pick.clicked.connect(self._pick_lut)
        row.addWidget(self._btn_lut_pick)
        self._btn_reset = _btn("보기 원래대로")
        self._btn_reset.setStyleSheet(
            f"min-width: 0px; color: {_WARN}; border: 1px solid {_WARN}; padding: 4px 10px;"
        )
        self._btn_reset.clicked.connect(self._reset_view)
        row.addWidget(self._btn_reset)
        row.addStretch(1)
        return row

    def _build_overlays(self) -> None:
        """뷰어 위에 뜨는 글자·도구 띠(그리기 층보다 위)."""
        mono = "font-family: Consolas, monospace;"
        self._hud = QLabel("", self._view)
        self._hud.setStyleSheet(f"background: #000000; color: #e6e6e6; padding: 2px 6px; {mono}")
        self._hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._state = QLabel("", self._view)
        self._state.setStyleSheet(f"background: #000000; color: {_WARN}; padding: 2px 6px;")
        self._state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._banner = QLabel("", self._view)
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner.setStyleSheet(
            f"background: {theme.ERROR}; color: #ffffff; font-weight: bold; padding: 6px 14px; "
            f"font-size: {theme.FONT_SIZE + 2}px;"
        )
        self._banner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._banner.hide()
        self._help = QLabel(self._help_text(), self._view)
        self._help.setStyleSheet(
            f"background: {theme.PANEL_BG}; color: {theme.TEXT}; padding: 14px 18px; "
            f"border: 1px solid {theme.BORDER};"
        )
        self._help.hide()

        self._pill = QFrame(self._view)
        self._pill.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL_BG}; border: 1px solid {theme.BORDER}; "
            f"border-radius: 6px; }}"
        )
        prow = QHBoxLayout(self._pill)
        prow.setContentsMargins(8, 4, 8, 4)
        prow.setSpacing(3)
        self._tool_btns: Dict[str, QPushButton] = {}
        for tool, label, key in _TOOLS:
            b = _btn(label, checkable=True, tip=f"{label} ({key})")
            b.setStyleSheet(_toggle_style())
            b.clicked.connect(lambda _c=False, t=tool: self._set_tool(t))
            self._tool_btns[tool] = b
            prow.addWidget(b)
        prow.addSpacing(6)
        self._color_btns: Dict[str, QPushButton] = {}
        for color in _COLORS:
            b = _btn("")
            b.setFixedSize(20, 20)
            b.clicked.connect(lambda _c=False, c=color: self._set_color(c))
            self._color_btns[color] = b
            prow.addWidget(b)
        prow.addSpacing(6)
        for label, slot, tip in (
            ("되돌리기", self._layer.undo, "Ctrl+Z"),
            ("다시", self._layer.redo, "Ctrl+Y"),
            ("지우기", self._layer.delete_selected, "Delete — 고른 그림 하나"),
            ("여기까지", self._extend_selected, "고른 그림을 지금 프레임까지 이어지는 구간으로"),
        ):
            b = _btn(label, tip=tip)
            b.clicked.connect(lambda _c=False, f=slot: f())
            prow.addWidget(b)
        self._color = _COLORS[0]
        self._view.view_changed.connect(self._place_overlays)

    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(10, 2, 10, 8)
        row.setSpacing(4)
        self._range_lbl = QLabel("")
        self._range_lbl.setStyleSheet(f"color: {theme.TEXT_LABEL};")
        row.addWidget(self._range_lbl, 1)
        for label, slot, tip in (
            ("|◀", self._go_first, "Home"),
            ("◀", lambda: self._step(-1), "←"),
        ):
            b = _btn(label, tip=tip)
            b.clicked.connect(lambda _c=False, f=slot: f())
            row.addWidget(b)
        self._btn_play = _btn("재생", tip="Space")
        self._btn_play.setMinimumWidth(70)
        self._btn_play.clicked.connect(self._toggle_play)
        row.addWidget(self._btn_play)
        for label, slot, tip in (
            ("▶", lambda: self._step(1), "→"),
            ("▶|", self._go_last, "End"),
        ):
            b = _btn(label, tip=tip)
            b.clicked.connect(lambda _c=False, f=slot: f())
            row.addWidget(b)
        self._btn_loop = _btn("반복", checkable=True)
        self._btn_loop.setChecked(True)
        self._btn_loop.setStyleSheet(_toggle_style())
        self._btn_loop.clicked.connect(lambda c: setattr(self, "_loop", bool(c)))
        row.addWidget(self._btn_loop)
        row.addStretch(1)
        self._frame_edit = QLineEdit()
        self._frame_edit.setFixedWidth(76)
        self._frame_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._frame_edit.setStyleSheet("min-width: 0px; padding: 3px 4px; font-weight: bold;")
        self._frame_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_edit.returnPressed.connect(self._on_frame_typed)
        row.addWidget(self._frame_edit)
        return row

    @staticmethod
    def _help_text() -> str:
        return (
            "<b>단축키</b><br>"
            "1 · 2 · 3 · 4 — 원본 / 전 버전 / 지금 / 편집본<br>"
            "D — 차이 (지금 보는 판 − 직전에 본 판)<br>"
            "R · G · B · Y — 채널 / 밝기만 (한 번 더 누르면 RGB)<br>"
            "L — 룩업 켜고 끄기<br>"
            "F — 화면 맞춤 &nbsp; H — 꽉 채움 &nbsp; 휠 — 확대 &nbsp; Alt+끌기 — 이동<br>"
            "Space — 재생/멈춤 &nbsp; ← → — 한 프레임 &nbsp; Home · End — 처음/끝<br>"
            "V 선택 · N 네모 · P 펜 · W 화살표 · T 글씨<br>"
            "Ctrl+Z / Ctrl+Y — 되돌리기 / 다시 &nbsp; Delete — 고른 그림 지우기<br>"
            "F11 — 전체화면 &nbsp; Esc — 닫기/취소 &nbsp; ? — 이 표"
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
        self._task = dict(task or {})
        self._sent_note_id = None
        for buf in self._bufs.values():
            buf.path, buf.info, buf.size, buf.frames = None, None, (0, 0), {}
            buf.full, buf.lut_baked, buf.version_label, buf.error = False, False, "", ""
        self._index, self._count = 0, 0
        self._checks = []
        self._shown, self._last_shown, self._diff = KEY_CUR, KEY_ORG, False
        self._layer.set_doc(AnnotationDoc())
        self._layer.set_ghosts([])
        self._timeline.set_range(self._frame_start, 0)
        self._title.setText(f"{Path(movie).name} — 재료 찾는 중…")
        self._panel.set_result("", True)
        self._sync_all()

        def _prepare() -> Dict[str, Any]:
            media = find_shot_media(Path(movie))
            paths = {
                KEY_CUR: media.current.path if media.current else None,
                KEY_PREV: media.previous.path if media.previous else None,
                KEY_ORG: media.org,
                KEY_EDIT: media.edit,
            }
            infos = {k: (probe_video(str(p)) if p else None) for k, p in paths.items()}
            return {"media": media, "paths": paths, "infos": infos}

        w = ShotGridWorker(_prepare)
        w.finished.connect(lambda r, t=token: self._on_prepared(r, t))
        w.error.connect(lambda e, t=token: self._on_prepare_failed(e, t))
        w.start()
        self._workers.append(w)

    def _on_prepare_failed(self, msg: str, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        self._title.setText(f"영상을 열지 못했습니다: {msg}")

    def _on_prepared(self, result: object, token: int) -> None:
        if token != self._load_token or self._closed or not isinstance(result, dict):
            return
        media = result["media"]
        paths: Dict[str, Optional[Path]] = result["paths"]
        infos: Dict[str, Optional[VideoInfo]] = result["infos"]
        cur_info = infos.get(KEY_CUR)
        if cur_info is None:
            self._title.setText(f"{Path(self._movie).name} — 영상 규격을 읽지 못했습니다")
            return
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

        ref_key = KEY_EDIT if self._bufs[KEY_EDIT].info else KEY_ORG
        self._checks = check_work_against_reference(
            cur_info,
            self._bufs[ref_key].info,
            self._bufs[ref_key].title,
            compare_resolution=ref_key == KEY_EDIT,
        )
        self._panel.set_checks(self._checks)
        self._timeline.set_range(self._frame_start, self._count)
        self._last_shown = KEY_ORG if self._bufs[KEY_ORG].available else KEY_PREV
        self._load_draft()
        self._load_project_lut()
        self._fill_work_info()
        self._decode_queue = [
            k for k in _DECODE_ORDER if self._bufs[k].available and self._bufs[k].full
        ]
        self._start_next_decode()
        self._sync_all()
        self._load_sg_context()

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
            for old in sorted(buf.frames, key=lambda i: abs(i - self._index), reverse=True)[
                : len(buf.frames) - _ONDEMAND_KEEP
            ]:
                buf.frames.pop(old, None)
        if key == KEY_CUR:
            self._timeline.add_cached(index)
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
        return self._gamma.value() / _GAMMA_SCALE

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
                self._diff_note = "화면 크기가 달라 차이를 볼 수 없음"
            else:
                self._view.set_image(SLOT_B, other_data, other.size[0], other.size[1])
                mode = VIEW_MODE_DIFF
        self._view.set_image(SLOT_A, data, buf.size[0], buf.size[1])
        self._view.set_view(
            gain=self._gain_value(),
            gamma=self._gamma_value(),
            mode=mode,
            channel=self._channel,
            lut_on=self._lut_on and self._lut is not None and not buf.lut_baked,
        )
        self._layer.set_frame(self.frame_number())
        self._sync_labels()

    def _sync_view(self) -> None:
        self._gain_val.setText(f"{self._gain_value():.2f}")
        self._gamma_val.setText(f"{self._gamma_value():.2f}")
        self._refresh_view()

    def _view_changes(self) -> List[str]:
        out: List[str] = []
        if self._diff:
            a, b = self._bufs[self._shown].number, self._bufs[self._last_shown].number
            out.append(f"차이 {a}−{b}")
        if self._channel != CHANNEL_RGB:
            out.append(next(lbl for lbl, c in _CHANNELS if c == self._channel) + " 채널")
        if abs(self._gain_value() - 1.0) > 1e-6:
            out.append(f"게인 {self._gain_value():.2f}")
        if abs(self._gamma_value() - 1.0) > 1e-6:
            out.append(f"감마 {self._gamma_value():.2f}")
        return out

    def _sync_labels(self) -> None:
        buf = self._bufs[self._shown]
        name = buf.path.stem if buf.path else ""
        loading = "" if buf.frames.get(self._buffer_index(buf)) is not None else "  올리는 중…"
        self._hud.setText(f"{buf.number} {buf.title}  {name}  {self.frame_number()}{loading}")
        self._hud.adjustSize()
        changes = self._view_changes()
        notes = list(changes)
        if self._diff_note:
            notes.append(self._diff_note)
        if self._lut_on and buf.lut_baked:
            notes.append("룩업이 이미 입혀진 파일 — 룩업 안 씌움")
        cur = self._bufs[KEY_CUR]
        if buf.key != KEY_CUR and buf.info and cur.info:
            if (buf.info.width * cur.info.height) != (cur.info.width * buf.info.height):
                notes.append(f"화면 비율이 작업본과 다름 ({buf.info.width}×{buf.info.height})")
        self._state.setText("보는 중: " + " · ".join(notes) if notes else "")
        self._state.setVisible(bool(notes))
        self._state.adjustSize()
        self._btn_reset.setVisible(bool(changes))
        self._timeline.set_current(self._index)
        if not self._frame_edit.hasFocus():
            self._frame_edit.setText(str(self.frame_number()))
        self._place_overlays()
        self._sync_info()

    def _sync_info(self) -> None:
        colors = {"pass": theme.SUCCESS, "fail": theme.ERROR}
        parts = [
            f'<span style="color:{colors.get(r.state, theme.TEXT_LABEL)}">{r.message}</span>'
            for r in self._checks
        ]
        buf = self._bufs[self._shown]
        if buf.info:
            i = buf.info
            fps = f"{i.fps:.3f}" if i.fps else "?"
            parts.append(f"{i.width}×{i.height} · {i.codec} {i.profile} · {fps} · {i.pix_fmt}")
        x, y = self._hover
        data = buf.frames.get(self._buffer_index(buf)) if buf.available else None
        if data is not None and x >= 0:
            off = (y * buf.size[0] + x) * 6
            if 0 <= off <= len(data) - 6:
                r, g, b = struct.unpack_from("<HHH", data, off)
                parts.append(
                    f"x {x} y {y} &nbsp; "
                    f'<span style="color:#ff7b7b">R</span> {r / 65535:.4f} '
                    f'<span style="color:#7fcf7f">G</span> {g / 65535:.4f} '
                    f'<span style="color:#7fb0ff">B</span> {b / 65535:.4f}'
                )
        self._info.setText(" &nbsp;·&nbsp; ".join(parts))

    def _sync_all(self) -> None:
        for key, btn in self._buf_btns.items():
            buf = self._bufs[key]
            btn.setText(buf.button_text() if buf.available else f"{buf.number} {buf.title} 없음")
            btn.setEnabled(buf.available)
            btn.setChecked(key == self._shown and not self._diff)
        self._btn_diff.setChecked(self._diff)
        for ch, btn in self._chan_btns.items():
            btn.setChecked(ch == self._channel)
        self._btn_lut.setChecked(self._lut_on)
        self._btn_lut.setEnabled(self._lut is not None)
        self._btn_lut_pick.setText(
            f"룩업: {Path(self._lut_path).name}" if self._lut_path else "룩업 고르기…"
        )
        for tool, btn in self._tool_btns.items():
            btn.setChecked(tool == self._layer.tool())
        for color, btn in self._color_btns.items():
            edge = "#ffffff" if color == self._color else theme.BORDER
            btn.setStyleSheet(
                f"min-width: 0px; padding: 0px; background: {color}; border: 2px solid {edge};"
            )
        cur = self._bufs[KEY_CUR]
        if cur.available:
            shot = (self._task.get("shot_code") or "").strip()
            self._title.setText(
                " · ".join(x for x in (shot, cur.path.name if cur.path else "") if x)
            )
            self._range_lbl.setText(
                f"{self._fps:.3f} fps · {self._frame_start} – "
                f"{self._frame_start + self._count - 1} · {self._count} 프레임"
            )
        fail = has_failure(self._checks)
        self._banner.setVisible(fail)
        if fail:
            self._banner.setText("  /  ".join(failure_lines(self._checks)))
            self._banner.adjustSize()
        self._btn_play.setText("멈춤" if self._playing else "재생")
        ready = bool(self._task.get("shot_id")) and cur.available
        self._panel.set_sendable(
            ready and not self._submit_busy,
            "" if ready else "샷그리드 정보가 있는 샷에서만 보낼 수 있습니다",
        )
        self._sync_memo()
        self._refresh_view()

    def _place_overlays(self) -> None:
        vw, vh = self._view.width(), self._view.height()
        self._hud.move(8, 8)
        self._state.move(max(8, vw - self._state.width() - 8), 8)
        self._banner.move(max(0, (vw - self._banner.width()) // 2), 40)
        self._pill.adjustSize()
        self._pill.move(
            max(0, (vw - self._pill.width()) // 2), max(0, vh - self._pill.height() - 12)
        )
        self._help.adjustSize()
        self._help.move(
            max(0, (vw - self._help.width()) // 2), max(0, (vh - self._help.height()) // 2)
        )
        for wdg in (self._hud, self._state, self._banner, self._pill, self._help):
            wdg.raise_()

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
        self._gamma.setValue(_GAMMA_SCALE)
        self._gain.blockSignals(False)
        self._gamma.blockSignals(False)
        self._sync_view()
        self._sync_all()

    def _view_fit(self) -> None:
        self._view.fit()

    def _view_fill(self) -> None:
        self._view.fill()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._panel.show()
        else:
            self._panel.hide()
            self.showFullScreen()
        self._btn_full.setChecked(self.isFullScreen())

    def _toggle_help(self) -> None:
        self._help.setVisible(not self._help.isVisible())
        self._place_overlays()

    def _set_tool(self, tool: str) -> None:
        self._layer.set_tool(tool)
        self._sync_all()

    def _set_color(self, color: str) -> None:
        self._color = color
        self._layer.set_color(color)
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
            self._btn_play.setText("멈춤")

    def _pause(self) -> None:
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            self._btn_play.setText("재생")

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
        doc = self._layer.doc()
        self._panel.set_memo(memo_lines(doc))
        frames = self._attachment_frames()
        self._panel.set_attach_text(
            f"그림 {len(frames)}장 첨부 · 샷 이름·버전·프레임 번호가 찍힘"
            if frames
            else "그림을 그리면 여기 첨부됩니다"
        )

    def _on_memo_toggled(self, shape_id: int, on: bool) -> None:
        self._layer.doc().update(shape_id, in_memo=on)
        self._on_doc_changed()

    def _insert_failures(self) -> None:
        for line in failure_lines(self._checks):
            self._panel.append_extra(line)

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
        try:
            if doc.is_empty():
                if path.is_file():
                    path.unlink()
            else:
                write_json_file(path, {"movie": self._movie, "shapes": doc.to_list()})
        except OSError as e:
            logger.warning("confirm draft save failed: %s", e)

    def _load_draft(self) -> None:
        path = self._draft_path()
        doc = AnnotationDoc()
        if path is not None:
            data = read_json_file(path, {})
            if isinstance(data, dict):
                doc.load_list(data.get("shapes"))
        self._layer.set_doc(doc)
        self._timeline.set_marks(doc.marked_frames())

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
                data, cur.size[0], cur.size[1], lut_on=self._lut is not None and not cur.lut_baked
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
        if not t:
            self._panel.set_work_info("샷그리드 정보 없음 — 파일만 열었습니다")
            return
        lines = []
        order = (t.get("vfx_work_order") or "").strip()
        lines.append("<b>워크 오더</b><br>" + (order.replace("\n", "<br>") if order else "없음"))
        desc = (t.get("shot_description") or "").strip()
        if desc:
            lines.append("<b>샷 설명</b><br>" + desc.replace("\n", "<br>"))
        who = (t.get("version_uploader_name") or "").strip()
        meta = " · ".join(
            x for x in (who, t.get("latest_version_code") or "", t.get("task_status") or "") if x
        )
        if meta:
            lines.append(meta)
        self._panel.set_work_info("<br><br>".join(lines))

    def _load_sg_context(self) -> None:
        shot_id = self._task.get("shot_id")
        if shot_id is None:
            self._panel.set_past_notes([])
            return
        token = self._load_token

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.notes import list_notes_for_shots

            return list_notes_for_shots(get_default_sg(), [int(shot_id)], days_back=0, limit=250)

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
        doc = self._layer.doc()
        lines = sum(1 for _i, _t, on in memo_lines(doc) if on)
        extra = bool(self._panel.extra_text().strip())
        frames = len(self._attachment_frames())
        if not lines and not extra and not frames:
            return f"상태만 {self._pending_status} 로 바꿈"
        return f"노트(메모 {lines}줄, 그림 {frames}장) 보내고 상태 {self._pending_status}"

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
        doc = self._layer.doc()
        body = compose_note_body(doc, self._panel.extra_text())
        images = self._render_note_images() if existing_note_id is None else []
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
                self._layer.set_doc(AnnotationDoc())
                self._on_doc_changed()
                self._panel.clear_extra()
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
            elif self._send_timer.isActive():
                self._cancel_pending()
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
        elif letter == "Y":
            self._set_channel(CHANNEL_LUMA)
        elif letter == "L":
            self._toggle_lut()
        elif letter == "F":
            self._view_fit()
        elif letter == "H":
            self._view_fill()
        elif letter in ("V", "N", "P", "W", "T"):
            self._set_tool(next(t for t, _l, k in _TOOLS if k == letter))
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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closed = True
        self._pause()
        self._send_timer.stop()
        self._save_draft()
        self._stop_decoders()
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
