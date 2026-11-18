"""BPE 컨펌 전용 창 — 누크 없이 쓰는 뷰어 + 그림 메모 + 작업 비하인드.

기존 피드백 탭과 따로 뜨는 독립 창이다. 영상을 프레임 단위로 메모리에 올려 재생하고,
원본·전 버전·지금 버전·편집본을 번호 키로 번갈아 본다. 모양은 ``style.py``(시안 2판).
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import sys
import tempfile
import time
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QFileInfo, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QKeyEvent,
    QPainter,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
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
from bpe.core.confirm_annotations import (
    SOURCE_EDIT,
    SOURCE_PLATE,
    AnnotationDoc,
    replace_memo_block,
    source_of,
)
from bpe.core.confirm_checks import (
    STATE_FAIL,
    STATE_PASS,
    CheckResult,
    basis_text,
    check_work_against_reference,
    failure_lines,
    has_failure,
    short_decode_message,
)
from bpe.core.confirm_decode import (
    RESAMPLE_LINEAR_22,
    RESAMPLE_LINEAR_709,
    RESAMPLE_PLAIN,
    ffmpeg_has_filter,
    fit_decode_size,
    frame_byte_size,
)
from bpe.core.confirm_guide_note import stage_annot_files
from bpe.core.confirm_list import (
    MODE_ANNOTATION,
    MODE_CONFIRM,
    annotation_status_text,
    annotation_subtitle,
    row_ident,
)
from bpe.core.confirm_look import judge_look, sample_grid
from bpe.core.confirm_media import (
    find_org,
    find_plate_media,
    find_shot_media,
    parse_version,
    quick_version_movie,
    reference_sources,
    usual_shot_root,
)
from bpe.core.confirm_probe import VideoInfo, codec_label, container_shortfall, probe_video
from bpe.core.confirm_sequence import (
    SEQ_BUDGET_SHARE,
    SEQ_MIN_CUTS,
    locate,
    next_position,
    order_rows,
    position,
    total_frames,
)
from bpe.core.confirm_shot_text import (
    KIND_LABELS,
    KIND_ROW_KEYS,
    KINDS,
    clean_text,
    same_text,
)
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
    CURVE_GAMMA22,
    CURVE_REC709,
    VIEW_MODE_A,
    VIEW_MODE_DIFF,
    slate_bar,
)
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.lut_cube import CubeLut, load_cube
from bpe.core.mov_colorspace import DISPLAY_NAME, GAMMA, REC709, inspect_mov_color
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
from bpe.gui.confirm.ref_frame_dialog import RefFrameDialog
from bpe.gui.confirm.sequence_player import SequencePlayer, prepare_cuts
from bpe.gui.confirm.sequence_strip import SequenceStrip
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
_BUFFER_TITLES = {k: t for k, _n, t in _BUFFER_DEFS}
# Annotation 모드: 작업본이 없는 샷이라 원본을 「지금 보는 판」 자리에 올린다
_ANNOTATION_KEYS = (KEY_CUR, KEY_EDIT)
_ANNOTATION_PLATE_TITLE = "ORG plate"
_MAX_W, _MAX_H = 2048, 1556
_ONDEMAND_KEEP = 12
_GAIN_STEPS_PER_STOP = 4
_GAIN_STOPS = 5
_GAMMA_STEPS = 100  # 막대 한쪽 끝까지의 칸 수
_GAMMA_SPAN = 4.0  # 막대 끝의 감마 배수(1/4 ~ 4)
_SEND_DELAY_SECS = 3
_NOTE_IMAGE_MAX_EDGE = 1280
_NOTE_IMAGE_NOTES = 40  # 그림을 찾아볼 노트 수(최근 것부터)
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
            (("Shift+L",), "지금 보는 판만 룩업 씌우기 / 빼기"),
            (("F", "H"), "Fit / Fill"),
            (("S",), "슬레이트 가림 켜고 끄기 (편집본과 같은 2:1)"),
            (("PgUp", "PgDn"), "이전 샷 / 다음 샷"),
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
            (("이어 재생",), "목록의 「이어 보기」로 컷을 골라 재생 · 멈추면 그 컷이 열림"),
        ),
    ),
    (
        "그리기",
        (
            (("V", "N", "O", "P", "W", "T"), "선택 / 네모 / 원 / 펜 / 화살표 / 글씨"),
            (("Ctrl+Z", "Ctrl+Y"), "되돌리기 / 다시"),
            (("Delete",), "고른 그림 지우기"),
            (("Enter",), "글씨 확정"),
            (("Shift+Enter", "Alt+Enter"), "글씨 줄 바꿈"),
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
    TOOL_RECT: "끌어서 네모",
    TOOL_ELLIPSE: "끌어서 원",
    TOOL_PEN: "펜 · 자유롭게 그리기",
    TOOL_ARROW: "끌어서 화살표",
    TOOL_TEXT: "눌러서 글씨 쓰기 → Enter",
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
        self.resample = RESAMPLE_PLAIN  # 크기를 줄이는 방법(원본만 줄일 때는 누크식 선형)
        self.version_label = ""
        self.error = ""
        # 다 풀었는데 그림이 모자라게 끝난 자리(0부터 세는 번호) — 파일이 잘렸거나 깨졌다
        self.short_at: Optional[int] = None

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


_STATUS_FLASH_MS = 1500  # 보낸 뒤 머리 줄 상태 칸을 강조해 두는 시간
_APP_ICON_PX = 18  # 색이 있는 프로그램 아이콘(탐색기·샷그리드)은 선 그림보다 조금 크게


def _explorer_icon() -> QIcon:
    """윈도우 탐색기 아이콘(노란 폴더). 못 읽으면 빈 아이콘 — 부르는 쪽이 선 그림을 그대로 둔다."""
    if sys.platform != "win32":
        return QIcon()
    exe = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "explorer.exe"
    provider = QFileIconProvider()
    try:
        if exe.is_file():
            icon = provider.icon(QFileInfo(str(exe)))
            if not icon.isNull():
                return icon
    except OSError:
        pass
    return provider.icon(QFileIconProvider.IconType.Folder)


def _shotgrid_icon() -> QIcon:
    """내 작업 탭의 「ShotGrid에서 열기」 버튼과 같은 그림. 파일이 없으면 빈 아이콘."""
    from bpe.gui.shotgrid_open_shot import shotgrid_open_shot_icon_png_path

    png = shotgrid_open_shot_icon_png_path()
    return QIcon(str(png)) if png.is_file() else QIcon()


def _use_app_icon(button: QPushButton, icon: QIcon) -> None:
    """프로그램 아이콘이 있으면 선 그림 대신 쓴다(없으면 그대로)."""
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(_APP_ICON_PX, _APP_ICON_PX))


def _same_file(a: str, b: str) -> bool:
    """경로 글 두 개가 같은 파일을 가리키나(빗금 방향·대소문자 차이는 무시)."""
    if not a or not b:
        return False
    return a.replace("\\", "/").lower() == b.replace("\\", "/").lower()


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


def _resolve_task_movie(row: Dict[str, Any]) -> str:
    """목록의 한 줄(샷)에서 그 최신 버전 영상 파일을 서버에서 찾는다(뒤에서 돈다)."""
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


def _resolve_plate_movie(row: Dict[str, Any]) -> str:
    """목록의 한 줄(샷)에서 그 샷의 원본(ORG plate) 영상을 서버에서 찾는다(뒤에서 돈다)."""
    from bpe.core.feedback_project_paths import effective_project_for_paths
    from bpe.core.nuke_render_paths import normalize_path_str

    shot_root = _find_shot_root(effective_project_for_paths(row), str(row.get("shot_code") or ""))
    plate = find_org(shot_root) if shot_root is not None else None
    return normalize_path_str(str(plate)) if plate is not None else ""


def _find_shot_root(project: str, shot: str) -> Optional[Path]:
    """프로젝트 폴더 이름과 샷 이름으로 서버의 샷 폴더를 찾는다(뒤에서 돈다)."""
    from bpe.core.nk_finder import _resolve_shot_root, find_server_root_auto
    from bpe.core.nuke_render_paths import normalize_path_str

    root = (os.environ.get("BPE_FEEDBACK_SERVER_ROOT") or "").strip()
    if not root:
        auto = find_server_root_auto(project)
        root = str(auto) if auto else (os.environ.get("BPE_SERVER_ROOT") or "").strip()
    root = normalize_path_str(root).strip() if root else ""
    shot_root = usual_shot_root(root, project, shot)  # 늘 있는 자리부터(넓게 찾기는 몇 초 걸림)
    if shot_root is None and root and shot:
        shot_root = _resolve_shot_root(root, project, shot)
    return shot_root


def _find_ref_sources(project: str, shot: str) -> List[Dict[str, Any]]:
    """다른 샷을 참고 그림으로 쓸 때 고를 영상들(최신 작업본·원본·편집본)과 프레임 수."""
    shot_root = _find_shot_root(project, shot.strip())
    out: List[Dict[str, Any]] = []
    for label, path in reference_sources(shot_root) if shot_root is not None else []:
        info = probe_video(str(path))
        frames = (info.frame_count or 1) if info is not None else 1
        out.append({"label": label, "path": str(path), "frames": frames})
    return out


def _prepare_media(
    movie: str, project: str, picked: Dict[str, Any], annotation: bool = False
) -> Dict[str, Any]:
    """작업본 영상에서 같은 샷의 재료·규격·검사 기준(프리셋)을 모은다(뒤에서 돈다).

    *annotation* 이면 *movie* 는 원본(ORG plate) — 작업본 없이 원본과 편집본만 올린다.
    """
    media = find_plate_media(Path(movie)) if annotation else find_shot_media(Path(movie))
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
    plate_path = media.current.path if annotation and media.current else media.org
    color = inspect_mov_color(plate_path).result if plate_path else None
    ffmpeg = resolve_ffmpeg()
    standards = {n: load_standard(n) for n in names} if len(names) > 1 else {}
    if len(names) > 1:
        cur = infos.get(KEY_CUR)
        size = (cur.width, cur.height) if cur and cur.width and cur.height else None
        if annotation:  # 원본의 크기는 납품 크기가 아니다 — 플레이트 색으로만 고른다
            size = None
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
        "plate_color": color,
        "zscale": bool(ffmpeg) and ffmpeg_has_filter(str(ffmpeg), "zscale"),
    }


def _prepare_sequence(rows: List[Dict[str, Any]], picked: Dict[str, Any]) -> Dict[str, Any]:
    """이어 볼 컷들의 영상·규격을 찾고, 첫 컷으로 검사 기준(프리셋·룩업)을 정한다(뒤에서 돈다)."""
    found = prepare_cuts(rows, _resolve_task_movie)
    cuts = found["cuts"]
    first: Optional[Dict[str, Any]] = None
    if cuts:
        row = cuts[0].row
        project = (row.get("project_code") or row.get("project_name") or "").strip()
        first = _prepare_media(cuts[0].movie, project, picked)
    return {"cuts": cuts, "skipped": found["skipped"], "first": first}


class _Preload:
    """미리 올려 둔 다음 샷 — 영상 위치·재료 정보와 현재버전의 앞쪽 프레임."""

    def __init__(self, task: Dict[str, Any]) -> None:
        self.task = task
        self.movie = ""
        self.prepared: Optional[Dict[str, Any]] = None
        self.frames: Dict[int, Any] = {}
        self.decoder: Optional[StreamDecodeWorker] = None

    def matches(self, row: Dict[str, Any]) -> bool:
        """같은 샷의 같은 버전인가(그 사이 새 버전이 올라왔으면 버린다)."""
        return row.get("task_id") == self.task.get("task_id") and row.get(
            "latest_version_id"
        ) == self.task.get("latest_version_id")


class ConfirmWindow(QWidget):
    """컨펌 전용 창."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BPE 컨펌")
        self.resize(1680, 980)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._closed = False
        self._annotation = False  # Annotation 모드인가
        self._ref_dialog: Optional[RefFrameDialog] = None
        # 이어 재생: 줄인 그림 창고, 한 줄 위의 자리, 지금 컷
        self._seq: Optional[SequencePlayer] = None
        self._seq_token = 0
        self._seq_pos = 0
        self._seq_cut = -1
        self._seq_playing = False
        self._seq_wait_start = False  # 첫 그림이 오면 바로 재생
        self._seq_quiet = False  # 멈춘 컷을 여는 동안 가운데 알림을 띄우지 않는다
        self._pending_index: Optional[int] = None  # 열리면 옮겨 갈 프레임
        self._aumid_applied = False
        self._workers: List[Any] = []
        self._decoders: List[StreamDecodeWorker] = []
        self._decode_queue: List[str] = []
        self._decoding: Optional[StreamDecodeWorker] = None
        self._ondemand_pending: Dict[Tuple[str, int], StreamDecodeWorker] = {}
        self._decode_from: Dict[str, int] = {}  # 판마다 풀기를 시작할 프레임(미리 올린 만큼 건너뜀)
        self._preload: Optional[_Preload] = None
        self._preload_token = 0
        self._bufs: Dict[str, _Buffer] = {k: _Buffer(k, n, t) for k, n, t in _BUFFER_DEFS}
        self._shown = KEY_CUR
        self._last_shown = KEY_ORG
        self._diff = False
        self._diff_note = ""
        self._channel = CHANNEL_RGB
        self._lut: Optional[CubeLut] = None
        self._lut_on = False
        self._slate_on = False  # 편집본 슬레이트 자리(위아래 띠) 가림
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
        # 화면에 올라와 있는 영상이 어느 태스크의 것인가(머리 줄의 샷과 다를 수 있다)
        self._loaded_task_id: Any = None
        # 「상태만 다시 바꾸기」가 쓸 값 — 보냈던 그 샷의 것(지금 열린 샷이 아니다)
        self._retry: Optional[Dict[str, Any]] = None
        self._last_status_code = ""
        self._submit_busy = False
        self._version_note = ""
        self._open_started = 0.0
        self._memo_lines: Dict[int, str] = {}  # 도형 id → 메모 칸에 적어 둔 그 도형의 글
        self._pasted: List[str] = []  # 메모에 붙여 넣은 그림 파일들(이 샷의 초안과 함께 남는다)
        self._cc_req = 0
        self._lut_failed = ""
        # 룩이 입혀졌는지: 원본과 그림을 견줘 가린 결과(판 → True 입혀짐 / False 로그)
        self._look_measured: Dict[str, bool] = {}
        self._look_tried: set = set()
        self._lut_override: Dict[str, bool] = {}  # 판 → 사용자가 정한 룩업 씌움/뺌
        self._plate_probe: Optional[List[Any]] = None  # 일찍 읽어 둔 원본 첫 장의 점들
        self._curve = CURVE_REC709  # 영상 값 ↔ 선형 빛 곡선(원본의 색 표시로 정함)
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
        # 샷의 글 칸(워크오더·디스크립션)에 덧붙이는 중인 칸들
        self._shot_text_busy: Set[str] = set()
        self._shot_text_base: Dict[str, str] = {}  # 칸에 불러와 둔 샷그리드의 글
        # 노트용 그림 파일 → (그린 영상, 그 영상에서의 프레임 순번) — 그림 이름을 맞출 때 쓴다
        self._note_image_meta: Dict[str, Tuple[str, int]] = {}
        # 보낸 직후 머리 줄 상태 칸을 잠깐 강조한다(「sv → retake」 / 「Note 보냄」)
        self._status_flash: Optional[Dict[str, Any]] = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(_STATUS_FLASH_MS)
        self._flash_timer.timeout.connect(self._end_status_flash)
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

        self._strip = SequenceStrip()  # 이어 재생의 컷 띠(이어 재생 중에만 보인다)
        self._strip.seek_requested.connect(self._on_seq_seek)
        self._strip.close_requested.connect(self._close_sequence)
        self._strip.hide()
        left.addWidget(self._strip)
        self._timeline = ConfirmTimeline()
        self._timeline.frame_picked.connect(self._on_frame_picked)
        left.addWidget(self._timeline)
        left.addWidget(self._build_transport())
        body.addLayout(left, 1)

        self._panel = ConfirmSidePanel()
        self._panel.status_requested.connect(self._on_status_requested)
        self._panel.note_requested.connect(self._on_note_requested)
        self._panel.shot_text_requested.connect(self._on_shot_text_requested)
        self._panel.ref_frame_requested.connect(self._open_ref_dialog)
        self._panel.cancel_requested.connect(self._cancel_pending)
        self._panel.retry_requested.connect(self._retry_status_only)
        self._panel.past_note_clicked.connect(self._on_past_note)
        self._panel.memo_edited.connect(self._draft_timer.start)
        self._panel.insert_failures_requested.connect(self._insert_failures)
        self._panel.nav_requested.connect(self._nav_shot)
        self._panel.image_pasted.connect(self._on_image_pasted)
        self._panel.image_remove_requested.connect(self._remove_pasted)
        self._panel.cc_search_requested.connect(self._search_cc)
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
        self._drawer.sequence_requested.connect(self._start_sequence)
        self._drawer.rows_changed.connect(self._sync_header)
        self._drawer.rows_changed.connect(self._maybe_preload)
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
        modes = QHBoxLayout()
        modes.setSpacing(0)
        self._mode_btns: Dict[str, QPushButton] = {}
        for mode, tip in (
            (MODE_CONFIRM, "확인 대기 샷을 보고 상태를 정한다"),
            (MODE_ANNOTATION, "작업을 나눠 주기 전(wtg · assign) 샷의 원본에 가이드를 남긴다"),
        ):
            b = _btn(mode, checkable=True, tip=tip)
            b.clicked.connect(lambda _c=False, m=mode: self._set_mode(m))
            self._mode_btns[mode] = b
            modes.addWidget(b)
        style.make_segments(list(self._mode_btns.values()))
        for b in self._mode_btns.values():
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 0px 10px; }")
        self._mode_btns[MODE_CONFIRM].setChecked(True)
        row.addLayout(modes)
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
        self._btn_shot_dir = _icon_btn("shot_dir", "이 샷 작업 폴더 열기")
        _use_app_icon(self._btn_shot_dir, _explorer_icon())  # 윈도우 탐색기 아이콘
        self._btn_shot_dir.clicked.connect(self._open_shot_folder)
        row.addWidget(self._btn_shot_dir)
        self._btn_sg = _icon_btn("web", "샷그리드에서 이 샷 열기")
        _use_app_icon(self._btn_sg, _shotgrid_icon())  # 내 작업 탭과 같은 샷그리드 아이콘
        self._btn_sg.clicked.connect(self._open_shot_in_shotgrid)
        row.addWidget(self._btn_sg)
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
        self._buf_pos: Dict[str, str] = {}
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
        self._btn_slate = _btn(
            "Slate (S)",
            checkable=True,
            tip="편집본 슬레이트 자리(위아래 띠, 2:1)를 가려서 봅니다 — 다시 누르면 끔",
        )
        self._btn_slate.clicked.connect(self._toggle_slate)
        style.make_segments([self._btn_slate])  # Fit·Fill 과 같은 눌린 모양
        chans.addWidget(self._btn_slate)
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
        self._btn_gain = _btn("Gain", tip="누르면 1.00 으로")
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
        self._btn_gamma = _btn("Gamma", tip="누르면 1.00 으로")
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
        self._btn_lut_here = _btn(
            "이 판에 씌움",
            checkable=True,
            tip="지금 보는 판에 룩업을 씌울지 — 자동 판단이 틀렸을 때 바꿉니다 (Shift+L)",
        )
        self._btn_lut_here.setStyleSheet(style.segment_style("only"))
        self._btn_lut_here.clicked.connect(self._toggle_lut_here)
        look.addWidget(self._btn_lut_here)
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
            self._stop_sequence()
            self.open_movie(path)

    def open_movie(
        self,
        movie: str,
        task: Optional[Dict[str, Any]] = None,
        preloaded: Optional[_Preload] = None,
    ) -> None:
        """작업본 영상 하나에서 출발해 같은 샷의 재료를 찾아 올린다.

        *preloaded* 는 미리 올려 둔 것 — 재료 찾기를 건너뛰고 올라와 있는 프레임부터 보여 준다.
        """
        token = self._reset_shot(movie, task)
        self._hud.setText(Path(movie).stem)
        self._hud.adjustSize()
        self._hud.show()
        looking = "편집본 찾는 중" if self._annotation else "원본 · 전 버전 · 편집본 찾는 중"
        self._set_busy(f"{Path(movie).stem} 여는 중…", looking)
        if self._open_started <= 0:
            self._open_started = time.perf_counter()
        logger.info("confirm open: movie resolved +%.2fs", time.perf_counter() - self._open_started)
        self._sync_all()

        project = self._project_key()
        picked = dict(get_confirm_settings()["presets"])

        if preloaded is not None and preloaded.prepared is not None:
            self._on_prepared(preloaded.prepared, token, preloaded.frames)
            return
        annotation = self._annotation
        w = ShotGridWorker(lambda: _prepare_media(movie, project, picked, annotation))
        w.finished.connect(lambda r, t=token: self._on_prepared(r, t))
        w.error.connect(lambda e, t=token: self._on_prepare_failed(e, t))
        w.start()
        self._workers.append(w)

    def _reset_shot(self, movie: str = "", task: Optional[Dict[str, Any]] = None) -> int:
        """열려 있던 샷을 내려놓고 빈 상태로 돌린다. 새로 여는 일의 번호를 돌려준다."""
        self._save_draft()
        self._stop_decoders()
        self._drop_preload()
        self._cancel_pending()
        self._pause()
        self._load_token += 1
        self._movie = movie
        self._shot_root = None
        self._task = self._with_sent_status(task)
        self._loaded_task_id = row_ident(self._task)
        self._retry = None
        self._drawer.set_current_task(row_ident(self._task))
        self._sent_note_id = None
        self._version_note = ""
        for buf in self._bufs.values():
            buf.path, buf.info, buf.size, buf.frames = None, None, (0, 0), {}
            buf.full, buf.lut_baked, buf.version_label, buf.error = False, False, "", ""
            buf.short_at = None
            buf.resample = RESAMPLE_PLAIN
        self._index, self._count = 0, 0
        self._checks = []
        self._standard, self._preset_names, self._basis = None, [], ""
        self._shown, self._last_shown, self._diff = KEY_CUR, KEY_ORG, False
        self._layer.set_doc(AnnotationDoc())
        self._layer.set_ghosts([])
        self._pasted = []
        self._panel.set_pasted_images([])
        self._panel.clear_cc()
        # 샷 칸 글은 이 샷에 지금 적혀 있는 글로 채운다(앞 샷에 쓰던 글이 넘어오지 않는다)
        self._load_shot_text()
        self._panel.set_shot_text_result("", True)
        self._look_measured, self._look_tried, self._lut_override = {}, set(), {}
        self._plate_probe = None
        self._timeline.set_range(self._frame_start, 0)
        self._panel.set_result("", True)
        self._panel.set_checks([])
        self._panel.set_standard("", "", [], "")
        self._panel.set_past_notes([])
        return self._load_token

    # ── 이어 재생 ────────────────────────────────────────────────
    # 고른 컷들의 줄인 그림을 한 줄로 재생한다. 재생 중에는 열린 샷이 없고(화면은 줄인
    # 그림 창고에서 바로 온다), 멈추면 그 컷을 평소처럼 열어 그리기·판 바꾸기·상태를 쓴다.

    def _nav_rows(self) -> List[Dict[str, Any]]:
        """이전·다음 샷이 오가는 줄들 — 이어 재생 중에는 그 컷들."""
        return self._seq.rows() if self._seq is not None else self._drawer.shown_rows()

    def is_sequence(self) -> bool:
        return self._seq is not None

    def _start_sequence(self, rows: object) -> None:
        """목록에서 고른 컷들을 샷 이름 순으로 이어 재생한다(준비는 뒤에서)."""
        picked_rows = (
            [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        )
        if len(picked_rows) < SEQ_MIN_CUTS or self._annotation:
            return
        if self._drawer.isVisible():
            self._toggle_drawer()
        self._stop_sequence()
        self._reset_shot()
        self._view.clear_images()
        self._hud.hide()
        token = self._seq_token
        self._strip.set_cuts([], [])
        self._strip.set_note("준비 중…")
        self._strip.show()
        self._set_busy("이어 재생 준비 중…", f"컷 {len(picked_rows)}개의 영상 찾는 중")
        ordered = order_rows(picked_rows)
        picked = dict(get_confirm_settings()["presets"])
        w = ShotGridWorker(lambda: _prepare_sequence(ordered, picked))
        w.finished.connect(lambda r, t=token: self._on_sequence_prepared(r, t))
        w.error.connect(lambda e, t=token: self._on_sequence_failed(e, t))
        w.start()
        self._workers.append(w)
        self._sync_all()

    def _on_sequence_failed(self, msg: str, token: int) -> None:
        if token != self._seq_token or self._closed:
            return
        self._strip.hide()
        self._set_busy("이어 재생을 준비하지 못했습니다", msg, error=True)

    def _on_sequence_prepared(self, result: object, token: int) -> None:
        if token != self._seq_token or self._closed or not isinstance(result, dict):
            return
        cuts = list(result.get("cuts") or [])
        skipped = [s for s in result.get("skipped") or [] if s]
        if len(cuts) < SEQ_MIN_CUTS:
            self._strip.hide()
            detail = "서버에 영상이 없는 컷: " + ", ".join(skipped) if skipped else ""
            self._set_busy("이어 볼 영상을 찾지 못했습니다", detail, error=True)
            return
        budget = int(int(get_confirm_settings()["cache_mb"]) * 1024 * 1024 * SEQ_BUDGET_SHARE)
        player = SequencePlayer(self)
        if not player.load(cuts, budget):
            self._strip.hide()
            player.deleteLater()
            self._set_busy(
                "컷이 너무 길어 이어 재생할 수 없습니다", "컷 수를 줄여 주세요", error=True
            )
            return
        first = result.get("first")
        if isinstance(first, dict):  # 첫 컷의 프리셋으로 룩업을 고른다
            standard = first.get("standard")
            self._standard = standard if isinstance(standard, ProjectStandard) else None
            self._task = dict(cuts[0].row)
            self._load_project_lut()
        player.frame_ready.connect(self._on_seq_frame)
        player.counts_changed.connect(self._on_seq_counts)
        player.look_changed.connect(self._on_seq_look)
        player.cut_failed.connect(self._on_seq_cut_failed)
        self._seq = player
        player.set_lut(self._lut, bool(self._standard and self._standard.look))
        self._seq_pos, self._seq_cut, self._seq_wait_start = 0, -1, True
        self._strip.set_cuts([c.shot for c in cuts], player.counts())
        note = f"{len(cuts)}컷 · {cuts[0].size[0]}×{cuts[0].size[1]}"
        if skipped:
            note += f" · 영상 없음 {len(skipped)}컷"
        self._strip.set_note(note)
        self._set_busy("이어 재생 올리는 중…", cuts[0].shot)
        logger.info(
            "confirm sequence: %d cuts, %d frames, %s, %.0f MB",
            len(cuts),
            total_frames(player.counts()),
            cuts[0].size,
            player.bytes_planned() / 1048576,
        )
        player.start()
        self._sync_all()

    def _on_seq_frame(self, cut: int, index: int) -> None:
        seq = self._seq
        if seq is None or self._closed:
            return
        self._strip.set_cached(cut, len(seq.cuts[cut].frames))
        if cut == self._seq_cut and self._seq_playing:
            self._timeline.add_cached(index)
        if self._seq_wait_start and index == 0:  # 첫 그림이 왔다 — 바로 재생
            self._seq_wait_start = False
            self._set_busy("")
            self._seq_play(position(seq.counts(), cut, 0))

    def _on_seq_counts(self) -> None:
        seq = self._seq
        if seq is None:
            return
        counts = seq.counts()
        self._strip.set_counts(counts)
        self._seq_pos = max(0, min(self._seq_pos, max(0, total_frames(counts) - 1)))

    def _on_seq_look(self, cut: int) -> None:
        if self._seq_playing and cut == self._seq_cut:
            self._seq_show(self._seq_pos)  # 룩 판단이 나왔다 — 지금 그림에 바로 맞춘다

    def _on_seq_cut_failed(self, cut: int, msg: str) -> None:
        seq = self._seq
        if seq is None:
            return
        self._panel.set_result(f"{seq.cuts[cut].shot} 영상을 풀지 못했습니다: {msg}", False)

    def _seq_interval(self) -> int:
        return max(1, int(round(1000.0 / (self._fps or 24.0))))

    def _seq_play(self, pos: Optional[int] = None) -> None:
        """이어 재생을 시작하거나 잇는다. 자리를 안 주면 멈춰서 보던 컷·프레임부터."""
        seq = self._seq
        if seq is None or total_frames(seq.counts()) <= 0:
            return
        if pos is None:
            pos = self._seq_pos
            cut = seq.index_of(self._task)
            if cut >= 0 and self._bufs[KEY_CUR].available:
                pos = position(seq.counts(), cut, self._index)
        self._seq_wait_start = False
        self._seq_quiet = False
        self._reset_shot()  # 열려 있던 컷은 내려놓는다(메모·그림은 초안으로 남는다)
        self._set_busy("")
        self._seq_cut = -1
        self._seq_pos = pos
        self._seq_playing = True
        self._layer.set_tool(TOOL_SELECT)
        self._seq_show(pos)
        self._play_timer.start(self._seq_interval())
        self._sync_all()

    def _seq_show(self, pos: int) -> bool:
        """한 줄 위의 *pos* 자리 그림을 화면에 올린다. 아직 안 풀린 자리면 ``False``."""
        seq = self._seq
        if seq is None:
            return False
        counts = seq.counts()
        cut, frame = locate(counts, pos)
        data = seq.frame(cut, frame)
        if data is None:
            return False
        c = seq.cuts[cut]
        if cut != self._seq_cut:  # 컷 경계 — 머리 줄·작업 내용·타임라인을 그 컷 것으로
            self._seq_cut = cut
            self._task = dict(c.row)
            self._fps = c.fps
            self._timeline.set_range(self._frame_start, c.count)
            for i in c.frames:
                self._timeline.add_cached(i)
            self._fill_work_info()
            self._sync_header()
            if self._seq_playing:
                self._play_timer.setInterval(self._seq_interval())
        self._seq_pos = pos
        self._view.set_image(SLOT_A, data, c.size[0], c.size[1])
        self._view.set_view(
            gain=self._gain_value(),
            gamma=self._gamma_value(),
            mode=VIEW_MODE_A,
            channel=self._channel,
            lut_on=self._lut_on and self._lut is not None and seq.lut_wanted(cut),
            lut_b_on=False,
            lut_post=False,
            curve=self._curve,
            mask_bar=self._slate_bar(c.size),
        )
        number = self._frame_start + frame
        self._timeline.set_current(frame)
        self._strip.set_position(pos)
        self._hud.setText(f"{cut + 1}/{len(counts)}  {Path(c.movie).stem}  {number}")
        self._hud.adjustSize()
        self._hud.show()
        if not self._frame_edit.hasFocus():
            self._frame_edit.setText(str(number))
        return True

    def _seq_tick(self) -> None:
        seq = self._seq
        if seq is None:
            self._seq_playing = False
            self._play_timer.stop()
            return
        nxt = next_position(seq.counts(), self._seq_pos, self._loop)
        if nxt is None:
            self._seq_pause()
            return
        self._seq_show(nxt)  # 아직 안 풀린 자리면 올라올 때까지 기다린다

    def _seq_halt(self) -> None:
        """재생 시계만 멈춘다(컷을 열지는 않는다)."""
        self._seq_playing = False
        self._seq_wait_start = False
        if not self._playing:
            self._play_timer.stop()
        style.set_icon(self._btn_play, "play", size=14)

    def _seq_pause(self) -> None:
        """이어 재생을 멈추고, 멈춘 컷을 평소처럼 연다 — 그 프레임에서 그리기·판 바꾸기·상태."""
        if self._seq is None or not self._seq_playing:
            return
        self._seq_halt()
        self._seq_open_at(self._seq_pos)

    def _seq_open_at(self, pos: int) -> None:
        seq = self._seq
        if seq is None:
            return
        cut, frame = locate(seq.counts(), pos)
        c = seq.cuts[cut]
        self._seq_pos, self._seq_cut = pos, cut
        self._strip.set_position(pos)
        self._pending_index = frame
        self._seq_quiet = True  # 줄인 그림이 보이고 있다 — 가운데 알림으로 가리지 않는다
        self._open_started = time.perf_counter()
        self.open_movie(c.movie, dict(c.row))

    def _on_seq_seek(self, pos: int) -> None:
        """컷 띠를 눌렀다 — 재생 중이면 그 자리로, 멈춰 있으면 그 컷·프레임을 연다."""
        seq = self._seq
        if seq is None:
            return
        if self._seq_playing:
            self._seq_show(pos)
            return
        cut, frame = locate(seq.counts(), pos)
        if cut == seq.index_of(self._task) and self._bufs[KEY_CUR].available:
            self._set_index(frame)
            return
        self._seq_open_at(pos)

    def _seq_follow(self) -> None:
        """멈춰서 프레임을 옮길 때 컷 띠의 자리도 따라가게 한다."""
        seq = self._seq
        if seq is None or self._seq_playing or not self._bufs[KEY_CUR].available:
            return
        cut = seq.index_of(self._task)
        if cut >= 0:
            self._seq_pos = position(seq.counts(), cut, self._index)
            self._strip.set_position(self._seq_pos)

    def _seq_nav(self, delta: int) -> None:
        """이어 재생 중의 이전·다음 샷 — 그 컷들 사이에서만 오간다."""
        seq = self._seq
        if seq is None:
            return
        counts = seq.counts()
        cut = self._seq_cut if self._seq_playing else seq.index_of(self._task)
        if cut < 0:
            cut = locate(counts, self._seq_pos)[0]
        nxt = cut + delta
        while 0 <= nxt < len(counts) and counts[nxt] <= 0:  # 못 푼 컷은 건너뛴다
            nxt += delta
        if not 0 <= nxt < len(counts):
            return
        pos = position(counts, nxt, 0)
        if not self._seq_playing:
            self._seq_open_at(pos)
        elif not self._seq_show(pos):
            self._seq_pos = max(0, pos - 1)  # 아직 안 풀렸다 — 올라오면 그 컷부터 잇는다

    def _stop_sequence(self) -> None:
        """이어 재생을 끝내고 풀어 둔 그림을 내려놓는다(열려 있는 컷은 그대로 둔다)."""
        self._seq_token += 1
        self._seq_playing = self._seq_wait_start = self._seq_quiet = False
        if not self._playing:
            self._play_timer.stop()
        seq, self._seq = self._seq, None
        self._seq_cut = -1
        if seq is not None:
            seq.stop()
            seq.deleteLater()
        self._strip.hide()

    def _close_sequence(self) -> None:
        """컷 띠의 「닫기」."""
        was_playing = self._seq_playing or not self._bufs[KEY_CUR].available
        self._stop_sequence()
        if was_playing:  # 열린 컷이 없다 — 화면을 비운다
            self._reset_shot()
            self._view.clear_images()
            self._hud.hide()
            self._panel.set_work_info("", "", "")
            self._set_busy("")
        style.set_icon(self._btn_play, "play", size=14)
        self._sync_all()

    def _set_mode(self, mode: str) -> None:
        """Confirm(확인 대기 샷) 과 Annotation(나눠 주기 전 샷의 원본에 가이드) 을 오간다.

        모드가 바뀌면 열려 있던 샷은 내려놓고(쓰던 메모·그림은 초안으로 남는다) 그 모드의
        목록을 연다.
        """
        annotation = mode == MODE_ANNOTATION
        if annotation == self._annotation:
            self._sync_header()
            return
        self._stop_sequence()
        self._reset_shot()
        self._annotation = annotation
        self._bufs[KEY_CUR].title = (
            _ANNOTATION_PLATE_TITLE if annotation else _BUFFER_TITLES[KEY_CUR]
        )
        self._panel.set_memo_text("")
        self._memo_lines = {}
        self._panel.set_work_info("", "", "")
        self._panel.set_annotation(annotation)
        self._drawer.set_mode(mode)
        self._view.clear_images()
        self._hud.hide()
        self._set_busy("")
        self._sync_all()
        if not self._drawer.isVisible():
            self._toggle_drawer()

    def is_annotation(self) -> bool:
        return self._annotation

    def _on_prepare_failed(self, msg: str, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        self._pending_index = None
        self._set_busy("영상을 열지 못했습니다", msg, error=True)

    def _on_prepared(
        self, result: object, token: int, seed: Optional[Dict[int, Any]] = None
    ) -> None:
        if token != self._load_token or self._closed or not isinstance(result, dict):
            return
        media = result["media"]
        paths: Dict[str, Optional[Path]] = result["paths"]
        infos: Dict[str, Optional[VideoInfo]] = result["infos"]
        cur_info = infos.get(KEY_CUR)
        if cur_info is None:
            name = Path(self._movie).name
            missing = container_shortfall(self._movie)
            if missing > 0:  # 목차까지 날아간 파일 — 보내거나 복사하다 끊겼다
                try:
                    have = Path(self._movie).stat().st_size
                except OSError:
                    have = 0
                mb = 1024 * 1024
                self._set_busy(
                    "파일이 잘려 열 수 없습니다",
                    f"{name} — {(have + missing) / mb:.0f}MB 중 {have / mb:.0f}MB 만 있음",
                    error=True,
                )
            else:
                self._set_busy("영상 규격을 읽지 못했습니다", name, error=True)
            return
        self._shot_root = media.shot_root
        self._curve = CURVE_GAMMA22 if result.get("plate_color") == GAMMA else CURVE_REC709
        linear = ""
        if result.get("zscale"):
            linear = {REC709: RESAMPLE_LINEAR_709, GAMMA: RESAMPLE_LINEAR_22}.get(
                str(result.get("plate_color") or ""), ""
            )
        cur_size = fit_decode_size(cur_info.width, cur_info.height, _MAX_W, _MAX_H)
        self._count = max(1, cur_info.frame_count or 1)
        self._fps = cur_info.fps or 24.0
        pending, self._pending_index = self._pending_index, None
        if pending:  # 이어 재생에서 멈춘 자리
            self._index = max(0, min(self._count - 1, int(pending)))
        budget = int(get_confirm_settings()["cache_mb"]) * 1024 * 1024
        if self._seq is not None:  # 이어 재생이 들고 있는 그림만큼은 뺀다
            budget = max(0, budget - self._seq.bytes_planned())
        for key in _DECODE_ORDER:
            buf = self._bufs[key]
            buf.path, buf.info = paths.get(key), infos.get(key)
            if buf.path is None or buf.info is None:
                continue
            if key == KEY_CUR:
                buf.size = cur_size
            else:
                buf.size = fit_decode_size(buf.info.width, buf.info.height, *cur_size)
                # 원본이 작업본보다 커서 원본만 줄여야 하면(예: UHD 원본 · 1080 납품) 누크처럼
                # 선형 색에서 줄인다 — 그래야 Difference 에서 그레인이 지워진다.
                bigger = (buf.info.width, buf.info.height) != (cur_info.width, cur_info.height)
                shrunk = buf.size != (buf.info.width, buf.info.height)
                if key == KEY_ORG and bigger and shrunk and linear:
                    buf.resample = linear
            need = frame_byte_size(*buf.size) * min(self._count, buf.frame_count() or self._count)
            buf.full = key == KEY_CUR or need <= budget
            if buf.full:
                budget -= need
        if media.current and (not self._annotation or media.current.version):
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
        if self._annotation:
            self._last_shown = KEY_EDIT
        self._load_draft()
        self._load_project_lut()
        self._fill_work_info()
        self._decode_queue = [
            k for k in _DECODE_ORDER if self._bufs[k].available and self._bufs[k].full
        ]
        cur_buf = self._bufs[KEY_CUR]
        seeded = False
        if seed and len(next(iter(seed.values()))) == frame_byte_size(*cur_buf.size):
            # 미리 올려 둔 앞쪽 프레임을 그대로 쓰고, 풀기는 그 뒤부터 잇는다
            seeded = True
            cur_buf.frames = dict(seed)
            for i in sorted(cur_buf.frames):
                self._timeline.add_cached(i)
            if len(cur_buf.frames) >= self._count:
                self._decode_queue.remove(KEY_CUR)
            else:
                self._decode_from[KEY_CUR] = len(cur_buf.frames)
        self._set_busy(f"{Path(self._movie).stem} 올리는 중…", f"0 / {self._count} 프레임")
        self._seq_quiet = False
        logger.info("confirm open: media ready +%.2fs", time.perf_counter() - self._open_started)
        self._start_look_probe()
        self._start_next_decode()
        if self._index > 0:  # 멈춘 프레임부터 먼저 보여 준다(앞에서부터 푸는 것을 안 기다린다)
            self._request_frame(cur_buf, self._index, force=True)
        self._sync_all()
        if seeded and self._buffer_index(cur_buf) in cur_buf.frames:
            self._set_busy("")
            logger.info(
                "confirm open: first picture +%.2fs (preloaded %d frames)",
                time.perf_counter() - self._open_started,
                len(cur_buf.frames),
            )
            self._open_started = 0.0
            self._refresh_view()
        if self._decoding is None and not self._decode_queue:
            QTimer.singleShot(0, self._maybe_preload)
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
        if self._annotation:  # 원본을 보는 중 — 납품 규격 검사는 하지 않는다
            self._checks = []
            self._basis = "Annotation — 원본(ORG plate)을 보는 중 · 규격 검사 없음"
            self._panel.set_checks([])
            self._show_standard()
            return
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
        self._show_standard()

    def _show_standard(self) -> None:
        """기준·룩 줄을 오른쪽 칸에 적는다(룩업을 읽은 뒤에도 다시 부른다)."""
        s = self._standard
        lut_name = Path(self._lut_path).stem if self._lut is not None else ""
        if s is None:
            look = ""
        elif lut_name and self._bufs[KEY_CUR].available:
            parts = [
                f"{b.title} {'씌움' if self._lut_wanted(b) else '그대로'}"
                for b in self._bufs.values()
                if b.available
            ]
            look = f"룩업 {lut_name} — " + " · ".join(parts)
        elif s.look and lut_name:
            look = f"{s.look} 입혀진 MOV — 룩업은 ORG plate 에만 ({lut_name})"
        elif s.look:
            look = f"{s.look} 입혀진 MOV — 룩업 안 씌움"
        elif s.viewer and lut_name:
            look = f"MOV 에 룩 없음 · 룩업 {lut_name}"
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
        """이 판에 룩이 이미 입혀져 있나(자동 판단).

        먼저 원본과 그림을 견줘 가린 결과를 쓴다 — 같은 프로젝트에서도 로그로 온 것과
        룩을 입혀 온 것이 섞여 있어서, 이름·프리셋만으로는 틀린다. 그림으로 못 가렸을 때만
        파일 이름(_lut) → 편집본은 입혀진 것 → 프리셋 순서로 본다. 원본은 늘 로그로 본다.
        """
        if buf.key == KEY_ORG or (self._annotation and buf.key == KEY_CUR):
            return buf.lut_baked  # 원본은 늘 로그(Annotation 에서는 「지금 보는 판」이 원본)
        measured = self._look_measured.get(buf.key)
        if measured is not None:
            return measured
        if buf.lut_baked or buf.key == KEY_EDIT:
            return True
        return bool(self._standard and self._standard.look)

    def _lut_wanted(self, buf: _Buffer) -> bool:
        """이 판에 룩업을 씌워야 하나 — 사용자가 바꿔 놓았으면 그대로, 아니면 자동 판단."""
        forced = self._lut_override.get(buf.key)
        return forced if forced is not None else not self._look_baked(buf)

    def _lut_applies(self, buf: _Buffer) -> bool:
        return self._lut_on and self._lut is not None and self._lut_wanted(buf)

    def _measure_looks(self) -> None:
        """원본과 견줘 각 판에 룩이 입혀졌는지 가린다(판마다 한 번, 프레임이 올라온 뒤)."""
        lut = self._lut
        org = self._bufs[KEY_ORG]
        if lut is None or (self._plate_probe is None and not org.frames):
            return
        changed = False
        for key in (KEY_CUR, KEY_PREV, KEY_EDIT):
            buf = self._bufs[key]
            if key in self._look_tried or not buf.frames:
                continue
            if self._plate_probe is not None:
                # 일찍 읽어 둔 원본 첫 장과, 이 판에서 가장 앞에 올라온 장을 견준다
                index = min(buf.frames)
                plate = self._plate_probe
            else:
                found = next((i for i in sorted(org.frames) if i in buf.frames), None)
                if found is None:
                    continue
                index = found
                plate = sample_grid(org.frames[index], org.size[0], org.size[1])
            self._look_tried.add(key)
            verdict = judge_look(
                sample_grid(buf.frames[index], buf.size[0], buf.size[1]), plate, lut
            )
            logger.info(
                "confirm look: %s baked=%s (plain %.3f, lut %.3f)",
                key,
                verdict.baked,
                verdict.to_plain,
                verdict.to_lut,
            )
            if verdict.baked is not None:
                self._look_measured[key] = verdict.baked
                changed = True
        if changed:
            self._show_standard()
            self._sync_all()

    def _start_look_probe(self) -> None:
        """원본 첫 장만 먼저 읽는다 — 긴 샷에서도 룩 판단이 바로 나오게."""
        org = self._bufs[KEY_ORG]
        if not org.available or self._closed:
            return
        w = StreamDecodeWorker(
            KEY_ORG, str(org.path), org.size[0], org.size[1], start_index=0, frame_count=1
        )
        token = self._load_token
        w.frame_ready.connect(lambda _k, _i, d, t=token: self._on_look_probe(d, t))
        self._decoders.append(w)
        w.start()

    def _on_look_probe(self, data: object, token: int) -> None:
        if token != self._load_token or self._closed:
            return
        org = self._bufs[KEY_ORG]
        samples = sample_grid(data, org.size[0], org.size[1])
        if samples:
            self._plate_probe = samples
            self._measure_looks()

    def _toggle_lut_here(self) -> None:
        """지금 보는 판만 룩업을 씌우거나 뺀다(자동 판단이 틀렸을 때)."""
        buf = self._bufs[self._shown]
        if self._lut is None or not buf.available:
            return
        self._lut_override[buf.key] = not self._lut_wanted(buf)
        self._lut_on = True
        self._show_standard()
        self._sync_all()

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
        self._load_project_lut()
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
        row = self._with_sent_status(task)
        shot = str(row.get("shot_code") or "")
        if self._drawer.isVisible():
            self._toggle_drawer()
        self._pending_index = None
        if self._seq is not None or self._strip.isVisible():
            cut = self._seq.index_of(row) if self._seq is not None else -1
            if cut >= 0 and self._seq is not None:  # 이어 보는 컷 — 그 컷의 첫 프레임으로 옮긴다
                self._seq_halt()
                self._seq_open_at(position(self._seq.counts(), cut, 0))
                return
            self._stop_sequence()  # 다른 샷을 열면 이어 재생은 끝난다
        # 세고 있던 보내기는 여기서 끊는다 — 머리 줄이 새 샷으로 바뀐 뒤에 나가면
        # 앞 샷의 메모·그림·상태가 새 샷으로 간다
        self._cancel_pending()
        self._pause()
        self._task = row  # 위 막대가 바로 고른 샷으로 바뀐다
        self._shot_root = None
        self._drawer.set_current_task(row_ident(row))
        self._sync_header()
        looking = "서버에서 원본(ORG plate) 찾는 중" if self._annotation else ""
        self._set_busy(f"{shot} 여는 중…", looking or "서버에서 영상 파일 찾는 중")
        self._open_started = time.perf_counter()
        pre = None if self._annotation else self._take_preload(row)
        if pre is not None:  # 미리 올려 둔 샷 — 찾기·읽기를 건너뛰고 바로 보여 준다
            self.open_movie(pre.movie, row, preloaded=pre)
            return
        self._drop_preload()
        self._load_token += 1
        token = self._load_token

        resolve = _resolve_plate_movie if self._annotation else _resolve_task_movie
        w = ShotGridWorker(lambda: resolve(row))
        w.finished.connect(lambda r, t=token, tk=row: self._on_task_resolved(r, t, tk))
        w.error.connect(lambda e, t=token: self._on_prepare_failed(e, t))
        w.start()
        self._workers.append(w)

    def _on_task_resolved(self, result: object, token: int, task: Dict[str, Any]) -> None:
        if token != self._load_token or self._closed:
            return
        if (not isinstance(result, str) or not result) and self._annotation:
            self._set_busy(
                "원본(ORG plate)을 찾지 못했습니다",
                f"{task.get('shot_code') or ''} — 샷 폴더의 plate/org 에 영상이 아직 없습니다",
                error=True,
            )
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
        if self._seq is not None:
            self._seq_nav(delta)
            return
        rows = self._drawer.shown_rows()
        cur = row_ident(self._task)
        idx = next((i for i, r in enumerate(rows) if row_ident(r) == cur), -1)
        nxt = idx + delta
        if rows and 0 <= nxt < len(rows):
            self._open_task(rows[nxt])

    # ── 풀기(디코드) ─────────────────────────────────────────────

    def _start_next_decode(self) -> None:
        if self._decoding is not None or not self._decode_queue or self._closed:
            return
        key = self._decode_queue.pop(0)
        buf = self._bufs[key]
        start = self._decode_from.pop(key, 0)
        w = StreamDecodeWorker(
            key,
            str(buf.path),
            buf.size[0],
            buf.size[1],
            start_index=start,
            frame_count=max(1, self._count - start),
            resample=buf.resample,
        )
        token = self._load_token
        w.frame_ready.connect(lambda k, i, d, t=token: self._on_frame(k, i, d, t))
        w.finished_ok.connect(lambda k, n, t=token, s=start: self._on_decode_done(t, k, s + n))
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
        if len(self._look_tried) < 3:
            self._measure_looks()
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

    def _on_decode_done(self, token: int, key: str = "", upto: int = 0) -> None:
        """한 판을 다 풀었다. *upto* 는 그 판에서 그림이 올라온 마지막 번호의 다음(0부터).

        머리 글에 적힌 프레임 수보다 적게 풀렸으면 파일이 잘렸거나 깨진 것이다 — 「올리는 중」
        으로 두지 않고 알린다(현재버전이면 검사도 실패로 바꾼다).
        """
        if token != self._load_token:
            return
        buf = self._bufs.get(key)
        if buf is not None and buf.available:
            want = min(self._count, buf.frame_count() or self._count)
            if 0 < upto < want:
                buf.short_at = upto
                logger.warning(
                    "confirm decode: %s %d장 중 %d장만 풀림 — 파일이 잘렸거나 깨짐 (%s)",
                    key,
                    want,
                    upto,
                    buf.path.name if buf.path else "",
                )
                if key == KEY_CUR:
                    self._fail_frames_check(short_decode_message(want, upto))
                self._sync_all()
        self._decoding = None
        self._start_next_decode()
        self._maybe_preload()

    def _fail_frames_check(self, message: str) -> None:
        """프레임 검사를 실패로 바꾼다(없으면 맨 앞에 넣는다) — 풀어 보니 그림이 모자랄 때."""
        if self._annotation:
            return
        cut = CheckResult("프레임", STATE_FAIL, message)
        rest = [c for c in self._checks if c.name != "프레임"]
        self._checks = [cut, *rest]
        self._panel.set_checks(self._checks)

    def _on_decode_failed(self, key: str, msg: str, token: int) -> None:
        if token != self._load_token:
            return
        self._bufs[key].error = msg
        if self._decoding is not None and self._decoding.key == key:
            self._decoding = None
        self._ondemand_pending = {k: v for k, v in self._ondemand_pending.items() if k[0] != key}
        self._start_next_decode()
        self._sync_all()

    def _request_frame(self, buf: _Buffer, index: int, force: bool = False) -> None:
        """메모리에 다 못 올린 판 — 필요한 프레임 한 장만 그때 푼다.

        *force* 면 다 올리는 판이어도 그 한 장을 먼저 푼다(이어 재생에서 멈춘 자리).
        """
        if (buf.full and not force) or not buf.available:
            return
        if (buf.key, index) in self._ondemand_pending or index in buf.frames:
            return
        w = StreamDecodeWorker(
            buf.key,
            str(buf.path),
            buf.size[0],
            buf.size[1],
            start_index=index,
            frame_count=1,
            resample=buf.resample,
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
        self._decode_from = {}
        self._decoding = None
        self._ondemand_pending = {}

    # ── 다음 샷 미리 올려 두기 ───────────────────────────────────

    def _maybe_preload(self) -> None:
        """지금 샷이 다 올라와 한가할 때만 목록의 다음 샷을 미리 준비한다."""
        if self._closed or self._count <= 0 or self._decoding is not None or self._decode_queue:
            return
        if self._annotation:  # 원본은 크다 — 다음 샷을 미리 올리지 않는다
            return
        if self._seq is not None:  # 이어 재생의 그림이 이미 올라와 있다
            return
        rows = self._drawer.shown_rows()
        cur = row_ident(self._task)
        idx = next((i for i, r in enumerate(rows) if row_ident(r) == cur), -1)
        if cur is None or idx < 0 or idx + 1 >= len(rows):
            return
        row = dict(rows[idx + 1])
        if self._preload is not None and self._preload.matches(row):
            return
        self._drop_preload()
        self._preload = _Preload(row)
        token = self._preload_token
        project = (row.get("project_code") or row.get("project_name") or "").strip()
        picked = dict(get_confirm_settings()["presets"])

        def _work() -> Dict[str, Any]:
            movie = _resolve_task_movie(row)
            prepared = _prepare_media(movie, project, picked) if movie else None
            return {"movie": movie, "prepared": prepared}

        w = ShotGridWorker(_work)
        w.finished.connect(lambda r, t=token: self._on_preload_ready(r, t))
        w.error.connect(lambda e: logger.info("confirm preload: failed: %s", e))
        w.start()
        self._workers.append(w)

    def _cache_room(self) -> int:
        """메모리 한도에서 지금 샷이 쓰는 만큼을 뺀 나머지(바이트)."""
        budget = int(get_confirm_settings()["cache_mb"]) * 1024 * 1024
        used = sum(
            len(b.frames) * frame_byte_size(*b.size) for b in self._bufs.values() if b.size[0]
        )
        return max(0, budget - used)

    def _on_preload_ready(self, result: object, token: int) -> None:
        pre = self._preload
        if token != self._preload_token or self._closed or pre is None:
            return
        prepared = result.get("prepared") if isinstance(result, dict) else None
        info = prepared["infos"].get(KEY_CUR) if isinstance(prepared, dict) else None
        movie = str(result.get("movie") or "") if isinstance(result, dict) else ""
        if not movie or info is None:
            self._preload = None  # 못 찾은 샷 — 열 때 평소대로 찾고 알린다
            return
        pre.movie, pre.prepared = movie, prepared
        size = fit_decode_size(info.width, info.height, _MAX_W, _MAX_H)
        # 지금 샷이 먼저다 — 남는 메모리만큼만 앞쪽 프레임을 올려 둔다
        room = self._cache_room() // max(1, frame_byte_size(*size))
        count = min(max(1, info.frame_count or 1), int(room))
        if count < 1:
            return
        w = StreamDecodeWorker(KEY_CUR, movie, size[0], size[1], frame_count=count)
        w.frame_ready.connect(lambda _k, i, d, t=token: self._on_preload_frame(i, d, t))
        pre.decoder = w
        w.start()

    def _on_preload_frame(self, index: int, data: object, token: int) -> None:
        if token == self._preload_token and self._preload is not None:
            self._preload.frames[index] = data

    def _take_preload(self, row: Dict[str, Any]) -> Optional[_Preload]:
        """미리 올려 둔 것이 이 샷(같은 버전)이면 넘겨받는다. 풀던 것은 멈춘다."""
        pre = self._preload
        if pre is None or pre.prepared is None or not pre.matches(row):
            return None
        self._preload = None
        self._release_preload(pre)
        return pre

    def _drop_preload(self) -> None:
        pre, self._preload = self._preload, None
        self._release_preload(pre)

    def _release_preload(self, pre: Optional[_Preload]) -> None:
        self._preload_token += 1  # 늦게 오는 프레임·결과는 버린다
        if pre is not None and pre.decoder is not None:
            pre.decoder.stop()
            pre.decoder.wait(_WORKER_WAIT_MS)
            pre.decoder = None

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
        lut_a, lut_b, lut_post = self._lut_applies(buf), False, False
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
                lut_b = self._lut_applies(other)
                if lut_a == lut_b:
                    # 두 판의 색 상태가 같다 — 누크에서 뷰어 룩업을 켠 채 빼는 것과 같게:
                    # 값 그대로(선형에서) 빼고, 결과에만 뷰어 룩업을 씌운다
                    lut_a, lut_b, lut_post = False, False, lut_a
        self._view.set_image(SLOT_A, data, buf.size[0], buf.size[1])
        self._view.set_view(
            gain=self._gain_value(),
            gamma=self._gamma_value(),
            mode=mode,
            channel=self._channel,
            lut_on=lut_a,
            lut_b_on=lut_b,
            lut_post=lut_post,
            curve=self._curve,
            mask_bar=self._slate_bar(buf.size),
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
            out.append(f"Gain {self._gain_value():.2f}")
        if abs(self._gamma_value() - 1.0) > 1e-6:
            out.append(f"Gamma {self._gamma_value():.2f}")
        return out

    def _sync_labels(self) -> None:
        buf = self._bufs[self._shown]
        if buf.available:
            name = buf.path.stem if buf.path else ""
            at = self._buffer_index(buf)
            ready = buf.frames.get(at) is not None
            loading = "" if ready else "  올리는 중…"
            if not ready and buf.short_at is not None and at >= buf.short_at:
                last = self._frame_start + buf.short_at - 1
                loading = f"  그림 없음 — 파일이 {last} 까지만 있음"
            self._hud.setText(f"{buf.number} {buf.title}  {name}  {self.frame_number()}{loading}")
            self._hud.adjustSize()
            self._hud.show()
        changes = self._view_changes()
        notes = list(changes)
        if self._diff_note:
            notes.append(self._diff_note)
        if buf.resample != RESAMPLE_PLAIN:
            notes.append("누크 방식으로 줄임(선형 · Cubic)")
        if self._lut_on and self._lut is not None:
            forced = buf.key in self._lut_override
            why = "직접 정함" if forced else "자동"
            if not self._lut_wanted(buf):
                notes.append(f"룩이 입혀진 영상 — 룩업 안 씌움 ({why})")
            elif buf.key != KEY_ORG and not (self._annotation and buf.key == KEY_CUR):
                notes.append(f"로그 영상 — 룩업 씌움 ({why})")
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
        self._seq_follow()
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
        if self._annotation:
            step = _ANNOTATION_PLATE_TITLE
        self._ver_chip.setText(f"{step} {cur.version_label}".strip() if cur.available else "")
        self._ver_chip.setVisible(cur.available)
        who = (t.get("uploader_name") or t.get("version_uploader_name") or "").strip()
        status = (t.get("task_status") or "").strip()
        status_text = status
        if self._annotation:  # 샷 한 줄에 태스크가 여럿 — 태스크와 상태를 모두 보인다
            who = annotation_subtitle(t)
            status_text = annotation_status_text(t) or status
        self._who.setText(who)
        # 메모 칸 바탕을 지금 상태의 색으로 은은하게 — 어느 상태의 샷인지 한눈에 보이게.
        # Annotation 에서 태스크마다 상태가 다르면 한 색으로 말할 수 없어 물들이지 않는다.
        tint = status
        if self._annotation and len(set(t.get("task_statuses") or [status])) > 1:
            tint = ""
        self._panel.set_memo_status(tint)
        flash = self._status_flash
        if flash is not None and flash.get("task_id") != row_ident(t):
            flash = None  # 다른 샷으로 넘어갔다 — 이 샷의 강조가 아니다
        if flash is not None:  # 방금 보냈다 — 바뀐 것을 잠깐 크게 알린다
            code = str(flash.get("code") or "")
            bg, fg = status_style.colors(code) if code else (style.OK, style.EDGE)
            self._status_lbl.setText(str(flash.get("text") or ""))
            self._status_lbl.setStyleSheet(
                f"color: {fg}; background: {bg}; font-weight: bold; "
                f"padding: 2px 8px; border-radius: {style.RADIUS}px;"
            )
        else:
            self._status_lbl.setText(status_text)
            self._status_lbl.setStyleSheet(f"color: {status_style.text_color(status)};")
        self._status_dot.setVisible(bool(status))
        if status:
            self._status_dot.setPixmap(status_style.chip(status, 16))
        rows = self._nav_rows()
        idx = next((i for i, r in enumerate(rows) if row_ident(r) == row_ident(t)), -1)
        self._panel.set_nav(
            f"{idx + 1} / {len(rows)}" if idx >= 0 else "",
            idx > 0,
            0 <= idx < len(rows) - 1,
        )
        self._btn_shot_dir.setEnabled(self._shot_folder() is not None)
        self._btn_sg.setEnabled(t.get("shot_id") is not None)
        self._btn_list.setText(" " + (self._drawer.summary() or "목록"))
        for mode, btn in self._mode_btns.items():
            btn.setChecked((mode == MODE_ANNOTATION) == self._annotation)

    def _sync_all(self) -> None:
        # Annotation: 그림은 그린 영상에 딸린다 — 지금 보는 영상의 그림만 보이고 거기에 그려진다
        self._layer.set_source(self._source_of(self._shown))
        keys = [k for k, _n, _t in _BUFFER_DEFS if not self._annotation or k in _ANNOTATION_KEYS]
        for key, btn in self._buf_btns.items():
            buf = self._bufs[key]
            btn.setVisible(key in keys)
            btn.set_label(buf.button_label())
            btn.setEnabled(buf.available)
            btn.setToolTip(buf.tip())
            btn.setChecked(key == self._shown)
            mark = style.WARN if self._diff and key == self._last_shown else ""
            pos = "mid"
            if key in keys:
                pos = "first" if key == keys[0] else "last" if key == keys[-1] else "mid"
            if self._buf_marks.get(key, "") != mark or self._buf_pos.get(key) != pos:
                self._buf_marks[key], self._buf_pos[key] = mark, pos
                btn.setStyleSheet(style.segment_style(pos, mark_color=mark))
        self._btn_diff.setChecked(self._diff)
        for ch, btn in self._chan_btns.items():
            btn.setChecked(ch == self._channel)
        self._btn_lut.setChecked(self._lut_on)
        shown = self._bufs[self._shown]
        self._btn_lut_here.setEnabled(self._lut is not None and shown.available)
        self._btn_lut_here.setChecked(self._lut is not None and self._lut_wanted(shown))
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
        playing = self._playing or self._seq_playing
        style.set_icon(self._btn_play, "pause" if playing else "play", size=14)
        ready = bool(self._task.get("shot_id")) and cur.available and self._task_is_open()
        self._panel.set_sendable(
            ready and not self._submit_busy,
            "" if ready else "샷그리드 정보가 있는 샷에서만 보낼 수 있습니다",
        )
        # 샷 칸에 덧붙이기는 영상이 없어도 된다 — 샷그리드의 그 샷이 열려 있으면 된다
        self._panel.set_shot_text_enabled(bool(self._task.get("shot_id")) and self._task_is_open())
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
        if not title or (self._seq_quiet and not error):
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

    def _slate_bar(self, size: Tuple[int, int]) -> float:
        """슬레이트 가림이 켜져 있으면 위아래 띠 하나의 높이 몫, 꺼져 있으면 0."""
        return slate_bar(size[0], size[1]) if self._slate_on else 0.0

    def _toggle_slate(self) -> None:
        """편집본 슬레이트 자리(위아래 띠)를 가렸다 보였다 한다 — 단축키 S."""
        self._slate_on = not self._slate_on
        self._btn_slate.setChecked(self._slate_on)
        cur = self._bufs[self._shown]
        size = cur.size if cur.size[0] else self._bufs[KEY_CUR].size
        self._view.set_view(mask_bar=self._slate_bar(size))

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
        if self._seq_playing and tool != TOOL_SELECT:
            self._seq_pause()  # 그리려면 멈춘다 — 멈춘 컷이 열리고 그 위에 그린다
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
        """이 샷에 쓸 룩업 — 직접 골라 둔 것이 먼저, 없으면 프리셋 누크 틀의 룩업 노드 파일.

        같은 파일이 이미 올라와 있으면 그대로 둔다(끄고 켠 상태도 그대로).
        """
        saved = str(get_confirm_settings()["luts"].get(self._project_key() or "_default") or "")
        auto = self._standard.lut_path if self._standard is not None else ""
        want = saved or auto
        if not want:
            if self._lut is not None:
                self._show_standard()
            return
        if self._lut is not None and _same_file(want, self._lut_path):
            self._show_standard()
            return
        if _same_file(want, self._lut_failed):  # 못 읽은 파일을 샷마다 다시 알리지 않는다
            return
        self._apply_lut_file(want, remember=False)
        if not _same_file(want, self._lut_path):
            self._lut_failed = want
        self._show_standard()

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
        if self._seq is not None:  # 이어 재생의 컷들도 새 룩업으로 다시 가린다
            self._seq.set_lut(lut, bool(self._standard and self._standard.look))
        # 룩업이 바뀌면 룩이 입혀졌는지도 새 룩업으로 다시 가린다
        self._look_measured, self._look_tried = {}, set()
        self._measure_looks()
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
        if self._seq_playing and self._seq is not None:  # 재생 중에 타임라인을 눌렀다
            self._seq_pos = position(self._seq.counts(), self._seq_cut, index)
            self._seq_pause()
            return
        self._pause()
        self._set_index(index)

    def _on_frame_typed(self) -> None:
        try:
            frame = int(self._frame_edit.text().strip())
        except ValueError:
            frame = self.frame_number()
        if self._seq_playing and self._seq is not None:
            self._seq_pos = position(self._seq.counts(), self._seq_cut, frame - self._frame_start)
            self._seq_pause()
            self.setFocus()
            return
        self._pause()
        self._set_index(frame - self._frame_start)
        self.setFocus()
        self._sync_labels()

    def _on_scrub_started(self) -> None:
        if self._seq_playing:
            self._seq_pause()  # 화면을 누르면 멈춘다
        self._scrub_from = self._index

    def _on_scrub_moved(self, dx: float) -> None:
        """영상을 누른 채 좌우로 끌면 프레임을 넘긴다(RV 처럼). 한 프레임 = 화면 몇 픽셀."""
        if self._count <= 1:
            return
        per_frame = max(_SCRUB_MIN_PX, min(_SCRUB_MAX_PX, self._view.width() / self._count))
        self._pause()
        self._set_index(self._scrub_from + int(dx / per_frame))

    def _step(self, delta: int) -> None:
        if self._seq_playing:
            self._seq_pause()
            return
        self._pause()
        self._set_index(self._index + delta)

    def _go_first(self) -> None:
        if self._seq_playing:
            self._seq_pause()
            return
        self._pause()
        self._set_index(0)

    def _go_last(self) -> None:
        if self._seq_playing:
            self._seq_pause()
            return
        self._pause()
        self._set_index(self._count - 1)

    def _toggle_play(self) -> None:
        if self._seq is not None:  # 이어 재생 — 멈추면 그 컷이 열리고, 다시 누르면 거기서 잇는다
            if self._seq_playing:
                self._seq_pause()
            else:
                self._seq_play()
            return
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
        if self._seq_playing:
            self._seq_tick()
            return
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
            swapped = replace_memo_block(lines, old, new)
            if swapped is not None:
                lines = swapped
            elif new is not None:
                lines.extend(new.split("\n"))
            if new is None:
                del self._memo_lines[sid]
            else:
                self._memo_lines[sid] = new
            changed = True
        for sid, text in texts.items():
            if sid not in self._memo_lines:
                lines.extend(text.split("\n"))
                self._memo_lines[sid] = text
                changed = True
        if changed:
            self._panel.set_memo_text("\n".join(lines))
        self._show_attach_text()

    def _show_attach_text(self) -> None:
        frames, pasted = len(self._attachment_frames()), len(self._pasted)
        parts = []
        if frames:
            parts.append(f"그린 그림 {frames}장(샷 이름·버전·프레임 번호가 찍힘)")
        if pasted:
            parts.append(f"붙인 그림 {pasted}장")
        self._panel.set_attach_text(
            " + ".join(parts) + " 첨부" if parts else "그리거나 Ctrl+V 로 그림 첨부"
        )

    # ── 메모에 붙여 넣은 그림 ────────────────────────────────────

    def _on_image_pasted(self, image: object) -> None:
        """복사한 그림을 이 샷의 초안 폴더에 PNG 로 남기고 첨부 줄에 올린다."""
        base = self._draft_path()
        if not isinstance(image, QImage) or image.isNull():
            return
        if base is None:
            self._panel.set_result("영상을 연 뒤에 그림을 붙여 주세요", False)
            return
        img = image
        if max(img.width(), img.height()) > _NOTE_IMAGE_MAX_EDGE:
            img = img.scaled(
                _NOTE_IMAGE_MAX_EDGE,
                _NOTE_IMAGE_MAX_EDGE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        path = base.with_name(f"{base.stem}_paste_{time.time_ns() // 1000000}.png")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("confirm paste: folder failed: %s", e)
        if not img.save(str(path), "PNG"):
            self._panel.set_result("붙여 넣은 그림을 저장하지 못했습니다", False)
            return
        self._pasted.append(str(path))
        self._show_pasted()

    def _open_ref_dialog(self) -> None:
        """다른 샷의 프레임을 샷 이름으로 찾아 붙이는 작은 창을 띄운다."""
        if self._draft_path() is None:
            self._panel.set_result("영상을 연 뒤에 그림을 붙여 주세요", False)
            return
        if self._ref_dialog is not None:
            self._ref_dialog.close()
            self._ref_dialog.deleteLater()
        project = self._project_key() or self._drawer.project_text()
        shot = str(self._task.get("shot_code") or "")
        hint = shot.split("_")[0] + "_" if "_" in shot else ""
        dlg = RefFrameDialog(
            self,
            find_sources=lambda name, p=project: _find_ref_sources(p, name),
            lut_file=self._lut_path if self._lut is not None else "",
            frame_start=self._frame_start,
            shot_hint=hint,
        )
        dlg.frame_picked.connect(self._on_ref_frame)
        self._ref_dialog = dlg
        dlg.show()

    def _on_ref_frame(self, image: object, caption: str) -> None:
        """고른 프레임을 붙인 그림으로 올리고, 어느 샷의 것인지 메모에 한 줄 적는다."""
        before = len(self._pasted)
        self._on_image_pasted(image)
        if len(self._pasted) > before and caption:
            self._panel.append_memo(caption)
            self._draft_timer.start()

    def _remove_pasted(self, index: int) -> None:
        if 0 <= index < len(self._pasted):
            self._remove_files([self._pasted.pop(index)])
            self._show_pasted()

    def _show_pasted(self) -> None:
        self._panel.set_pasted_images(self._pasted)
        self._show_attach_text()
        self._draft_timer.start()

    def _insert_failures(self) -> None:
        for line in failure_lines(self._checks):
            self._panel.append_memo(line)

    def _source_of(self, key: str) -> str:
        """판 → 그린 영상 이름. Annotation 에서만 가린다(원본은 「현재버전」 자리에 올라와 있다)."""
        if not self._annotation:
            return ""
        return SOURCE_EDIT if key == KEY_EDIT else SOURCE_PLATE

    def _key_of(self, source: str) -> str:
        return KEY_EDIT if source == SOURCE_EDIT else KEY_CUR

    def _attachment_marks(self) -> List[Tuple[str, int]]:
        """노트에 붙일 그림 한 장씩 — ``(판, 프레임)``. Confirm 에서는 늘 현재버전 판이다."""
        doc = self._layer.doc()
        if not self._annotation:
            return [(KEY_CUR, f) for f in doc.marked_frames()]
        return [(self._key_of(src), f) for src, f in doc.marked_sources()]

    def _attachment_frames(self) -> List[int]:
        return [f for _key, f in self._attachment_marks()]

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
            if doc.is_empty() and not memo.strip() and not self._pasted:
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
                        "images": list(self._pasted),
                    },
                )
        except OSError as e:
            logger.warning("confirm draft save failed: %s", e)

    def _load_draft(self) -> None:
        path = self._draft_path()
        doc = AnnotationDoc()
        memo, lines = "", {}
        images: List[str] = []
        if path is not None:
            data = read_json_file(path, {})
            if isinstance(data, dict):
                stored_images = data.get("images")
                if isinstance(stored_images, list):
                    images = [str(p) for p in stored_images if p and Path(str(p)).is_file()]
                doc.load_list(data.get("shapes"))
                memo = str(data.get("memo") or "")
                stored = data.get("memo_lines")
                if isinstance(stored, dict):
                    lines = {int(k): str(v) for k, v in stored.items() if str(k).isdigit()}
        self._memo_lines = lines
        self._pasted = images
        self._panel.set_pasted_images(images)
        self._panel.set_memo_text(memo)
        self._layer.set_doc(doc)
        self._timeline.set_marks(doc.marked_frames())
        self._sync_memo()

    def _render_note_images(self) -> List[str]:
        """그림을 남긴 프레임마다 노트용 PNG 를 임시 폴더에 만든다.

        Annotation 에서는 그림을 그린 그 영상(원본 / edit)의 프레임 위에 찍는다.
        """
        cur = self._bufs[KEY_CUR]
        doc = self._layer.doc()
        out: List[str] = []
        self._note_image_meta = {}
        shot = (self._task.get("shot_code") or (cur.path.stem if cur.path else "")).strip()
        for key, frame in self._attachment_marks():
            buf = self._bufs[key]
            if not buf.available:
                continue
            # 영상마다 길이가 다를 수 있다(원본은 앞뒤 여유분) — 순번은 그 영상 기준으로 센다
            index = max(0, min(frame - self._frame_start, (buf.frame_count() or self._count) - 1))
            data = buf.frames.get(index)
            if data is None:
                continue
            img = self._view.render_frame_image(
                data,
                buf.size[0],
                buf.size[1],
                lut_on=self._lut is not None and self._lut_wanted(buf),
            )
            if img is None:
                continue
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            p = QPainter(img)
            rect = (0.0, 0.0, float(img.width()), float(img.height()))
            shapes = [
                s
                for s in doc.shapes()
                if s["frame"] == frame
                and (not self._annotation or self._key_of(source_of(s)) == key)
            ]
            paint_shapes(p, shapes, rect)
            label = f"{shot}  {buf.version_label or buf.title}  프레임 {frame}"
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
                self._note_image_meta[tmp] = (self._source_of(key), index)
        self._refresh_view()
        return out

    # ── 샷그리드 ────────────────────────────────────────────────

    def _fill_work_info(self) -> None:
        t = self._task
        cur = self._bufs[KEY_CUR]
        who = (t.get("uploader_name") or t.get("version_uploader_name") or "").strip()
        meta = " · ".join(x for x in (who, cur.version_label, t.get("task_status") or "") if x)
        if self._annotation and t:
            meta = annotation_subtitle(t) or "태스크 정보 없음"
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
        self._load_note_images(result, token)

    def _load_note_images(self, notes: List[Dict[str, Any]], token: int) -> None:
        """샷그리드 노트에 붙은 그림을 뒤에서 내려받아 Note 목록에 보인다."""
        ids = [
            int(n["note_id"]) for n in notes if isinstance(n, dict) and n.get("note_id") is not None
        ][:_NOTE_IMAGE_NOTES]
        if not ids:
            return

        def _fetch() -> Dict[int, List[bytes]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.confirm_context import note_images

            return note_images(get_default_sg(), ids)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, t=token: self._on_note_images(r, t))
        w.error.connect(lambda e: logger.warning("confirm: note images failed: %s", e))
        w.start()
        self._workers.append(w)

    def _on_note_images(self, result: object, token: int) -> None:
        if token != self._load_token or self._closed or not isinstance(result, dict):
            return
        self._panel.set_note_images(result)

    def _on_past_note(self, note: Dict[str, Any]) -> None:
        """지난 지적을 누르면 — 그 버전(전 버전 판에 있으면)과 지금 버전을 바로 비교하게 한다."""
        code = str(note.get("version_code") or "")
        prev = self._bufs[KEY_PREV]
        if prev.available and prev.path is not None and code and code in prev.path.stem:
            self._last_shown = KEY_CUR
            self._shown = KEY_PREV
            self._diff = False
            self._sync_all()

    def _task_is_open(self) -> bool:
        """머리 줄의 샷과 화면에 올라와 있는 영상이 같은 샷인가.

        목록에서 다른 샷을 고르면 머리 줄은 바로 바뀌지만 영상은 서버에서 찾은 뒤에야 바뀐다.
        그 사이와, 새 샷의 영상을 못 찾았을 때는 화면의 메모·그림이 앞 샷 것이라 보내면 안 된다.
        """
        return row_ident(self._task) == self._loaded_task_id

    def _on_note_requested(self) -> None:
        """Annotation 모드의 「Note 보내기」 — 상태는 그대로 두고 메모·그림만 보낸다."""
        if self._submit_busy or not self._task.get("shot_id") or not self._task_is_open():
            return
        self._layer.commit_text_edit()  # 화면에 치던 글도 노트에 들어가게
        if not (self._panel.memo_text().strip() or self._attachment_frames() or self._pasted):
            self._panel.set_result("메모를 쓰거나 그림을 남긴 뒤 보내 주세요", False)
            return
        self._on_status_requested("")

    def _on_status_requested(self, code: str) -> None:
        if self._submit_busy or not self._task.get("shot_id") or not self._task_is_open():
            return
        self._layer.commit_text_edit()  # 화면에 치던 글도 노트에 들어가게
        self._pending_status = code
        self._pending_left = _SEND_DELAY_SECS
        self._sent_note_id = None
        self._panel.set_result("", True)
        self._show_pending()
        self._send_timer.start()

    def _pending_summary(self) -> str:
        lines = sum(1 for ln in self._panel.memo_text().split("\n") if ln.strip())
        frames = len(self._attachment_frames()) + len(self._pasted)
        if not lines and not frames:
            return f"상태만 {self._pending_status} 로 바꿈 (태스크·버전)"
        warn = f" · {self._version_note}" if self._version_note else ""
        cc = len(self._panel.cc_users())
        cc_text = f", 참조 {cc}명" if cc else ""
        if not self._pending_status:
            to = len(self._task.get("task_assignees") or [])
            to_text = f"담당 {to}명에게" if to else "받는 사람 없이"
            return f"노트(메모 {lines}줄, 그림 {frames}장{cc_text}) {to_text} 보냄 · 상태는 그대로"
        return (
            f"노트(메모 {lines}줄, 그림 {frames}장{cc_text}) 보내고 "
            f"상태 {self._pending_status}{warn}"
        )

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
        r = self._retry
        if r is None or not r.get("code") or r.get("note_id") is None:
            return
        # 보냈던 그 샷의 상태를 다시 바꾼다(그 사이 다른 샷을 열었어도 그 샷으로)
        self._submit(str(r["code"]), existing_note_id=int(r["note_id"]), task=dict(r["task"]))

    def _submit(
        self,
        code: str,
        existing_note_id: Optional[int] = None,
        task: Optional[Dict[str, Any]] = None,
    ) -> None:
        if task is None and not self._task_is_open():
            self._panel.set_result("샷이 바뀌어 보내지 않았습니다", False)
            return
        t = dict(task if task is not None else self._task)
        # 결과가 돌아올 때 어느 샷의 것인지 알도록 같이 들려 보낸다
        ticket: Dict[str, Any] = {
            "task_id": t.get("task_id"),
            "ident": row_ident(t),
            "shot": str(t.get("shot_code") or ""),
            "draft": self._draft_path() if task is None else None,
            "retry": existing_note_id is not None,
            "code": code,
            "task": t,
        }
        body = self._panel.memo_text().strip()
        frames = self._attachment_frames() if existing_note_id is None else []
        images = self._render_note_images() if existing_note_id is None else []
        pasted = list(self._pasted) if existing_note_id is None else []
        cc = self._panel.cc_users()
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
        # Annotation: 샷그리드에서 직접 그려 올린 노트와 같은 자리(edit·org 버전)에, 같은 그림
        # 이름으로 보낸다 — 그래야 guide 봇이 집어 가 샷 목록의 guide 칸에 뜬다
        guide: Optional[Dict[str, Any]] = None
        if self._annotation and task is None and existing_note_id is None:
            plate, edit = self._bufs[KEY_CUR], self._bufs[KEY_EDIT]
            guide = {
                "codes": {
                    SOURCE_PLATE: plate.path.stem if plate.path is not None else "",
                    SOURCE_EDIT: edit.path.stem if edit.path is not None else "",
                },
                "drawn": sorted({src for src, _f in self._layer.doc().marked_sources()}),
                "shown": self._source_of(self._shown),
                "items": [(p, self._note_image_meta[p][1]) for p in images],
            }

        def _work() -> Any:
            from bpe.shotgrid.confirm_submit import (
                addressings_for_confirm,
                guide_note_target,
                note_subject,
                open_submit_session,
                submit_confirm,
            )

            sg, me = open_submit_session()
            version_id, version_code, paths = t.get("latest_version_id"), cur_code, images
            # 노트에는 그 버전의 태스크를 건다 — Confirm 은 확인하는 태스크, Annotation 은 아래에서
            # 고른 edit·org 버전의 태스크
            note_task_id = t.get("task_id") if guide is None else None
            staged = ""
            if guide is not None:
                _src, ver = guide_note_target(
                    sg,
                    int(t["shot_id"]),
                    codes=guide["codes"],
                    drawn=guide["drawn"],
                    shown=guide["shown"],
                )
                if ver is not None:
                    version_id, version_code = int(ver["id"]), str(ver["code"])
                    note_task_id = ver.get("task_id")
                    ticket["note_version"] = version_code
                    staged = tempfile.mkdtemp(prefix="bpe_annot_")
                    paths = stage_annot_files(guide["items"], version_id, Path(staged))
            try:
                return submit_confirm(
                    sg,
                    project_id=int(t["project_id"]),
                    shot_id=int(t["shot_id"]),
                    version_id=version_id,
                    task_id=t.get("task_id"),
                    status_code=code,
                    status_field=(t.get("status_field") or None),
                    subject=note_subject(me, version_code, (t.get("shot_code") or "").strip()),
                    content=body,
                    attachment_paths=paths + pasted,
                    author_user=me,
                    addressings_to=addressings_for_confirm(t.get("task_assignees")),
                    addressings_cc=cc or None,
                    existing_note_id=existing_note_id,
                    note_task_id=note_task_id,
                    # Annotation 노트에는 쓴 글만 — 글이 없어도 대신 넣는 글이 없다
                    **({"empty_note_text": ""} if guide is not None else {}),
                )
            finally:
                if staged:
                    shutil.rmtree(staged, ignore_errors=True)

        w = ShotGridWorker(_work)
        w.finished.connect(
            lambda r, imgs=images, p=pasted, tk=ticket: self._on_submitted(r, imgs, p, tk)
        )
        w.error.connect(lambda e, imgs=images, tk=ticket: self._on_submit_error(e, imgs, tk))
        w.start()
        self._workers.append(w)

    @staticmethod
    def _remove_files(paths: List[str]) -> None:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    # ── 샷의 글 칸에 덧붙이기(Annotation: VFX work order · Description) ──────

    def _load_shot_text(self) -> None:
        """오른쪽 칸의 샷 칸 글을 지금 샷에 적혀 있는 글로 채운다."""
        self._shot_text_base = {}
        for kind in KINDS:
            text = clean_text(str(self._task.get(KIND_ROW_KEYS[kind]) or ""))
            self._shot_text_base[kind] = text
            self._panel.set_shot_text(kind, text)

    def _on_shot_text_requested(self, kind: str, text: str) -> None:
        """오른쪽 칸의 「적용」 — 샷그리드 샷의 그 칸을 지금 칸의 글 그대로 바꾼다(노트와 따로)."""
        t = self._task
        if kind in self._shot_text_busy or not t.get("shot_id") or not self._task_is_open():
            return
        base = self._shot_text_base.get(kind, "")
        new = clean_text(text)
        if same_text(new, base):
            self._panel.set_shot_text_result("바뀐 글이 없습니다", False)
            return
        shot_id = int(t["shot_id"])
        ticket = {
            "task_id": t.get("task_id"),
            "ident": row_ident(t),
            "shot_id": shot_id,
            "shot": str(t.get("shot_code") or ""),
            "kind": kind,
        }
        self._shot_text_busy.add(kind)
        self._panel.set_shot_text_busy(kind, True)
        self._panel.set_shot_text_result("", True)

        def _work() -> Tuple[bool, str]:
            from bpe.shotgrid.confirm_submit import open_submit_session
            from bpe.shotgrid.shot_text import apply_shot_text

            sg, _me = open_submit_session()
            # 칸에 불러와 있던 글(base)과 샷그리드의 지금 글이 다르면 바꾸지 않고 그 글을 돌려준다
            return apply_shot_text(sg, shot_id, kind, new, expected=base)

        w = ShotGridWorker(_work)
        w.finished.connect(lambda r, tk=ticket: self._on_shot_text_saved(r, tk))
        w.error.connect(lambda e, tk=ticket: self._on_shot_text_failed(e, tk))
        w.start()
        self._workers.append(w)

    def _on_shot_text_saved(self, result: object, ticket: Dict[str, Any]) -> None:
        kind = str(ticket.get("kind") or "")
        self._shot_text_busy.discard(kind)
        if self._closed:
            return
        self._panel.set_shot_text_busy(kind, False)
        applied, value = True, result
        if isinstance(result, tuple) and len(result) == 2:
            applied, value = bool(result[0]), result[1]
        text = clean_text(str(value or ""))
        here = self._result_is_for_open_shot(ticket)
        key = KIND_ROW_KEYS[kind]
        # 목록의 그 줄에도 샷그리드의 글을 적어 둔다 — 다시 열었을 때 옛 글이 보이지 않게
        self._drawer.set_row_values(ticket.get("task_id"), {key: text}, ticket.get("shot_id"))
        if here:
            self._task[key] = text
            self._fill_work_info()
            self._shot_text_base[kind] = text
            self._panel.set_shot_text(kind, text)
        label = KIND_LABELS.get(kind, kind)
        if applied:
            note = f"샷그리드 {label} 칸에 적용했습니다"
        else:  # 그 사이 다른 사람이 고쳤다 — 덮어쓰지 않고 지금 글을 다시 보여 준다
            note = (
                f"그 사이 샷그리드의 {label} 글이 바뀌어 적용하지 않았습니다 — "
                "지금 글을 불러왔으니 확인하고 다시 적용해 주세요"
            )
        self._panel.set_shot_text_result(self._named(ticket, here, note), applied)

    def _on_shot_text_failed(self, msg: str, ticket: Dict[str, Any]) -> None:
        kind = str(ticket.get("kind") or "")
        self._shot_text_busy.discard(kind)
        if self._closed:
            return
        self._panel.set_shot_text_busy(kind, False)
        here = self._result_is_for_open_shot(ticket)
        label = KIND_LABELS.get(kind, kind)
        # 쓰던 글은 칸에 그대로 둔다 — 다시 누르면 된다
        self._panel.set_shot_text_result(
            self._named(ticket, here, f"{label} 적용 실패: {msg}"), False
        )

    def _result_is_for_open_shot(self, ticket: Optional[Dict[str, Any]]) -> bool:
        """돌아온 보내기 결과가 지금 열려 있는 샷의 것인가(그 사이 다른 샷으로 넘어갔을 수 있다)."""
        if ticket is None:
            return True
        ident = ticket.get("ident", ticket.get("task_id"))
        return ident == row_ident(self._task) and self._task_is_open()

    @staticmethod
    def _named(ticket: Optional[Dict[str, Any]], here: bool, text: str) -> str:
        """다른 샷의 결과면 어느 샷 것인지 앞에 적는다."""
        shot = str((ticket or {}).get("shot") or "")
        return text if here or not shot else f"{shot}: {text}"

    def _on_submit_error(
        self, msg: str, images: List[str], ticket: Optional[Dict[str, Any]] = None
    ) -> None:
        self._remove_files(images)
        self._submit_busy = False
        here = self._result_is_for_open_shot(ticket)
        self._panel.set_result(self._named(ticket, here, f"보내지 못했습니다: {msg}"), False)
        self._sync_all()

    def _on_submitted(
        self,
        res: Any,
        images: List[str],
        pasted: Optional[List[str]] = None,
        ticket: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._remove_files(images)
        self._submit_busy = False
        # 보내는 사이 다른 샷으로 넘어갔으면 지금 화면(그 샷의 메모·그림·상태)은 건드리지 않는다
        here = self._result_is_for_open_shot(ticket)
        retry = bool((ticket or {}).get("retry"))  # 상태만 다시 바꾼 것 — 노트는 전에 갔다
        parts: List[str] = []
        fresh_note = False
        if res.note_needed and not retry:
            if res.note_ok:
                if here:
                    fresh_note = self._sent_note_id != res.note_id
                    self._sent_note_id = res.note_id
                sent = list(pasted or [])
                if not res.attachment_ok:
                    # 글은 갔지만 그림이 안 올라갔다 — 그린 그림·붙인 그림은 지우지 않는다
                    parts.append(
                        f"노트 보냄(그림 실패: {res.attachment_error}) — 그림은 남겨 두었습니다"
                    )
                    if here:
                        self._memo_lines = {}
                        self._panel.clear_memo()
                        self._panel.clear_cc()
                else:
                    where = str((ticket or {}).get("note_version") or "")
                    parts.append(f"노트 보냄 → {where}" if where else "노트 보냄")
                    # 보낸 붙임 그림은 지운다(다른 샷으로 넘어간 뒤 끝났어도 그 파일만)
                    self._remove_files(sent)
                    self._pasted = [p for p in self._pasted if p not in sent]
                    if here:
                        self._memo_lines = {}
                        self._panel.clear_memo()
                        self._panel.set_pasted_images(self._pasted)
                        self._panel.clear_cc()
                        self._layer.set_doc(AnnotationDoc())
                        self._on_doc_changed()
                    else:
                        # 떠나면서 남긴 그 샷의 초안 — 이미 보냈으니 다시 열 때
                        # 또 나오지 않게 지운다
                        self._remove_files([str(p) for p in [(ticket or {}).get("draft")] if p])
            else:
                parts.append(f"노트 실패: {res.note_error}")
        code = str(ticket["code"]) if ticket is not None else self._last_status_code
        old_status = str(self._task.get("task_status") or "") if here else ""
        if res.status_needed:
            if res.status_ok:
                parts.append(f"태스크 상태 {code} 로 바꿈")
                if here:
                    self._task["task_status"] = code
            else:
                parts.append(f"태스크 상태 실패: {res.status_error}")
        if res.version_needed:
            if res.version_ok:
                parts.append(f"버전 상태 {code} 로 바꿈({res.version_count}개)")
            else:
                parts.append(f"버전 상태 실패: {res.version_error}")
        status_failed = bool(res.status_needed and not res.status_ok)
        version_failed = bool(res.version_needed and not res.version_ok)
        note_fine = res.note_ok or not res.note_needed
        can_retry = bool((status_failed or version_failed) and note_fine)
        self._retry = None
        if can_retry:  # 다시 바꿀 때는 보냈던 그 샷의 값으로
            sent_task = (ticket or {}).get("task") or dict(self._task)
            self._retry = {"task": dict(sent_task), "code": code, "note_id": res.note_id}
        text = " · ".join(parts) or "보낼 것이 없습니다"
        self._panel.set_result(self._named(ticket, here, text), res.all_ok, can_retry=can_retry)
        # 바뀐 것이 눈에 보이게 — 목록의 그 줄은 바로 「보냄」(다른 샷으로 넘어간 뒤 끝났어도),
        # 지금 열린 샷이면 머리 줄 상태 칸도 잠깐 강조한다
        status_done = bool(res.status_needed and res.status_ok)
        note_done = bool(res.note_needed and res.note_ok and not retry)
        if status_done or note_done:
            sent_task = (ticket or {}).get("task") or self._task
            self._drawer.mark_sent(
                sent_task.get("task_id"), code if status_done else "", sent_task.get("shot_id")
            )
            if here:
                if status_done and old_status and old_status != code:
                    self._flash_status(f"{old_status} → {code}", code)
                elif status_done:
                    self._flash_status(code, code)
                else:
                    self._flash_status("Note 보냄", "")
        if here:
            self._fill_work_info()
        self._sync_all()
        if fresh_note:
            # 방금 보낸 노트가 이 샷의 Note 목록에 바로 보이게 다시 읽는다
            self._load_sg_context()

    def _flash_status(self, text: str, code: str) -> None:
        """머리 줄 상태 칸을 잠깐 강조한다 — *code* 의 상태 색으로, 없으면 초록(Note 만 보냄)."""
        self._status_flash = {"task_id": row_ident(self._task), "text": text, "code": code}
        self._flash_timer.start()
        self._sync_header()

    def _end_status_flash(self) -> None:
        self._flash_timer.stop()
        if self._status_flash is None:
            return
        self._status_flash = None
        if not self._closed:
            self._sync_header()

    def _with_sent_status(self, task: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """목록에서 온 줄을 여는 값으로 — 이 창에서 보내 바꾼 상태가 있으면 그것이 지금 상태다."""
        row = dict(task or {})
        sent = str(row.get("sent_status") or "") or self._drawer.sent_status_of(row.get("task_id"))
        if sent:
            row["task_status"] = sent
        return row

    # ── 참조(CC) 사람 찾기 ───────────────────────────────────────

    def _search_cc(self, text: str) -> None:
        self._cc_req += 1
        req = self._cc_req

        def _fetch() -> List[Dict[str, Any]]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.users import search_human_users

            return search_human_users(get_default_sg(), text, limit=8)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r, q=req: self._on_cc_found(r, q))
        w.error.connect(lambda e: logger.warning("confirm: cc search failed: %s", e))
        w.start()
        self._workers.append(w)

    def _on_cc_found(self, rows: object, req: int) -> None:
        if req != self._cc_req or self._closed:
            return
        self._panel.set_cc_results(rows if isinstance(rows, list) else [])

    # ── 바로 가기 ────────────────────────────────────────────────

    def _shot_folder(self) -> Optional[Path]:
        """이 샷의 작업 폴더 — 샷 폴더를 못 찾았으면 지금 보는 영상이 든 폴더."""
        if self._shot_root is not None:
            return self._shot_root
        cur = self._bufs[KEY_CUR].path
        return cur.parent if cur is not None else None

    def _open_shot_folder(self) -> None:
        folder = self._shot_folder()
        if folder is None or not folder.is_dir():
            self._panel.set_result("샷 폴더를 찾지 못했습니다", False)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_shot_in_shotgrid(self) -> None:
        shot_id = self._task.get("shot_id")
        if shot_id is None:
            return
        from bpe.gui.shotgrid_open_shot import open_shot_canvas_in_browser

        open_shot_canvas_in_browser(int(shot_id))

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
        elif ctrl and letter == "C" and self._panel.copy_note_selection():
            pass  # 지난 Note 에서 끌어 고른 글을 복사했다
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
        elif key == Qt.Key.Key_PageUp:
            self._nav_shot(-1)
        elif key == Qt.Key.Key_PageDown:
            self._nav_shot(1)
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
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._toggle_lut_here()
            else:
                self._toggle_lut()
        elif letter == "F":
            self._view_fit()
        elif letter == "H":
            self._view_fill()
        elif letter == "S":
            self._toggle_slate()
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
        self._stop_sequence()
        if self._ref_dialog is not None:
            self._ref_dialog.close()
        self._pause()
        self._send_timer.stop()
        self._flash_timer.stop()
        self._save_draft()
        self._stop_decoders()
        self._drop_preload()
        self._drawer.shutdown()
        self._view.release_gl()  # 그래픽 물건은 지금 지운다(뒷정리에 맡기면 죽는다)
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
