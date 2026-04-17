"""My Tasks tab — ShotGrid comp task list with thumbnails, NukeX open, shot folder."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QIntValidator,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.core.nk_finder import (
    find_latest_comp_version_display,
    find_latest_nk_and_open,
    find_server_root_auto,
    find_shot_folder,
    open_comp_render_in_rv,
    open_plate_in_rv,
)
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.shotgrid_browser import build_project_overview_url, try_launch_chrome_app_url
from bpe.core.shotgrid_settings import get_shotgrid_settings
from bpe.gui import theme
from bpe.gui.shotgrid_open_shot import setup_copy_shot_name_button, setup_shotgrid_open_shot_button
from bpe.gui.widgets.clickable_image import ClickableImage
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.notes import (
    download_attachment_bytes,
    get_note_attachments,
    list_notes_for_project,
    list_notes_for_shots,
)
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.shots import find_shot, search_shots_by_code_prefix
from bpe.shotgrid.tasks import (
    BELUCA_TASK_STATUS_PRESETS,
    fetch_representative_my_tasks_row_for_project_shot,
    list_comp_tasks_for_project_user,
    load_my_tasks_all_tasks_bundle,
)
from bpe.shotgrid.users import guess_human_user_for_me, list_project_assignees, search_human_users
from bpe.shotgrid.versions import list_versions_for_shot

logger = get_logger("gui.tabs.my_tasks_tab")

_AUTOCOMPLETE_DELAY = 350
# 담당자 입력란: 기본 너비 + ~1.5cm @ 96dpi (대략 57px)
_ASSIGNEE_EDIT_WIDTH = 200 + int(round(96 / 2.54 * 1.5))
_THUMB_W = 160
_THUMB_H = 110
_VERSION_THUMB_W = 56
_VERSION_THUMB_H = 42
# 샷 카드 접힘 높이(오른쪽 노트 카드 약 1.5개 분량). 펼치면 워크오더 영역만 확장
_CARD_COLLAPSED_H = 230
_VFX_TEXT_H_COLLAPSED = 75
_VFX_TEXT_H_EXPANDED = 300
_QWIDGETSIZE_MAX = 16777215

_SPINNER_FRAMES: Tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

# 상태 필터 버튼 순서 (ALL 제외) — shotgrid 프리셋과 동기화
_STATUS_ORDER = [code for code, _ in BELUCA_TASK_STATUS_PRESETS]

_SORT_MODE_SHOT = 0
_SORT_MODE_DELIVERY = 1


def _format_human_user_display(u: Dict[str, Any]) -> str:
    """담당자 표시: '이름 로그인 (이메일)' (ShotGrid HumanUser dict)."""
    name = (u.get("name") or "").strip()
    login = (u.get("login") or "").strip()
    email = (u.get("email") or "").strip()
    if name and login and email:
        return f"{name} {login} ({email})"
    if name and login:
        return f"{name} {login}"
    if name and email:
        return f"{name} ({email})"
    if login and email:
        return f"{login} ({email})"
    return name or login or email or ""


def _pick_user_for_enter_resolve(
    users: List[Dict[str, Any]], query: str
) -> Optional[Dict[str, Any]]:
    """엔터 확정: 유일 후보이거나 이름/로그인이 검색어와 정확히 일치하는 한 명만 자동 선택."""
    q = (query or "").strip().lower()
    if not users:
        return None
    if len(users) == 1:
        return users[0]
    exact: List[Dict[str, Any]] = []
    for u in users:
        name = (u.get("name") or "").strip().lower()
        login = (u.get("login") or "").strip().lower()
        if q and (name == q or login == q):
            exact.append(u)
    if len(exact) == 1:
        return exact[0]
    return None


def _status_cell_colors(status_code: str) -> Tuple[str, str]:
    return theme.task_status_badge_colors(status_code)


def _hex_to_rgba(bg_hex: str, alpha: float) -> str:
    """#RRGGBB -> rgba() for muted status bars."""
    h = (bg_hex or "").lstrip("#")
    if len(h) != 6:
        return f"rgba(90, 90, 90, {alpha})"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return f"rgba(90, 90, 90, {alpha})"
    return f"rgba({r},{g},{b},{alpha})"


def _version_status_bar_style(bg_hex: str, fg_hex: str, alpha: float = 0.42) -> str:
    bg = _hex_to_rgba(bg_hex, alpha)
    return (
        f"background-color: {bg}; color: {fg_hex}; padding: 4px 8px; "
        f"border-radius: 4px; font-weight: 600; border: none;"
    )


def _normalize_version_description_for_display(text: str) -> str:
    """줄 단위로 UNC를 드라이브 경로로 바꿔 사용자에게 표시한다."""
    lines = text.splitlines()
    out: List[str] = []
    for line in lines:
        if line.strip():
            out.append(normalize_path_str(line))
        else:
            out.append(line)
    return "\n".join(out)


_VERSION_DESC_EDIT_MAX_H = 90


def _status_bg_luminance(bg: str) -> float:
    """#RRGGBB 밝기 (0~255 근사). 파싱 실패 시 중간값."""
    h = bg.lstrip("#")
    if len(h) != 6:
        return 128.0
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 128.0
    return 0.299 * r + 0.587 * g + 0.114 * b


def _inactive_status_label_color(bg: str, fg: str) -> str:
    """비활성 버튼 글자색 — 기존은 상태 bg 색. 패널과 겹쳐 안 보이는 어두운 bg(fin 등)만 fg."""
    if _status_bg_luminance(bg) < 60.0:
        return fg
    return bg


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


def _natural_sort_key(s: str) -> List[Any]:
    """샷 코드 자연 정렬(숫자 구간은 정수 비교)."""
    out: List[Any] = []
    for p in re.split(r"(\d+)", s):
        if p == "":
            continue
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(p.lower())
    return out


def _normalize_task_status(t: Dict[str, Any]) -> str:
    return (t.get("task_status") or "").strip().lower()


def _version_cache_key(t: Dict[str, Any]) -> str:
    shot = (t.get("shot_code") or "").strip()
    proj = (t.get("project_code") or t.get("project_folder") or "").strip()
    return f"{shot}\x00{proj}"


def _filter_tasks_by_status(tasks: List[Dict[str, Any]], active: str) -> List[Dict[str, Any]]:
    if active == "all":
        return list(tasks)
    return [t for t in tasks if _normalize_task_status(t) == active]


def _filter_tasks_by_tag(
    tasks: List[Dict[str, Any]], tag_sel: Optional[str]
) -> List[Dict[str, Any]]:
    if not tag_sel:
        return list(tasks)
    needle = tag_sel.strip().lower()
    if not needle:
        return list(tasks)
    out: List[Dict[str, Any]] = []
    for t in tasks:
        tags = t.get("shot_tags")
        if not isinstance(tags, list):
            continue
        if any(str(x).strip().lower() == needle for x in tags):
            out.append(t)
    return out


def _sort_tasks_by_mode(
    tasks: List[Dict[str, Any]], mode: int, ascending: bool
) -> List[Dict[str, Any]]:
    if not tasks:
        return []
    if mode == _SORT_MODE_DELIVERY:
        return sorted(tasks, key=_task_delivery_sort_key, reverse=not ascending)

    def _shot_key(t: Dict[str, Any]) -> List[Any]:
        return _natural_sort_key((t.get("shot_code") or "").strip())

    return sorted(tasks, key=_shot_key, reverse=not ascending)


def _parse_delivery_date_for_sort(val: Any) -> Optional[date]:
    """delivery_date 원시값을 date로 변환. 실패·없음은 None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, dict):
        inner = val.get("date") or val.get("name") or val.get("value")
        if inner is None:
            return None
        return _parse_delivery_date_for_sort(inner)
    s = str(val).strip()
    if not s or s == "—":
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    return None


def _task_delivery_sort_key(t: Dict[str, Any]) -> Tuple[int, date, int, str]:
    """촉박한 순: 유효 날짜 오름차순, 날짜 없음은 맨 뒤. 동률은 task_id → shot_code."""
    d = _parse_delivery_date_for_sort(t.get("delivery_date"))
    tid = t.get("task_id")
    try:
        tid_i = int(tid) if tid is not None else 0
    except (TypeError, ValueError):
        tid_i = 0
    sc = (t.get("shot_code") or "").strip()
    if d is None:
        return (1, date.max, tid_i, sc)
    return (0, d, tid_i, sc)


def sort_tasks_by_delivery_urgency(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Delivery date 가까운 순(오름차순). 날짜 없는 항목은 뒤로."""
    return sorted(tasks, key=_task_delivery_sort_key)


def _vline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(1)
    line.setMinimumHeight(_THUMB_H)
    line.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
    return line


class _NoteCardFrame(QFrame):
    """Note row; click (except image thumbnails) scrolls the shot list to the linked shot."""

    def __init__(
        self,
        shot_ids: List[int],
        on_navigate: Callable[[List[int]], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._shot_ids = shot_ids
        self._on_navigate = on_navigate
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def wire_click_filters(self) -> None:
        """Install filters after children are attached; ClickableImage / QPushButton 제외."""
        for w in self.findChildren(QWidget):
            if isinstance(w, ClickableImage):
                continue
            if isinstance(w, QPushButton):
                continue
            if isinstance(w, QLabel) and (
                w.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
            ):
                continue
            w.installEventFilter(self)

    def eventFilter(self, obj: object, event: object) -> bool:
        if isinstance(obj, ClickableImage):
            return False
        if isinstance(obj, QPushButton):
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                self._on_navigate(self._shot_ids)
                return True
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_navigate(self._shot_ids)
        super().mousePressEvent(event)


class _ShotCard(QFrame):
    """Single shot card widget inside the task list."""

    def __init__(
        self,
        task_data: Dict[str, Any],
        publish_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        shot_builder_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        select_callback: Optional[Callable[["_ShotCard"], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.task_data = task_data
        self._publish_callback = publish_callback
        self._shot_builder_callback = shot_builder_callback
        self._select_callback = select_callback
        self._vlines: List[QFrame] = []
        self._vfx_expanded = False
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(task_data)
        self._apply_vfx_height_state()
        self.thumb_label.installEventFilter(self)
        self.thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb_label.setToolTip("플레이트 MOV를 RV로 열기")
        for w in self.findChildren(QWidget):
            if w is self.thumb_label:
                continue
            if isinstance(w, (QPushButton, QTextEdit)):
                continue
            w.installEventFilter(self)

    def eventFilter(self, obj: object, event: object) -> bool:
        if obj is self.thumb_label and event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                self._open_plate_in_rv()
                return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and self._select_callback is not None
        ):
            if isinstance(obj, (QPushButton, QTextEdit)):
                return False
            if obj is self.thumb_label:
                return False
            self._select_callback(self)
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._select_callback is not None:
            self._select_callback(self)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def _add_vline(self, lay: QHBoxLayout) -> None:
        line = _vline()
        self._vlines.append(line)
        lay.addWidget(line, alignment=Qt.AlignmentFlag.AlignTop)

    def _sync_vline_heights(self) -> None:
        h = self.height()
        for line in self._vlines:
            line.setMinimumHeight(max(_THUMB_H, h - 16))

    def _toggle_vfx(self) -> None:
        self._vfx_expanded = not self._vfx_expanded
        self._apply_vfx_height_state()

    def _apply_vfx_height_state(self) -> None:
        if self._vfx_expanded:
            self.setMinimumHeight(_CARD_COLLAPSED_H)
            self.setMaximumHeight(_QWIDGETSIZE_MAX)
            self._vfx_text.setFixedHeight(_VFX_TEXT_H_EXPANDED)
            self._vfx_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._vfx_toggle_btn.setText("\u25b2")
            self._vfx_toggle_btn.setToolTip("워크오더 접기")
        else:
            self.setMinimumHeight(_CARD_COLLAPSED_H)
            self.setMaximumHeight(_CARD_COLLAPSED_H)
            self._vfx_text.setFixedHeight(_VFX_TEXT_H_COLLAPSED)
            self._vfx_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._vfx_toggle_btn.setText("\u25bc")
            self._vfx_toggle_btn.setToolTip("워크오더 펼치기")
        QTimer.singleShot(0, self._sync_vline_heights)

    def _build(self, d: Dict[str, Any]) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 8, 8)
        lay.setSpacing(0)

        # Thumbnail (fills cell; pixmap cropped in set_thumbnail)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedWidth(_THUMB_W)
        self.thumb_label.setMinimumHeight(_THUMB_H)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        self.thumb_label.setText("img")
        lay.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignTop)

        shot_code = d.get("shot_code", "")
        task_content = d.get("task_content", "")
        status = d.get("task_status", "")
        delivery = _format_task_date(d.get("delivery_date"))
        vfx_wo = (d.get("vfx_work_order") or "").strip()

        self._add_vline(lay)

        # Shot name, task, version (thumbnail right; local NK는 백그라운드에서 채움)
        info = QVBoxLayout()
        info.setSpacing(4)
        info.setContentsMargins(8, 0, 8, 0)
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel(shot_code)
        title.setStyleSheet(f"font-weight: bold; border: none; color: {theme.ACCENT};")
        shot_id_i: Optional[int] = None
        try:
            raw_sid = d.get("shot_id")
            if raw_sid is not None:
                shot_id_i = int(raw_sid)
        except (TypeError, ValueError):
            shot_id_i = None
        if shot_id_i is not None and shot_id_i <= 0:
            shot_id_i = None

        sg_open_btn = QPushButton()
        setup_shotgrid_open_shot_button(sg_open_btn, shot_id_i)
        copy_shot_btn = QPushButton()
        setup_copy_shot_name_button(copy_shot_btn, str(shot_code).strip() if shot_code else "")
        title_row.addWidget(title, alignment=Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(sg_open_btn, alignment=Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(copy_shot_btn, alignment=Qt.AlignmentFlag.AlignTop)
        title_row.addStretch()
        info.addLayout(title_row)
        task_line = QLabel(f"Task: {task_content}")
        task_line.setObjectName("page_subtitle")
        task_line.setStyleSheet(f"border: none; color: {theme.TEXT};")
        info.addWidget(task_line)
        self._version_line = QLabel("Version: —")
        self._version_line.setObjectName("page_subtitle")
        self._version_line.setStyleSheet(f"border: none; color: {theme.TEXT};")
        info.addWidget(self._version_line)
        info.addStretch()
        lay.addLayout(info, 1)

        self._add_vline(lay)

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
        lay.addWidget(status_cell, alignment=Qt.AlignmentFlag.AlignTop)

        self._add_vline(lay)

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
        lay.addWidget(date_col, alignment=Qt.AlignmentFlag.AlignTop)

        self._add_vline(lay)

        # VFX work order — 고정 높이 카드 + 펼치기; 긴 경로는 QTextEdit WrapAnywhere
        vfx_col = QWidget()
        vfx_col.setMinimumWidth(0)
        vfx_col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        vfx_lay = QVBoxLayout(vfx_col)
        vfx_lay.setContentsMargins(6, 6, 6, 6)
        vfx_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        vfx_hdr_row = QHBoxLayout()
        vfx_hdr_row.setSpacing(6)
        vfx_hdr = QLabel("VFX work order")
        vfx_hdr.setObjectName("page_subtitle")
        vfx_hdr.setStyleSheet("border: none;")
        self._vfx_toggle_btn = QPushButton("\u25bc")
        self._vfx_toggle_btn.setFixedSize(28, 22)
        self._vfx_toggle_btn.setToolTip("워크오더 펼치기")
        self._vfx_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vfx_toggle_btn.setStyleSheet(
            f"QPushButton {{ color: {theme.ACCENT}; background: transparent; border: none; "
            f"font-size: 12px; padding: 0; }}"
            f"QPushButton:hover {{ background-color: {theme.INPUT_BG}; border-radius: 4px; }}"
        )
        self._vfx_toggle_btn.clicked.connect(self._toggle_vfx)
        vfx_hdr_row.addWidget(vfx_hdr, 0, Qt.AlignmentFlag.AlignVCenter)
        vfx_hdr_row.addWidget(self._vfx_toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        vfx_hdr_row.addStretch()
        vfx_lay.addLayout(vfx_hdr_row)
        self._vfx_text = QTextEdit()
        self._vfx_text.setPlainText(vfx_wo if vfx_wo else "—")
        self._vfx_text.setReadOnly(True)
        self._vfx_text.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self._vfx_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vfx_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vfx_text.setFrameShape(QFrame.Shape.NoFrame)
        self._vfx_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._vfx_text.document().setDocumentMargin(0)
        self._vfx_text.setMinimumWidth(0)
        self._vfx_text.setStyleSheet(
            f"QTextEdit {{ background-color: transparent; color: {theme.TEXT}; "
            f"border: none; padding: 0; selection-background-color: {theme.ACCENT}; }}"
        )
        vfx_lay.addWidget(self._vfx_text)
        lay.addWidget(vfx_col, 2, Qt.AlignmentFlag.AlignTop)

        self._add_vline(lay)

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

        sb_btn = QPushButton("Shot Build")
        sb_btn.setMinimumWidth(80)
        sb_btn.setToolTip("Shot Builder — NK 생성")
        sb_btn.clicked.connect(self._on_shot_builder)
        btn_col.addWidget(sb_btn)

        btn_col.addStretch()
        lay.addLayout(btn_col)

    def _on_publish(self) -> None:
        if self._publish_callback is not None:
            self._publish_callback(self.task_data)

    def _on_shot_builder(self) -> None:
        if self._shot_builder_callback is not None:
            self._shot_builder_callback(self.task_data)

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
        QDesktopServices.openUrl(QUrl.fromLocalFile(normalize_path_str(folder)))

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

    def _open_plate_in_rv(self) -> None:
        d = self.task_data
        shot_code = d.get("shot_code", "")
        project_code = d.get("project_code") or d.get("project_folder", "")
        if not shot_code or not project_code:
            logger.warning("RV 열기: shot_code 또는 project_code 없음")
            return

        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = find_server_root_auto(project_code) or env_root
        if not server_root:
            logger.warning(
                "RV 열기: 서버 루트를 찾을 수 없음 (드라이브:\\vfx\\project_연도\\%s)",
                project_code,
            )
            return
        logger.info("RV: server_root=%s shot=%s", server_root, shot_code)
        if not open_plate_in_rv(shot_code, project_code, server_root):
            logger.warning("RV 열기 실패: MOV 없거나 rv 미설치 (%s)", shot_code)

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

    def set_comp_version_label(self, version_code: str) -> None:
        v = (version_code or "").strip()
        self._version_line.setText(f"Version: {v}" if v else "Version: —")


class MyTasksTab(QWidget):
    """My Tasks tab: project/user filter → shot card list + notes."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._projects: List[Dict[str, Any]] = []
        self._user_id: Optional[int] = None
        # 선택 확정 후 입력란 전체 문자열. 동일하면 자동완성 팝업 생략(깜빡임 방지).
        self._assignee_resolved_display: Optional[str] = None
        # PC에서 추정한 ShotGrid HumanUser (My Tasks 자동 인식 성공 시만). 담당자 필터와 별개.
        self._me_sg_user: Optional[Dict[str, Any]] = None
        self._timelog_resolve_busy: bool = False
        self._user_search_seq: int = 0
        self._cards: List[_ShotCard] = []
        self._workers: List[ShotGridWorker] = []
        self._note_widgets: List[QFrame] = []
        self._last_shot_ids: List[int] = []
        self._notes_req_seq: int = 0
        self._version_req_seq: int = 0
        self._splitter_initial_ratio_done: bool = False
        self._splitter_ratio_attempts: int = 0
        self._selected_shot_card: Optional[_ShotCard] = None
        self._current_project_code: Optional[str] = None
        self._all_tasks: List[Dict[str, Any]] = []
        self._active_status: str = "all"
        self._status_btn_map: Dict[str, QPushButton] = {}
        self._sort_ascending: bool = True
        self._version_cache: Dict[str, Optional[str]] = {}
        self._project_users: List[Dict[str, Any]] = []
        self._version_widgets: List[QWidget] = []
        self._versions_req_seq: int = 0
        self._user_assignee_popup: Optional[QFrame] = None
        self._assignee_all_mode: bool = False
        self._skip_project_notes_on_next_tasks_load: bool = False
        self._roster_page: int = 1
        self._roster_page_size: int = 100
        self._roster_total: int = 0
        self._roster_total_all: int = 0
        self._status_counts_sg: Dict[str, int] = {}
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._on_spinner_tick)
        self._spinner_labels: Set[QLabel] = set()
        self._spinner_frame_idx: int = 0

        self._user_timer = QTimer(self)
        self._user_timer.setSingleShot(True)
        self._user_timer.timeout.connect(self._do_user_search)

        self._shot_search_timer = QTimer(self)
        self._shot_search_timer.setSingleShot(True)
        self._shot_search_timer.timeout.connect(self._do_shot_autocomplete)
        self._shot_ac_seq = 0
        self._shot_focus_shot_id: Optional[int] = None
        self._shot_extra_task: Optional[Dict[str, Any]] = None
        self._shot_inject_seq = 0
        self._tag_filter_value: Optional[str] = None
        self._tag_filter_popup: Optional[QFrame] = None

        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)
        QTimer.singleShot(200, self._load_projects)
        QTimer.singleShot(400, self._guess_me)
        self._update_timelog_button_state()

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

        # ── Filter bar ────────────────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)
        filter_bar.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        # 우측 노트 패널 right_lay(8px)과 맞춰 TimeLog·Shotgrid 오른쪽 끝을 노트 새로고침과 정렬
        filter_bar.setContentsMargins(0, 0, 8, 0)

        _lbl_style = (
            f"color: {theme.TEXT_LABEL}; font-size: {theme.FONT_SIZE}px; "
            f"background: transparent; border: none;"
        )
        proj_label = QLabel("프로젝트")
        proj_label.setStyleSheet(_lbl_style)
        filter_bar.addWidget(proj_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._project_combo = QComboBox()
        self._project_combo.setFixedWidth(130)
        self._project_combo.addItem("-- 로딩 중 --")
        self._project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        filter_bar.addWidget(self._project_combo, 0, Qt.AlignmentFlag.AlignVCenter)

        filter_bar.addSpacing(14)

        user_label = QLabel("담당자")
        user_label.setStyleSheet(_lbl_style)
        filter_bar.addWidget(user_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("이름 입력 후 Enter 또는 목록 선택")
        self._user_edit.setFixedWidth(_ASSIGNEE_EDIT_WIDTH)
        self._user_edit.textChanged.connect(lambda: self._user_timer.start(_AUTOCOMPLETE_DELAY))
        self._user_edit.returnPressed.connect(self._on_user_search_immediate)
        filter_bar.addWidget(self._user_edit, 0, Qt.AlignmentFlag.AlignVCenter)

        # user_info: 담당자 입력 아래에 뜨는 플로팅 레이블 (레이아웃 높이 영향 없음)
        self._user_info = QLabel("", self)
        self._user_info.setObjectName("user_id_badge")
        self._user_info.setVisible(False)
        self._user_info.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: 11px; "
            f"padding: 0; margin: 0; background: transparent;"
        )
        self._user_info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 검색 결과: 팝업 목록만 보이게 함(닫힌 콤보 한 줄이 잠깐 보이지 않도록 본체 높이 0·투명)
        self._user_combo = QComboBox(self)
        self._user_combo.setObjectName("user_autocomplete_combo")
        self._user_combo.setVisible(False)
        self._user_combo.setEditable(False)
        self._user_combo.setMaxVisibleItems(12)
        self._user_combo.setFixedHeight(0)
        self._user_combo.currentIndexChanged.connect(self._on_user_selected)

        filter_bar.addSpacing(14)

        self._user_list_btn = QPushButton(f"Assigned To  {chr(0x25BE)}")
        self._user_list_btn.setObjectName("filter_combo_like_btn")
        self._user_list_btn.setMinimumWidth(130)
        self._user_list_btn.setToolTip("프로젝트에 배정된 담당자 목록")
        self._user_list_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_list_btn.clicked.connect(self._toggle_user_assignee_popup)
        filter_bar.addWidget(self._user_list_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._me_btn = QPushButton("My Tasks")
        self._me_btn.setFixedWidth(80)
        self._me_btn.clicked.connect(self._guess_me)
        filter_bar.addWidget(self._me_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh_btn = QPushButton("  조회  ")
        refresh_btn.setProperty("primary", True)
        refresh_btn.clicked.connect(self._refresh)
        filter_bar.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        filter_bar.addStretch()

        self._project_shotgrid_btn = QPushButton("Shotgrid")
        self._project_shotgrid_btn.setObjectName("my_tasks_project_shotgrid_btn")
        self._project_shotgrid_btn.setFixedWidth(88)
        self._project_shotgrid_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._project_shotgrid_btn.clicked.connect(self._open_project_overview_in_browser)
        filter_bar.addWidget(self._project_shotgrid_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._timelog_btn = QPushButton("TimeLog")
        self._timelog_btn.setFixedWidth(88)
        self._timelog_btn.setToolTip("")
        self._timelog_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timelog_btn.clicked.connect(self._open_time_log_dialog)
        filter_bar.addWidget(self._timelog_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addLayout(filter_bar)
        self._update_project_shotgrid_btn_state()

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
        shot_hdr.setSpacing(8)
        shot_title = QLabel("샷 목록")
        shot_title.setObjectName("log_title")
        shot_hdr.addWidget(shot_title)
        shot_sub = QLabel("배정 태스크")
        shot_sub.setObjectName("page_subtitle")
        shot_hdr.addWidget(shot_sub)
        self._shot_spinner_lbl = QLabel("")
        self._shot_spinner_lbl.setFixedWidth(18)
        self._shot_spinner_lbl.setObjectName("page_subtitle")
        self._shot_spinner_lbl.setVisible(False)
        shot_hdr.addWidget(self._shot_spinner_lbl)
        shot_hdr.addStretch()

        self._shot_search_edit = QLineEdit()
        self._shot_search_edit.setPlaceholderText("샷 코드 (2자 이상 자동완성, Enter 확정)")
        self._shot_search_edit.setFixedWidth(_ASSIGNEE_EDIT_WIDTH)
        self._shot_search_edit.setFixedHeight(34)
        self._shot_search_edit.textChanged.connect(
            lambda: self._shot_search_timer.start(_AUTOCOMPLETE_DELAY)
        )
        self._shot_search_edit.returnPressed.connect(self._on_shot_search_immediate)
        shot_hdr.addWidget(self._shot_search_edit, 0, Qt.AlignmentFlag.AlignVCenter)

        self._shot_combo = QComboBox(self)
        self._shot_combo.setObjectName("shot_autocomplete_combo")
        self._shot_combo.setVisible(False)
        self._shot_combo.setEditable(False)
        self._shot_combo.setMaxVisibleItems(12)
        self._shot_combo.setFixedHeight(0)
        self._shot_combo.currentIndexChanged.connect(self._on_shot_suggest_selected)

        self._tag_filter_btn = QPushButton(f"태그  {chr(0x25BE)}")
        self._tag_filter_btn.setObjectName("filter_combo_like_btn")
        self._tag_filter_btn.setMinimumWidth(130)
        self._tag_filter_btn.setFixedHeight(34)
        self._tag_filter_btn.setToolTip("샷 태그로 목록 좁히기")
        self._tag_filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tag_filter_btn.clicked.connect(self._toggle_tag_filter_popup)
        shot_hdr.addWidget(self._tag_filter_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        _sort_lbl = QLabel("샷 정렬")
        _sort_lbl.setObjectName("page_subtitle")
        shot_hdr.addWidget(_sort_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Shot Name", _SORT_MODE_SHOT)
        self._sort_combo.addItem("Delivery Date", _SORT_MODE_DELIVERY)
        self._sort_combo.setMinimumWidth(100)
        self._sort_combo.setMaximumWidth(140)
        self._sort_combo.setFixedHeight(34)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_combo_changed)
        shot_hdr.addWidget(self._sort_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        self._sort_dir_btn = QPushButton("\u25b2")
        self._sort_dir_btn.setFixedSize(34, 34)
        self._sort_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_dir_btn.clicked.connect(self._toggle_sort_direction)
        self._sort_dir_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
            f"font-size: 14px; padding: 0px; min-width: 0; min-height: 0; }}"
            f"QPushButton:hover {{ background-color: {theme.PANEL_BG}; "
            f"border-color: {theme.ACCENT}; color: {theme.ACCENT}; }}"
            f"QPushButton:pressed {{ background-color: {theme.BORDER}; }}"
        )
        shot_hdr.addWidget(self._sort_dir_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._update_sort_dir_button()
        shot_lay.addLayout(shot_hdr)

        self._status_scroll = QScrollArea()
        self._status_scroll.setWidgetResizable(True)
        self._status_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._status_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._status_scroll.setFixedHeight(56)
        self._status_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._status_host = QWidget()
        self._status_layout = QHBoxLayout(self._status_host)
        self._status_layout.setContentsMargins(0, 0, 0, 0)
        self._status_layout.setSpacing(6)
        self._status_scroll.setWidget(self._status_host)
        shot_lay.addWidget(self._status_scroll)

        self._pager_host = QWidget()
        self._pager_host.setVisible(False)
        pager_lay = QHBoxLayout(self._pager_host)
        pager_lay.setContentsMargins(0, 4, 0, 0)
        pager_lay.setSpacing(8)
        self._pager_prev = QPushButton("« 이전")
        self._pager_prev.setFixedWidth(72)
        self._pager_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pager_prev.clicked.connect(self._roster_prev_page)
        pager_lay.addWidget(self._pager_prev)
        self._pager_next = QPushButton("다음 »")
        self._pager_next.setFixedWidth(72)
        self._pager_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pager_next.clicked.connect(self._roster_next_page)
        pager_lay.addWidget(self._pager_next)
        self._pager_info = QLabel("")
        self._pager_info.setObjectName("page_subtitle")
        pager_lay.addWidget(self._pager_info, 1)
        sz_lbl = QLabel("페이지 크기")
        sz_lbl.setObjectName("page_subtitle")
        pager_lay.addWidget(sz_lbl)
        self._pager_size_edit = QLineEdit()
        self._pager_size_edit.setFixedWidth(52)
        self._pager_size_edit.setValidator(QIntValidator(10, 500, self))
        self._pager_size_edit.setText("100")
        self._pager_size_edit.editingFinished.connect(self._roster_page_size_committed)
        pager_lay.addWidget(self._pager_size_edit)

        self._card_area = QScrollArea()
        self._card_area.setObjectName("shot_list_scroll")
        self._card_area.setWidgetResizable(True)
        self._card_area.setFrameShape(QFrame.Shape.NoFrame)
        self._card_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        self._card_area.setWidget(self._card_host)
        shot_lay.addWidget(self._card_area, 1)
        shot_lay.addWidget(self._pager_host)

        self._splitter.addWidget(shot_panel)

        # Right panel — panel selector + stacked (Notes | Versions)
        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.setSpacing(6)

        # Panel toggle row
        sel_row = QHBoxLayout()
        sel_row.setSpacing(4)
        self._notes_panel_btn = QPushButton("Notes")
        self._notes_panel_btn.setObjectName("panel_tab_btn")
        self._notes_panel_btn.setProperty("selected", True)
        self._notes_panel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notes_panel_btn.clicked.connect(lambda: self._switch_right_panel(0))
        sel_row.addWidget(self._notes_panel_btn)
        self._versions_panel_btn = QPushButton("Versions")
        self._versions_panel_btn.setObjectName("panel_tab_btn")
        self._versions_panel_btn.setProperty("selected", False)
        self._versions_panel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._versions_panel_btn.clicked.connect(lambda: self._switch_right_panel(1))
        sel_row.addWidget(self._versions_panel_btn)
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
        self._note_title_lbl = QLabel("Notes")
        self._note_title_lbl.setObjectName("log_title")
        note_hdr.addWidget(self._note_title_lbl)
        self._note_sub_lbl = QLabel("최근 2주 코멘트")
        self._note_sub_lbl.setObjectName("page_subtitle")
        note_hdr.addWidget(self._note_sub_lbl)
        self._note_spinner_lbl = QLabel("")
        self._note_spinner_lbl.setFixedWidth(18)
        self._note_spinner_lbl.setObjectName("page_subtitle")
        self._note_spinner_lbl.setVisible(False)
        note_hdr.addWidget(self._note_spinner_lbl)
        note_hdr.addStretch()
        self._note_refresh_btn = QPushButton("노트 새로고침")
        self._note_refresh_btn.setMinimumWidth(120)
        self._note_refresh_btn.clicked.connect(self._refresh_notes_clicked)
        note_hdr.addWidget(self._note_refresh_btn)
        notes_page_lay.addLayout(note_hdr)

        note_scroll = QScrollArea()
        note_scroll.setObjectName("note_list_scroll")
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

        # ── Page 1: Versions (ShotGrid) ───────────────────────────────
        versions_page = QWidget()
        versions_page_lay = QVBoxLayout(versions_page)
        versions_page_lay.setContentsMargins(0, 0, 0, 0)
        versions_page_lay.setSpacing(4)
        ver_hdr = QHBoxLayout()
        ver_title = QLabel("Versions")
        ver_title.setObjectName("log_title")
        ver_hdr.addWidget(ver_title)
        self._versions_shot_lbl = QLabel("")
        self._versions_shot_lbl.setObjectName("page_subtitle")
        ver_hdr.addWidget(self._versions_shot_lbl)
        self._ver_spinner_lbl = QLabel("")
        self._ver_spinner_lbl.setFixedWidth(18)
        self._ver_spinner_lbl.setObjectName("page_subtitle")
        self._ver_spinner_lbl.setVisible(False)
        ver_hdr.addWidget(self._ver_spinner_lbl)
        ver_hdr.addStretch()
        ver_refresh_btn = QPushButton("새로고침")
        ver_refresh_btn.setFixedWidth(88)
        ver_refresh_btn.clicked.connect(self._refresh_versions_clicked)
        ver_hdr.addWidget(ver_refresh_btn)
        versions_page_lay.addLayout(ver_hdr)
        ver_scroll = QScrollArea()
        ver_scroll.setObjectName("note_list_scroll")
        ver_scroll.setWidgetResizable(True)
        ver_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._versions_host = QWidget()
        self._versions_layout = QVBoxLayout(self._versions_host)
        self._versions_layout.setContentsMargins(0, 0, 0, 0)
        self._versions_layout.setSpacing(6)
        self._versions_layout.addStretch()
        ver_scroll.setWidget(self._versions_host)
        versions_page_lay.addWidget(ver_scroll, 1)
        self._right_stack.addWidget(versions_page)

        right_lay.addWidget(self._right_stack, 1)
        self._splitter.addWidget(right_panel)

        self._splitter.setStretchFactor(0, 6)
        self._splitter.setStretchFactor(1, 4)
        root.addWidget(self._splitter, 1)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._splitter_initial_ratio_done:
            QTimer.singleShot(0, self._apply_splitter_initial_ratio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._user_combo.isVisible():
            self._position_user_results_combo()
        if getattr(self, "_shot_combo", None) is not None and self._shot_combo.isVisible():
            self._position_shot_results_combo()
        if self._user_info.isVisible():
            self._position_user_info()

    def _on_spinner_tick(self) -> None:
        if not self._spinner_labels:
            return
        self._spinner_frame_idx = (self._spinner_frame_idx + 1) % len(_SPINNER_FRAMES)
        ch = _SPINNER_FRAMES[self._spinner_frame_idx]
        for lbl in self._spinner_labels:
            lbl.setText(ch)

    def _start_spinner(self, lbl: QLabel) -> None:
        self._spinner_labels.add(lbl)
        lbl.setVisible(True)
        lbl.setText(_SPINNER_FRAMES[0])
        if not self._spinner_timer.isActive():
            self._spinner_timer.start()

    def _stop_spinner(self, lbl: QLabel) -> None:
        self._spinner_labels.discard(lbl)
        lbl.setVisible(False)
        lbl.setText("")
        if not self._spinner_labels:
            self._spinner_timer.stop()

    def _on_app_focus_changed(self, _old: Optional[QWidget], new: Optional[QWidget]) -> None:
        def _maybe_hide(pop: Optional[QFrame]) -> None:
            if pop is None or not pop.isVisible():
                return
            if new is None:
                return
            w: Optional[QWidget] = new
            while w is not None:
                if w is pop:
                    return
                w = w.parentWidget()
            pop.hide()

        _maybe_hide(self._user_assignee_popup)
        _maybe_hide(getattr(self, "_tag_filter_popup", None))

    def _position_shot_results_combo(self) -> None:
        w = max(220, self._shot_search_edit.width())
        self._shot_combo.setFixedWidth(w)
        top_left = self._shot_search_edit.mapTo(self, QPoint(0, self._shot_search_edit.height()))
        self._shot_combo.move(top_left.x(), top_left.y())
        self._shot_combo.raise_()

    def _clear_shot_focus_only(self) -> None:
        self._shot_focus_shot_id = None
        self._shot_extra_task = None
        if getattr(self, "_shot_search_edit", None) is not None:
            self._shot_search_edit.clear()
        if getattr(self, "_shot_combo", None) is not None:
            self._shot_combo.blockSignals(True)
            self._shot_combo.hide()
            self._shot_combo.clear()
            self._shot_combo.blockSignals(False)

    def _clear_shot_and_tag_filters(self) -> None:
        self._clear_shot_focus_only()
        self._tag_filter_value = None
        self._update_tag_filter_button_label()
        p = getattr(self, "_tag_filter_popup", None)
        if p is not None and p.isVisible():
            p.hide()

    def _merged_tasks_for_display(self) -> List[Dict[str, Any]]:
        rows = list(self._all_tasks)
        if self._shot_extra_task is not None:
            sid = self._shot_extra_task.get("shot_id")
            if sid is not None:
                try:
                    sid_i = int(sid)
                except (TypeError, ValueError):
                    sid_i = None
                if sid_i is not None:
                    have = False
                    for t in rows:
                        ts = t.get("shot_id")
                        if ts is None:
                            continue
                        try:
                            if int(ts) == sid_i:
                                have = True
                                break
                        except (TypeError, ValueError):
                            continue
                    if not have:
                        rows.append(dict(self._shot_extra_task))
        return rows

    def _update_tag_filter_button_label(self) -> None:
        btn = getattr(self, "_tag_filter_btn", None)
        if btn is None:
            return
        tv = (self._tag_filter_value or "").strip()
        if tv:
            disp = tv if len(tv) <= 14 else tv[:13] + "…"
            btn.setText(f"태그: {disp}  {chr(0x25BE)}")
        else:
            btn.setText(f"태그  {chr(0x25BE)}")

    def _collect_union_shot_tags(self) -> List[str]:
        seen: Set[str] = set()
        out: List[str] = []
        for t in self._all_tasks:
            raw = t.get("shot_tags")
            if not isinstance(raw, list):
                continue
            for x in raw:
                s = str(x).strip()
                if not s:
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
        out.sort(key=lambda s: s.lower())
        return out

    def _toggle_tag_filter_popup(self) -> None:
        if not self._all_tasks:
            QMessageBox.information(self, "태그", "먼저 조회를 실행하세요.")
            return
        p = self._tag_filter_popup
        if p is not None and p.isVisible():
            p.hide()
            return
        if p is not None:
            p.deleteLater()
        tags = self._collect_union_shot_tags()
        popup = QFrame(self)
        popup.setObjectName("user_assignee_popup")
        popup.setStyleSheet(
            f"QFrame#user_assignee_popup {{ background-color: {theme.PANEL_BG}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        popup.setWindowFlags(Qt.WindowType.Popup)
        lay = QVBoxLayout(popup)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        def _pick(tag: Optional[str]) -> None:
            self._tag_filter_value = tag
            self._update_tag_filter_button_label()
            popup.hide()
            self._apply_filter_and_sort()

        all_btn = QPushButton("(전체)")
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.clicked.connect(lambda: _pick(None))
        lay.addWidget(all_btn)
        if not tags:
            hint = QLabel("이 조회 결과에 샷 태그가 없습니다.")
            hint.setObjectName("page_subtitle")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        else:
            for tg in tags:
                b = QPushButton(tg)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _c=False, val=tg: _pick(val))
                lay.addWidget(b)

        popup.adjustSize()
        gp = self._tag_filter_btn.mapToGlobal(QPoint(0, self._tag_filter_btn.height()))
        popup.move(gp)
        popup.show()
        self._tag_filter_popup = popup

    def _do_shot_autocomplete(self) -> None:
        self._shot_ac_seq += 1
        seq = self._shot_ac_seq
        q = self._shot_search_edit.text().strip()
        pid = self._project_combo.currentData()
        if pid is None or len(q) < 2:
            self._shot_combo.hide()
            return

        def _search() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return search_shots_by_code_prefix(sg, int(pid), q, limit=20)

        w = ShotGridWorker(_search)
        w.finished.connect(lambda r: self._on_shot_autocomplete_results(r, seq))
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _on_shot_autocomplete_results(self, result: object, seq: int) -> None:
        if seq != self._shot_ac_seq:
            return
        rows = result if isinstance(result, list) else []
        self._shot_combo.blockSignals(True)
        self._shot_combo.clear()
        for s in rows:
            code = (s.get("code") or "").strip()
            sid = s.get("id")
            if not code or sid is None:
                continue
            self._shot_combo.addItem(code, int(sid))
        self._shot_combo.blockSignals(False)
        if rows:
            self._shot_combo.setVisible(True)
            self._position_shot_results_combo()
            QTimer.singleShot(0, self._position_shot_results_combo)
            self._shot_combo.showPopup()
        else:
            self._shot_combo.setVisible(False)

    def _on_shot_suggest_selected(self, idx: int) -> None:
        if idx < 0:
            return
        sid = self._shot_combo.itemData(idx)
        code = self._shot_combo.itemText(idx)
        if sid is None:
            return
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            return
        self._shot_combo.blockSignals(True)
        self._shot_combo.hide()
        self._shot_combo.clear()
        self._shot_combo.blockSignals(False)
        self._shot_search_edit.setText(code)
        self._commit_shot_focus(sid_i, code)

    def _on_shot_search_immediate(self) -> None:
        self._shot_search_timer.stop()
        self._shot_ac_seq += 1
        pid = self._project_combo.currentData()
        if pid is None:
            QMessageBox.information(self, "샷 검색", "프로젝트를 먼저 선택하세요.")
            return
        raw = self._shot_search_edit.text().strip()
        if not raw:
            self._clear_shot_and_tag_filters()
            self._apply_filter_and_sort()
            return

        def _fetch() -> Optional[Dict[str, Any]]:
            sg = get_default_sg()
            return find_shot(sg, int(pid), raw)

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r: self._on_shot_find_for_enter(r, raw))
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _on_shot_find_for_enter(self, shot: object, typed: str) -> None:
        s = shot if isinstance(shot, dict) else None
        if s is None or s.get("id") is None:
            QMessageBox.information(
                self,
                "샷 검색",
                f"프로젝트에서 '{typed}' 샷을 찾지 못했습니다.",
            )
            return
        try:
            sid_i = int(s.get("id"))
        except (TypeError, ValueError):
            return
        code = (s.get("code") or typed).strip()
        self._shot_search_edit.setText(code)
        self._commit_shot_focus(sid_i, code)

    def _commit_shot_focus(self, shot_id: int, shot_code: str) -> None:
        self._shot_focus_shot_id = int(shot_id)
        self._shot_extra_task = None
        have = False
        for t in self._all_tasks:
            ts = t.get("shot_id")
            if ts is None:
                continue
            try:
                if int(ts) == int(shot_id):
                    have = True
                    break
            except (TypeError, ValueError):
                continue
        if have:
            self._apply_filter_and_sort()
            return
        self._shot_inject_seq += 1
        seq = self._shot_inject_seq
        pid = self._project_combo.currentData()
        if pid is None:
            return

        def _fetch() -> Optional[Dict[str, Any]]:
            sg = get_default_sg()
            return fetch_representative_my_tasks_row_for_project_shot(sg, int(pid), int(shot_id))

        w = ShotGridWorker(_fetch)
        w.finished.connect(lambda r: self._on_injected_shot_row(r, seq, int(shot_id), shot_code))
        w.error.connect(lambda m: QMessageBox.warning(self, "샷 검색", f"태스크 로드 실패: {m}"))
        w.start()
        self._workers.append(w)

    def _on_injected_shot_row(
        self,
        row: object,
        seq: int,
        wanted_id: int,
        shot_code: str,
    ) -> None:
        if seq != self._shot_inject_seq:
            return
        if not isinstance(row, dict):
            QMessageBox.information(
                self,
                "샷 검색",
                f"'{shot_code}' 샷에 표시할 comp 태스크를 찾지 못했습니다.",
            )
            self._shot_focus_shot_id = None
            return
        try:
            rid = int(row.get("shot_id") or 0)
        except (TypeError, ValueError):
            rid = 0
        if rid != int(wanted_id):
            self._shot_focus_shot_id = None
            return
        self._shot_extra_task = row
        self._apply_filter_and_sort()

    def _apply_splitter_initial_ratio(self) -> None:
        """첫 표시 시 샷 목록 ~72% / 우측 패널 ~28% (Notes·Shot Builder)."""
        if self._splitter_initial_ratio_done:
            return
        w = self._splitter.width()
        if w <= 0:
            self._splitter_ratio_attempts += 1
            if self._splitter_ratio_attempts < 20:
                QTimer.singleShot(50, self._apply_splitter_initial_ratio)
            else:
                self._splitter_initial_ratio_done = True
            return
        self._splitter_initial_ratio_done = True
        left = int(w * 0.60)
        self._splitter.setSizes([left, w - left])

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
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        self._project_combo.addItem("(전체)", None)
        for p in projects:
            name = p.get("name") or p.get("code") or ""
            self._project_combo.addItem(name, p.get("id"))
        self._project_combo.blockSignals(False)
        self._on_project_combo_changed()

    # ── Project assignees / user picker / guess ─────────────────────

    def _on_project_combo_changed(self, _idx: int = 0) -> None:
        self._clear_shot_and_tag_filters()
        self._project_users.clear()
        assignee_text = (self._user_edit.text() or "").strip()
        if assignee_text == "All Tasks":
            self._assignee_all_mode = True
            if getattr(self, "_pager_host", None) is not None:
                self._pager_host.setVisible(True)
            self._update_roster_pager_ui()
        else:
            self._assignee_all_mode = False
            if getattr(self, "_pager_host", None) is not None:
                self._pager_host.setVisible(False)
        pid = self._project_combo.currentData()
        self._update_project_shotgrid_btn_state()
        if pid is None:
            return

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_project_assignees(sg, int(pid))

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_project_users_loaded)
        w.error.connect(lambda e: logger.warning("프로젝트 담당자 목록 실패: %s", e))
        w.start()
        self._workers.append(w)

    def _on_project_users_loaded(self, result: object) -> None:
        users = result if isinstance(result, list) else []
        self._project_users = [u for u in users if isinstance(u, dict)]

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
            self._show_user_id_badge("자동 감지 실패", success=False)
            return
        self._me_sg_user = dict(user)
        self._apply_user_from_dict(user)

    def _hide_user_autocomplete_combo(self) -> None:
        """조회 시작 등 — 비동기 검색 결과로 목록이 잠깐 뜨는 현상 방지."""
        self._user_search_seq += 1
        self._user_combo.blockSignals(True)
        self._user_combo.hide()
        self._user_combo.clear()
        self._user_combo.blockSignals(False)

    def _position_user_results_combo(self) -> None:
        """담당자 자동완성 콤보를 입력란 바로 아래에만 표시 (필터 줄 중복 위젯 없음)."""
        w = max(220, self._user_edit.width())
        self._user_combo.setFixedWidth(w)
        top_left = self._user_edit.mapTo(self, QPoint(0, self._user_edit.height()))
        self._user_combo.move(top_left.x(), top_left.y())
        self._user_combo.raise_()

    def _position_user_info(self) -> None:
        """user_info 플로팅 레이블을 담당자 입력란 바로 아래에 위치시킨다."""
        if not self._user_info.isVisible():
            return
        self._user_info.adjustSize()
        p = self._user_edit.mapTo(self, QPoint(0, self._user_edit.height() + 2))
        self._user_info.move(p.x(), p.y())
        self._user_info.raise_()

    def _show_user_id_badge(self, text: str, *, success: bool = True) -> None:
        """user_info 레이블 텍스트를 설정하고 담당자 입력란 아래에 표시한다."""
        self._user_info.setText(text)
        self._user_info.setVisible(bool(text))
        color = theme.SUCCESS if success else theme.ERROR
        self._user_info.setStyleSheet(
            f"color: {color}; font-size: 11px; padding: 0; margin: 0; background: transparent;"
        )
        QTimer.singleShot(0, self._position_user_info)

    def _apply_user_from_dict(self, u: Dict[str, Any]) -> None:
        uid = u.get("id")
        if uid is None:
            return
        self._assignee_all_mode = False
        if getattr(self, "_pager_host", None) is not None:
            self._pager_host.setVisible(False)
        self._user_id = int(uid)
        self._user_edit.setText(_format_human_user_display(u))
        self._assignee_resolved_display = (self._user_edit.text() or "").strip()
        self._user_edit.setCursorPosition(0)
        self._show_user_id_badge(f"✓ #{self._user_id}")
        self._clear_shot_and_tag_filters()
        self._update_timelog_button_state()

    def _update_timelog_button_state(self) -> None:
        if getattr(self, "_timelog_btn", None) is None:
            return
        busy = getattr(self, "_timelog_resolve_busy", False)
        self._timelog_btn.setEnabled(not busy)
        self._timelog_btn.setToolTip(
            "PC ShotGrid 사용자(My Tasks 자동 인식)로 TimeLog를 씁니다."
            if not busy
            else "PC 사용자 확인 중…"
        )

    def _update_project_shotgrid_btn_state(self) -> None:
        btn = getattr(self, "_project_shotgrid_btn", None)
        if btn is None:
            return
        pid = self._project_combo.currentData()
        if pid is None:
            btn.setEnabled(False)
            btn.setToolTip("프로젝트를 선택한 뒤 ShotGrid 프로젝트 오버뷰를 엽니다.")
            return
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            btn.setEnabled(False)
            btn.setToolTip("유효한 프로젝트 ID가 없습니다.")
            return
        if pid_i <= 0:
            btn.setEnabled(False)
            btn.setToolTip("유효한 프로젝트 ID가 없습니다.")
            return
        btn.setEnabled(True)
        btn.setToolTip("ShotGrid에서 현재 프로젝트 오버뷰 열기")

    def _open_project_overview_in_browser(self) -> None:
        pid = self._project_combo.currentData()
        if pid is None:
            return
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return
        if pid_i <= 0:
            return
        sgset = get_shotgrid_settings()
        base_u = (sgset.get("base_url") or "").strip()
        chrome_ex = ""
        cx = sgset.get("chrome_executable")
        if isinstance(cx, str):
            chrome_ex = cx.strip()
        try:
            url = build_project_overview_url(base_u, pid_i)
        except ValueError as e:
            logger.warning("ShotGrid 프로젝트 오버뷰 URL 실패: %s", e)
            return
        if not try_launch_chrome_app_url(url, chrome_executable=chrome_ex):
            QDesktopServices.openUrl(QUrl(url))

    def _open_time_log_dialog(self) -> None:
        if getattr(self, "_timelog_resolve_busy", False):
            return
        from bpe.gui.widgets.time_log_dialog import TimeLogDialog

        if self._me_sg_user and self._me_sg_user.get("id") is not None:
            uid = int(self._me_sg_user["id"])
            name = _format_human_user_display(self._me_sg_user)
            dlg = TimeLogDialog(self, uid, self._workers.append, user_name=name)
            dlg.exec()
            return

        def _fetch() -> Optional[Dict[str, Any]]:
            sg = get_default_sg()
            return guess_human_user_for_me(sg)

        self._timelog_resolve_busy = True
        self._update_timelog_button_state()

        w = ShotGridWorker(_fetch)

        def _done(result: object) -> None:
            self._timelog_resolve_busy = False
            self._update_timelog_button_state()
            u = result if isinstance(result, dict) else None
            if not u or u.get("id") is None:
                QMessageBox.warning(
                    self,
                    "사용자 확인 실패",
                    "이 PC의 ShotGrid 사용자를 찾지 못했습니다.\n"
                    "상단의 My Tasks 버튼으로 자동 인식을 먼저 시도해 보세요.",
                )
                return
            self._me_sg_user = dict(u)
            uid = int(u["id"])
            name = _format_human_user_display(u)
            dlg = TimeLogDialog(self, uid, self._workers.append, user_name=name)
            dlg.exec()

        def _err(msg: str) -> None:
            self._timelog_resolve_busy = False
            self._update_timelog_button_state()
            QMessageBox.warning(self, "ShotGrid 오류", msg)

        w.finished.connect(_done)
        w.error.connect(_err)
        self._workers.append(w)
        w.start()

    def _on_user_search_immediate(self) -> None:
        """엔터 시 디바운스 없이 즉시 검색(아래 빈 콤보 줄 깜빡임 완화에도 도움)."""
        self._user_timer.stop()
        self._do_user_search(resolve_on_enter=True)

    def _do_user_search(self, resolve_on_enter: bool = False) -> None:
        self._user_search_seq += 1
        seq = self._user_search_seq
        query = self._user_edit.text().strip()
        if len(query) < 2:
            self._user_combo.setVisible(False)
            return
        if (
            self._user_id is not None
            and self._assignee_resolved_display
            and query == self._assignee_resolved_display
        ):
            self._user_combo.setVisible(False)
            return

        def _search() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return search_human_users(sg, query)

        w = ShotGridWorker(_search)
        w.finished.connect(lambda r: self._on_user_results(r, seq, resolve_on_enter, query))
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _on_user_results(
        self,
        result: object,
        seq: int,
        resolve_on_enter: bool,
        frozen_query: str,
    ) -> None:
        if seq != self._user_search_seq:
            return
        users: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._user_combo.blockSignals(True)
        self._user_combo.clear()
        for u in users:
            label = _format_human_user_display(u)
            self._user_combo.addItem(label, u)
        self._user_combo.blockSignals(False)

        if resolve_on_enter:
            if not users:
                self._user_combo.setVisible(False)
                self._show_user_id_badge("검색 결과 없음", success=False)
                return
            chosen = _pick_user_for_enter_resolve(users, frozen_query)
            if chosen is not None:
                self._apply_user_from_dict(chosen)
                self._user_combo.setVisible(False)
                self._user_combo.blockSignals(True)
                self._user_combo.clear()
                self._user_combo.blockSignals(False)
                return
            # 후보가 여러 명이면 목록만 펼침(클릭으로 선택)

        if users:
            self._user_combo.setVisible(True)
            self._position_user_results_combo()
            QTimer.singleShot(0, self._position_user_results_combo)
            self._user_combo.showPopup()
        else:
            self._user_combo.setVisible(False)

    def _on_user_selected(self, idx: int) -> None:
        if idx < 0:
            return
        u = self._user_combo.itemData(idx)
        if not isinstance(u, dict):
            return
        self._apply_user_from_dict(u)
        self._user_combo.blockSignals(True)
        self._user_combo.hide()
        self._user_combo.clear()
        self._user_combo.blockSignals(False)

    def _toggle_user_assignee_popup(self) -> None:
        pid = self._project_combo.currentData()
        if pid is None:
            QMessageBox.information(
                self,
                "담당자",
                "담당자 목록을 보려면 프로젝트를 하나 선택하세요.\n"
                "(전체 프로젝트 모드에서는 목록을 불러올 수 없습니다.)",
            )
            return
        if not self._project_users:
            QMessageBox.information(
                self,
                "담당자",
                "담당자 목록을 불러오는 중이거나 비어 있습니다.\n"
                "잠시 후 다시 시도하거나 조회를 실행하세요.",
            )
            return

        if self._user_assignee_popup is not None and self._user_assignee_popup.isVisible():
            self._user_assignee_popup.hide()
            return

        if self._user_assignee_popup is not None:
            self._user_assignee_popup.deleteLater()
            self._user_assignee_popup = None

        popup = QFrame(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("user_assignee_popup")
        popup.setStyleSheet(
            f"QFrame#user_assignee_popup {{ background-color: {theme.PANEL_BG}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; }}"
            f"QListWidget {{ background-color: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; outline: none; }}"
            f"QListWidget::item {{ padding: 6px 8px; min-height: 22px; }}"
            f"QListWidget::item:selected {{ background-color: {theme.ACCENT}; color: #ffffff; }}"
            f"QLineEdit {{ background-color: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 6px; }}"
        )
        lay = QVBoxLayout(popup)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        search = QLineEdit()
        search.setPlaceholderText("이름 또는 로그인 검색…")
        lay.addWidget(search)
        lst = QListWidget()
        lst.setAlternatingRowColors(False)
        lay.addWidget(lst, 1)

        def _fill(filter_q: str) -> None:
            lst.clear()
            q = (filter_q or "").strip().lower()
            if not q:
                it0 = QListWidgetItem("All Tasks")
                it0.setData(Qt.ItemDataRole.UserRole, {"_bpe_roster_all": True})
                lst.addItem(it0)
            for u in self._project_users:
                name = (u.get("name") or "").strip()
                login = (u.get("login") or "").strip()
                email = (u.get("email") or "").strip()
                line = _format_human_user_display(u)
                if not line:
                    line = str(u.get("id", ""))
                if q and q not in name.lower() and q not in login.lower():
                    if email and q not in email.lower():
                        continue
                it = QListWidgetItem(line)
                it.setData(Qt.ItemDataRole.UserRole, u)
                lst.addItem(it)

        _fill("")
        search.textChanged.connect(_fill)

        def _on_item_clicked(item: QListWidgetItem) -> None:
            u = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(u, dict):
                return
            if u.get("_bpe_roster_all"):
                self._assignee_all_mode = True
                self._user_id = None
                self._assignee_resolved_display = None
                self._roster_page = 1
                self._user_edit.setText("All Tasks")
                self._show_user_id_badge("프로젝트 Shot Task 전체", success=True)
                popup.hide()
                return
            if u.get("id") is None:
                return
            self._apply_user_from_dict(u)
            popup.hide()

        lst.itemClicked.connect(_on_item_clicked)

        popup.setFixedSize(400, 420)
        g = self._user_list_btn.mapToGlobal(QPoint(0, self._user_list_btn.height()))
        popup.move(g)
        self._user_assignee_popup = popup
        popup.show()
        QTimer.singleShot(0, search.setFocus)

    def _update_roster_pager_ui(self) -> None:
        if not getattr(self, "_pager_host", None):
            return
        vis = self._assignee_all_mode
        self._pager_host.setVisible(vis)
        if not vis:
            return
        max_page = max(
            1, (self._roster_total + self._roster_page_size - 1) // self._roster_page_size
        )
        self._pager_prev.setEnabled(self._roster_page > 1)
        self._pager_next.setEnabled(self._roster_page < max_page)
        self._pager_info.setText(
            f"페이지 {self._roster_page}/{max_page} · 전체 {self._roster_total}건 (All Tasks)"
        )

    def _roster_prev_page(self) -> None:
        if not self._assignee_all_mode or self._roster_page <= 1:
            return
        self._roster_page -= 1
        self._refresh(reset_status=False)

    def _roster_next_page(self) -> None:
        if not self._assignee_all_mode:
            return
        max_page = max(
            1, (self._roster_total + self._roster_page_size - 1) // self._roster_page_size
        )
        if self._roster_page >= max_page:
            return
        self._roster_page += 1
        self._refresh(reset_status=False)

    def _roster_page_size_committed(self) -> None:
        if not self._assignee_all_mode:
            return
        raw = self._pager_size_edit.text().strip()
        try:
            n = int(raw)
        except ValueError:
            n = 100
        n = max(10, min(500, n))
        self._pager_size_edit.setText(str(n))
        if n == self._roster_page_size:
            return
        self._roster_page_size = n
        self._roster_page = 1
        self._refresh(reset_status=False)

    # ── Sort / status filter UI ─────────────────────────────────────

    def _on_sort_combo_changed(self) -> None:
        if not self._all_tasks:
            return
        self._apply_filter_and_sort()

    def _toggle_sort_direction(self) -> None:
        if not self._all_tasks:
            return
        self._sort_ascending = not self._sort_ascending
        self._update_sort_dir_button()
        self._apply_filter_and_sort()

    def _update_sort_dir_button(self) -> None:
        if self._sort_ascending:
            self._sort_dir_btn.setText("\u25b2")
            self._sort_dir_btn.setToolTip("오름차순 (클릭하면 내림차순)")
        else:
            self._sort_dir_btn.setText("\u25bc")
            self._sort_dir_btn.setToolTip("내림차순 (클릭하면 오름차순)")

    def _count_statuses(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self._all_tasks:
            code = _normalize_task_status(t)
            if not code:
                continue
            counts[code] = counts.get(code, 0) + 1
        return counts

    def _build_status_buttons(self) -> None:
        while self._status_layout.count():
            item = self._status_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._status_btn_map.clear()

        if self._assignee_all_mode:
            n_all = int(self._roster_total_all)
            counts = (
                dict(self._status_counts_sg) if self._status_counts_sg else self._count_statuses()
            )
        else:
            counts = self._count_statuses()
            n_all = len(self._all_tasks)

        def _add_btn(code: str, label: str, n: int) -> None:
            btn = QPushButton(f"{label}\n{n}")
            btn.setMinimumSize(44, 44)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, c=code: self._on_status_clicked(c))
            self._status_btn_map[code] = btn
            self._status_layout.addWidget(btn)

        _add_btn("all", "ALL", n_all)
        for code in _STATUS_ORDER:
            cnt = counts.get(code, 0)
            if cnt <= 0:
                continue
            _add_btn(code, code.upper(), cnt)
        self._update_status_button_styles()

    def _set_status_button_style(self, btn: QPushButton, code: str, is_active: bool) -> None:
        r = theme.INPUT_RADIUS
        if code == "all":
            if is_active:
                ss = (
                    f"QPushButton {{ background-color: {theme.ACCENT}; color: #ffffff; "
                    f"border: 2px solid {theme.ACCENT}; border-radius: {r}px; "
                    f"font-weight: 700; font-size: 11px; padding: 4px 6px; "
                    f"min-width: 0; min-height: 0; }}"
                )
            else:
                ss = (
                    f"QPushButton {{ background-color: {theme.PANEL_BG}; color: {theme.TEXT}; "
                    f"border: 1px solid {theme.BORDER}; border-radius: {r}px; "
                    f"font-weight: 600; font-size: 11px; padding: 4px 6px; "
                    f"min-width: 0; min-height: 0; }}"
                )
            btn.setStyleSheet(ss)
            return
        bg, fg = _status_cell_colors(code)
        if is_active:
            ss = (
                f"QPushButton {{ background-color: {bg}; color: {fg}; "
                f"border: 2px solid {theme.ACCENT}; border-radius: {r}px; "
                f"font-weight: 700; font-size: 11px; padding: 4px 6px; "
                f"min-width: 0; min-height: 0; }}"
            )
        else:
            label = _inactive_status_label_color(bg, fg)
            ss = (
                f"QPushButton {{ background-color: {theme.PANEL_BG}; color: {label}; "
                f"border: 1px solid {theme.BORDER}; border-radius: {r}px; "
                f"font-weight: 600; font-size: 11px; padding: 4px 6px; "
                f"min-width: 0; min-height: 0; }}"
            )
        btn.setStyleSheet(ss)

    def _update_status_button_styles(self) -> None:
        for code, btn in self._status_btn_map.items():
            self._set_status_button_style(btn, code, code == self._active_status)

    def _on_status_clicked(self, code: str) -> None:
        if self._active_status == code:
            return
        if self._assignee_all_mode:
            self._active_status = code
            self._roster_page = 1
            self._update_status_button_styles()
            self._refresh(reset_status=False)
            return
        if not self._all_tasks:
            return
        self._active_status = code
        self._update_status_button_styles()
        self._apply_filter_and_sort()

    def _apply_filter_and_sort(self) -> None:
        merged = self._merged_tasks_for_display()
        if not merged:
            self._clear_cards()
            if self._assignee_all_mode and self._roster_total > 0:
                self._loading_label.setText(
                    f"이 페이지에 표시할 Task 없음 (전체 {self._roster_total}건, "
                    f"상태·페이지를 바꿔 보세요)"
                )
            else:
                self._loading_label.setText("0개 Task 로드됨")
            return

        filtered = _filter_tasks_by_status(merged, self._active_status)
        filtered = _filter_tasks_by_tag(filtered, self._tag_filter_value)
        if self._shot_focus_shot_id is not None:
            try:
                fid = int(self._shot_focus_shot_id)
            except (TypeError, ValueError):
                fid = None
            if fid is not None:
                filtered = [
                    t
                    for t in filtered
                    if t.get("shot_id") is not None and int(t.get("shot_id") or 0) == fid
                ]

        mode_raw = self._sort_combo.currentData()
        mode = int(mode_raw) if mode_raw is not None else _SORT_MODE_SHOT
        sorted_tasks = _sort_tasks_by_mode(filtered, mode, self._sort_ascending)

        self._clear_cards()
        for t in sorted_tasks:
            card = _ShotCard(
                t,
                publish_callback=self._open_publish_dialog,
                shot_builder_callback=self._open_shot_builder_dialog,
                select_callback=self._on_shot_card_selected,
            )
            self._cards.append(card)
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

        for card in self._cards:
            self._load_thumbnail(card)
            self._apply_cached_version_to_card(card)

        tag_note = " · 태그 필터" if (self._tag_filter_value or "").strip() else ""
        shot_note = " · 샷 검색" if self._shot_focus_shot_id is not None else ""

        if self._assignee_all_mode:
            max_page = max(
                1, (self._roster_total + self._roster_page_size - 1) // self._roster_page_size
            )
            self._loading_label.setText(
                f"{len(sorted_tasks)}개 표시 · 페이지 {self._roster_page}/{max_page} "
                f"(전체 {self._roster_total}건){tag_note}{shot_note}"
            )
        else:
            self._loading_label.setText(
                f"{len(sorted_tasks)}개 표시 (전체 {len(self._all_tasks)}개 Task)"
                f"{tag_note}{shot_note}"
            )

        self._clear_versions_panel()
        if self._right_stack.currentIndex() == 1 and self._shot_focus_shot_id is None:
            self._versions_shot_lbl.setText("")
            self._add_version_placeholder("샷을 선택하세요.")

        if self._shot_focus_shot_id is not None:
            try:
                fid = int(self._shot_focus_shot_id)
            except (TypeError, ValueError):
                fid = None
            if fid is not None:
                for c in self._cards:
                    sid = c.task_data.get("shot_id")
                    if sid is None:
                        continue
                    try:
                        if int(sid) == fid:
                            self._on_shot_card_selected(c)
                            break
                    except (TypeError, ValueError):
                        continue
        elif not self._assignee_all_mode and self._last_shot_ids:
            self._load_notes(self._last_shot_ids, days_back=14)

    def _apply_cached_version_to_card(self, card: _ShotCard) -> None:
        k = _version_cache_key(card.task_data)
        v = self._version_cache.get(k)
        if v:
            card.set_comp_version_label(v)
        else:
            card.set_comp_version_label("")

    def _refresh_version_labels_on_cards(self) -> None:
        for card in self._cards:
            self._apply_cached_version_to_card(card)

    # ── Refresh / fetch tasks ───────────────────────────────────────

    def _refresh(self, *, reset_status: bool = True) -> None:
        self._hide_user_autocomplete_combo()
        if reset_status:
            self._clear_shot_and_tag_filters()
        project_id = self._project_combo.currentData()
        if self._assignee_all_mode:
            if project_id is None:
                self._loading_label.setText("All Tasks 조회는 프로젝트를 선택해야 합니다.")
                return
        elif self._user_id is None:
            self._loading_label.setText("담당자를 먼저 선택하세요.")
            return

        if reset_status:
            self._active_status = "all"
            if self._assignee_all_mode:
                self._roster_page = 1

        user_id = self._user_id

        self._skip_project_notes_on_next_tasks_load = self._assignee_all_mode and not reset_status

        self._loading_label.setText("조회 중...")
        self._clear_cards()
        self._start_spinner(self._shot_spinner_lbl)

        def _fetch() -> Any:
            sg = get_default_sg()
            if self._assignee_all_mode and project_id is not None:
                pid = int(project_id)
                st = None if self._active_status == "all" else self._active_status
                b = load_my_tasks_all_tasks_bundle(
                    sg,
                    pid,
                    page_1based=self._roster_page,
                    page_size=self._roster_page_size,
                    task_content="",
                    status_filter_active=st,
                )
                return {
                    "_bpe_bundle": True,
                    "tasks": b.get("tasks") or [],
                    "status_counts": b.get("status_counts") or {},
                    "total": int(b.get("total") or 0),
                    "total_all": int(b.get("total_all") or 0),
                }
            return list_comp_tasks_for_project_user(
                sg,
                project_id=project_id,
                human_user_id=int(user_id),
                status_filter=None,
                task_content="",
            )

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_tasks_loaded)

        def _on_refresh_error(msg: str) -> None:
            self._stop_spinner(self._shot_spinner_lbl)
            self._loading_label.setText(f"오류: {msg}")

        w.error.connect(_on_refresh_error)
        w.start()
        self._workers.append(w)

    def _on_tasks_loaded(self, result: object) -> None:
        self._stop_spinner(self._shot_spinner_lbl)
        if isinstance(result, dict) and result.get("_bpe_bundle"):
            tasks = result.get("tasks") if isinstance(result.get("tasks"), list) else []
            sc = result.get("status_counts")
            self._status_counts_sg = sc if isinstance(sc, dict) else {}
            try:
                self._roster_total = int(result.get("total") or 0)
            except (TypeError, ValueError):
                self._roster_total = 0
            try:
                self._roster_total_all = int(result.get("total_all") or 0)
            except (TypeError, ValueError):
                self._roster_total_all = 0
        else:
            tasks = result if isinstance(result, list) else []
            self._status_counts_sg = {}
            self._roster_total = 0
            self._roster_total_all = 0

        self._all_tasks = tasks
        self._reset_notes_header_to_default()
        self._version_cache.clear()

        if not tasks:
            self._current_project_code = None
        else:
            t0 = tasks[0]
            self._current_project_code = (
                t0.get("project_code") or t0.get("project_folder") or ""
            ).strip() or None

        self._sort_combo.blockSignals(True)
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.blockSignals(False)
        self._sort_ascending = True
        self._update_sort_dir_button()

        shot_ids = [int(t.get("shot_id")) for t in tasks if t.get("shot_id") is not None]
        self._last_shot_ids = shot_ids
        if not shot_ids:
            self._clear_notes()
            if not (self._assignee_all_mode and self._project_combo.currentData() is not None):
                self._add_note_placeholder("조회된 샷이 없습니다.")
                self._reset_notes_header_to_default()

        self._build_status_buttons()
        self._apply_filter_and_sort()
        self._update_roster_pager_ui()

        pid_notes = self._project_combo.currentData()
        if (
            self._assignee_all_mode
            and pid_notes is not None
            and not self._skip_project_notes_on_next_tasks_load
            and self._shot_focus_shot_id is None
        ):
            self._load_project_notes(int(pid_notes))
        self._skip_project_notes_on_next_tasks_load = False

        # Local comp NK 기준 Version 라벨 (백그라운드, 전체 태스크 기준 캐시)
        self._version_req_seq += 1
        vseq = self._version_req_seq
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        tasks_for_scan = list(tasks)

        def _scan_versions() -> List[Optional[str]]:
            out: List[Optional[str]] = []
            for t in tasks_for_scan:
                shot = (t.get("shot_code") or "").strip()
                proj = (t.get("project_code") or t.get("project_folder") or "").strip()
                if not shot or not proj:
                    out.append(None)
                    continue
                server_root = find_server_root_auto(proj) or env_root
                if not server_root:
                    out.append(None)
                    continue
                try:
                    ver = find_latest_comp_version_display(shot, proj, server_root)
                except Exception:
                    ver = None
                out.append(ver)
            return out

        vw = ShotGridWorker(_scan_versions)
        vw.finished.connect(lambda res: self._on_version_scan_done(res, vseq))
        vw.start()
        self._workers.append(vw)

    def _clear_cards(self) -> None:
        if self._selected_shot_card is not None:
            self._selected_shot_card.set_selected(False)
            self._selected_shot_card = None
        for card in self._cards:
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def _on_note_navigate_to_shot(self, shot_ids: List[int]) -> None:
        """노트 클릭: 샷 목록에서 해당 카드만 하이라이트·스크롤 (노트 패널 내용은 그대로)."""
        ids_set: Set[int] = set()
        for x in shot_ids:
            try:
                ids_set.add(int(x))
            except (TypeError, ValueError):
                continue
        if not ids_set:
            return
        if self._selected_shot_card is not None:
            self._selected_shot_card.set_selected(False)
            self._selected_shot_card = None
        for card in self._cards:
            sid = card.task_data.get("shot_id")
            if sid is None:
                continue
            try:
                if int(sid) in ids_set:
                    card.set_selected(True)
                    self._selected_shot_card = card
                    self._card_area.ensureWidgetVisible(card)
                    return
            except (TypeError, ValueError):
                continue

    def _open_note_render_in_rv(self, rec: Dict[str, Any]) -> None:
        """Notes에서 연결된 ShotGrid Version 코드 기준 comp 렌더 MOV를 RV로 연다."""
        version_code: Optional[str] = rec.get("version_code")
        if not version_code:
            logger.warning("RV 렌더: 노트에 연결된 ShotGrid Version 없음")
            return
        proj = self._current_project_code
        if not proj:
            logger.warning("RV 렌더: 현재 조회 프로젝트 코드 없음")
            return
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = find_server_root_auto(proj) or env_root
        if not server_root:
            logger.warning(
                "RV 렌더: 서버 루트를 찾을 수 없음 (project=%s)",
                proj,
            )
            return
        raw_names = rec.get("shot_names")
        shot_names: List[str] = []
        if isinstance(raw_names, list):
            for x in raw_names:
                s = str(x).strip()
                if s:
                    shot_names.append(s)
        if not shot_names:
            logger.warning("RV 렌더: 노트에 연결된 샷 이름 없음")
            return
        for shot_code in shot_names:
            if open_comp_render_in_rv(shot_code, proj, server_root, version_code=version_code):
                logger.info(
                    "RV 렌더 열기: shot=%s project=%s version=%s",
                    shot_code,
                    proj,
                    version_code,
                )
                return
        logger.warning(
            "RV 렌더 열기 실패 (mov 없음 또는 RV 없음): shots=%s version=%s",
            shot_names,
            version_code,
        )

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

    def _on_version_scan_done(self, result: object, seq: int) -> None:
        if seq != self._version_req_seq:
            return
        versions = result if isinstance(result, list) else []
        self._version_cache.clear()
        for i, t in enumerate(self._all_tasks):
            if i >= len(versions):
                break
            key = _version_cache_key(t)
            raw = versions[i]
            if isinstance(raw, str) and raw.strip():
                self._version_cache[key] = raw.strip()
            else:
                self._version_cache[key] = None
        self._refresh_version_labels_on_cards()

    def _reset_notes_header_to_default(self) -> None:
        self._note_title_lbl.setText("Notes")
        self._note_sub_lbl.setText("최근 2주 코멘트")
        self._note_refresh_btn.setText("노트 새로고침")
        self._note_refresh_btn.setToolTip("")

    def _update_notes_header_for_shot(self, shot_code: str) -> None:
        sc = (shot_code or "").strip() or "—"
        self._note_title_lbl.setText(f"Notes — {sc}")
        self._note_sub_lbl.setText("이 샷의 전체 노트 기록")
        self._note_refresh_btn.setText("↩ 전체 보기")
        self._note_refresh_btn.setToolTip("클릭하면 전체 샷 최근 2주 코멘트로 돌아갑니다")

    def _on_shot_card_selected(self, card: _ShotCard) -> None:
        if self._selected_shot_card is not None and self._selected_shot_card is not card:
            self._selected_shot_card.set_selected(False)
        self._selected_shot_card = card
        card.set_selected(True)
        sid = card.task_data.get("shot_id")
        shot_code = (card.task_data.get("shot_code") or "").strip()
        if sid is None:
            return
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            return
        self._update_notes_header_for_shot(shot_code)
        self._load_notes([sid_i], days_back=0)
        if self._right_stack.currentIndex() == 1:
            self._load_versions_for_shot_task(card.task_data)

    # ── Notes panel ──────────────────────────────────────────────────

    def _refresh_notes_clicked(self) -> None:
        if self._assignee_all_mode:
            pid = self._project_combo.currentData()
            if pid is None:
                self._loading_label.setText("All Tasks 조회는 프로젝트를 선택해야 합니다.")
                return
            had_shot_focus = self._shot_focus_shot_id is not None
            if had_shot_focus:
                self._clear_shot_focus_only()
            if self._selected_shot_card is not None:
                self._selected_shot_card.set_selected(False)
                self._selected_shot_card = None
            self._reset_notes_header_to_default()
            self._note_sub_lbl.setText("프로젝트 전체 · 최근 2주")
            self._clear_versions_panel()
            if self._right_stack.currentIndex() == 1:
                self._versions_shot_lbl.setText("")
                self._add_version_placeholder("샷을 선택하세요.")
            self._switch_right_panel(0)
            self._load_project_notes(int(pid))
            if had_shot_focus:
                self._apply_filter_and_sort()
            return
        if self._shot_focus_shot_id is not None:
            self._clear_shot_focus_only()
            self._apply_filter_and_sort()
            return
        if not self._last_shot_ids:
            self._loading_label.setText("먼저 조회를 실행하세요.")
            return
        if self._selected_shot_card is not None:
            self._selected_shot_card.set_selected(False)
            self._selected_shot_card = None
        self._reset_notes_header_to_default()
        self._clear_versions_panel()
        if self._right_stack.currentIndex() == 1:
            self._versions_shot_lbl.setText("")
            self._add_version_placeholder("샷을 선택하세요.")
        self._switch_right_panel(0)
        self._load_notes(self._last_shot_ids, days_back=14)

    def _load_notes(self, shot_ids: List[int], days_back: int = 14) -> None:
        self._notes_req_seq += 1
        seq = self._notes_req_seq
        ids = [int(sid) for sid in shot_ids if sid is not None][:150]
        self._loading_label.setText("노트 불러오는 중...")
        self._start_spinner(self._note_spinner_lbl)

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_notes_for_shots(sg, ids, days_back=int(days_back))

        def _on_done(result: object) -> None:
            if seq != self._notes_req_seq:
                return
            notes: List[Dict[str, Any]] = result if isinstance(result, list) else []
            self._loading_label.setText("")
            self._stop_spinner(self._note_spinner_lbl)
            self._render_notes(notes)

        def _on_error(msg: str) -> None:
            if seq != self._notes_req_seq:
                return
            self._loading_label.setText("")
            self._stop_spinner(self._note_spinner_lbl)
            logger.warning("노트 로드 실패: %s", msg)
            self._clear_notes()
            self._add_note_placeholder("노트 로드 실패")

        w = ShotGridWorker(_fetch)
        w.finished.connect(_on_done)
        w.error.connect(_on_error)
        w.start()
        self._workers.append(w)

    def _load_project_notes(self, project_id: int) -> None:
        self._notes_req_seq += 1
        seq = self._notes_req_seq
        self._loading_label.setText("노트 불러오는 중...")
        self._note_sub_lbl.setText("프로젝트 전체 · 최근 2주")
        self._start_spinner(self._note_spinner_lbl)

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_notes_for_project(sg, int(project_id), days_back=14)

        def _on_done(result: object) -> None:
            if seq != self._notes_req_seq:
                return
            notes: List[Dict[str, Any]] = result if isinstance(result, list) else []
            self._loading_label.setText("")
            self._stop_spinner(self._note_spinner_lbl)
            self._render_notes(notes)

        def _on_error(msg: str) -> None:
            if seq != self._notes_req_seq:
                return
            self._loading_label.setText("")
            self._stop_spinner(self._note_spinner_lbl)
            logger.warning("프로젝트 노트 로드 실패: %s", msg)
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
        raw_ids = rec.get("shot_ids") or []
        shot_ids: List[int] = []
        for x in raw_ids:
            try:
                shot_ids.append(int(x))
            except (TypeError, ValueError):
                pass
        card = _NoteCardFrame(shot_ids, self._on_note_navigate_to_shot)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        proj = (rec.get("project_name") or "—").strip()
        author = (rec.get("author") or "—").strip()
        context = (rec.get("context") or "—").strip()
        ts = (rec.get("timestamp") or "—").strip()
        meta = f"{proj}  ·  {author}  ·  {context}  ·  {ts}"

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_label = QLabel(meta)
        meta_label.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
        meta_label.setWordWrap(True)
        meta_row.addWidget(meta_label, 1)
        version_code: Optional[str] = rec.get("version_code")
        rv_btn = QPushButton("\u25b6")
        rv_btn.setFixedSize(22, 22)
        if version_code:
            rv_btn.setToolTip(f"렌더 MOV RV로 열기 ({version_code})")
            rv_btn.setEnabled(True)
            rv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rv_btn.setStyleSheet(
                f"QPushButton {{ color: {theme.ACCENT}; background: transparent; "
                f"border: 1px solid {theme.ACCENT}; border-radius: 4px; "
                f"font-size: 9px; padding: 0; }}"
                f"QPushButton:hover {{ background: rgba(45, 139, 122, 0.12); }}"
            )
        else:
            rv_btn.setToolTip("연결된 ShotGrid Version 없음 — RV 열기 불가")
            rv_btn.setEnabled(False)
            rv_btn.setStyleSheet(
                f"QPushButton {{ color: {theme.TEXT_DIM}; background: transparent; "
                f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
                f"font-size: 9px; padding: 0; }}"
            )
        rv_btn.clicked.connect(lambda _checked=False, r=rec: self._open_note_render_in_rv(r))
        meta_row.addWidget(rv_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(meta_row)

        raw = (rec.get("content") or rec.get("subject") or "—").strip()
        body = raw.strip() or "—"
        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet(f"color: {theme.TEXT}; border: none;")
        body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        body_label.setCursor(Qt.CursorShape.IBeamCursor)
        lay.addWidget(body_label)

        note_id = rec.get("note_id")
        if note_id is not None:
            self._load_note_attachments(int(note_id), card, lay, self._notes_req_seq)

        card.wire_click_filters()
        return card

    def _load_note_attachments(
        self, note_id: int, card: _NoteCardFrame, card_lay: QVBoxLayout, seq: int
    ) -> None:
        def _fetch() -> List[Optional[bytes]]:
            sg = get_default_sg()
            metas = get_note_attachments(sg, note_id)
            out: List[Optional[bytes]] = []
            for m in metas:
                out.append(download_attachment_bytes(sg, m))
            return out

        def _on_done(result: object) -> None:
            if seq != self._notes_req_seq:
                return
            if not isinstance(result, list):
                return
            valid: List[bytes] = [d for d in result if isinstance(d, bytes)]
            if not valid:
                return

            img_host = QWidget(card)
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
            card_lay.addWidget(img_host)
            card.wire_click_filters()

        w = ShotGridWorker(_fetch)
        w.finished.connect(_on_done)
        w.start()
        self._workers.append(w)

    # ── Right panel toggle ────────────────────────────────────────────

    def _switch_right_panel(self, idx: int) -> None:
        self._right_stack.setCurrentIndex(idx)
        for i, btn in enumerate([self._notes_panel_btn, self._versions_panel_btn]):
            btn.setProperty("selected", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if idx == 1:
            self._maybe_load_versions_panel()

    def _clear_versions_panel(self) -> None:
        for w in self._version_widgets:
            self._versions_layout.removeWidget(w)
            w.deleteLater()
        self._version_widgets.clear()

    def _add_version_placeholder(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("page_subtitle")
        self._versions_layout.insertWidget(self._versions_layout.count() - 1, lbl)
        self._version_widgets.append(lbl)

    def _maybe_load_versions_panel(self) -> None:
        if self._selected_shot_card is None:
            self._clear_versions_panel()
            self._versions_shot_lbl.setText("")
            self._add_version_placeholder("샷을 선택하세요.")
            return
        self._load_versions_for_shot_task(self._selected_shot_card.task_data)

    def _refresh_versions_clicked(self) -> None:
        self._maybe_load_versions_panel()

    def _load_versions_for_shot_task(self, task_data: Dict[str, Any]) -> None:
        sid = task_data.get("shot_id")
        shot_code = (task_data.get("shot_code") or "").strip()
        if sid is None:
            self._clear_versions_panel()
            self._add_version_placeholder("샷 ID 없음")
            return
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            self._clear_versions_panel()
            self._add_version_placeholder("샷 ID 없음")
            return
        self._clear_versions_panel()
        self._add_version_placeholder("버전 불러오는 중…")
        self._versions_shot_lbl.setText(shot_code or f"Shot #{sid_i}")
        self._versions_req_seq += 1
        seq = self._versions_req_seq
        self._start_spinner(self._ver_spinner_lbl)

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_versions_for_shot(sg, sid_i)

        def _on_done(result: object) -> None:
            if seq != self._versions_req_seq:
                return
            rows = result if isinstance(result, list) else []
            self._stop_spinner(self._ver_spinner_lbl)
            self._render_versions_list(rows, shot_code)

        def _on_error(msg: str) -> None:
            if seq != self._versions_req_seq:
                return
            self._stop_spinner(self._ver_spinner_lbl)
            logger.warning("버전 로드 실패: %s", msg)
            self._clear_versions_panel()
            self._add_version_placeholder("버전 로드 실패")

        w = ShotGridWorker(_fetch)
        w.finished.connect(_on_done)
        w.error.connect(_on_error)
        w.start()
        self._workers.append(w)

    def _render_versions_list(self, rows: List[Dict[str, Any]], shot_code: str) -> None:
        self._clear_versions_panel()
        if not rows:
            self._add_version_placeholder("연결된 버전이 없습니다.")
            return
        for rec in rows:
            code = (rec.get("code") or "").strip() or "—"
            artist = (rec.get("artist") or "—").strip()
            st = (rec.get("status") or "").strip()
            ts = (rec.get("created_at_display") or "—").strip()
            thumb_url = (rec.get("thumb_url") or "").strip()
            row_fr = QFrame()
            row_fr.setObjectName("card")
            main_row = QHBoxLayout(row_fr)
            main_row.setContentsMargins(10, 8, 10, 8)
            main_row.setSpacing(10)

            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(_VERSION_THUMB_W, _VERSION_THUMB_H)
            thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_lbl.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
            thumb_lbl.setText("—")
            main_row.addWidget(thumb_lbl, 0, Qt.AlignmentFlag.AlignTop)
            if thumb_url:
                self._load_version_thumbnail(thumb_lbl, thumb_url)

            rcol = QVBoxLayout()
            rcol.setSpacing(4)
            top = QHBoxLayout()
            name_lbl = QLabel(code)
            name_lbl.setStyleSheet(f"font-weight: bold; border: none; color: {theme.ACCENT};")
            name_lbl.setWordWrap(True)
            top.addWidget(name_lbl, 1)
            play_btn = QPushButton("\u25b6")
            play_btn.setFixedSize(28, 28)
            play_btn.setToolTip("렌더 MOV RV로 열기")
            play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            play_btn.setStyleSheet(
                f"QPushButton {{ color: {theme.ACCENT}; background: transparent; "
                f"border: 1px solid {theme.ACCENT}; border-radius: 4px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: rgba(45, 139, 122, 0.12); }}"
            )
            play_btn.clicked.connect(
                lambda _c=False, vc=code, sc=shot_code: self._open_version_in_rv(vc, sc)
            )
            top.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignTop)
            rcol.addLayout(top)
            meta = QLabel(f"Artist: {artist}  ·  {ts}")
            meta.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
            meta.setWordWrap(True)
            rcol.addWidget(meta)
            bg, fg = _status_cell_colors(st)
            st_bar = QLabel(f"Status: {st or '—'}")
            st_bar.setStyleSheet(_version_status_bar_style(bg, fg, alpha=0.42))
            rcol.addWidget(st_bar)
            raw_desc = (rec.get("description") or "").strip()
            if raw_desc:
                desc_te = QPlainTextEdit()
                desc_te.setObjectName("version_description")
                desc_te.setReadOnly(True)
                desc_te.setPlainText(_normalize_version_description_for_display(raw_desc))
                desc_te.setFixedHeight(_VERSION_DESC_EDIT_MAX_H)
                desc_te.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
                desc_te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                desc_te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                desc_te.setTabChangesFocus(False)
                rcol.addWidget(desc_te)
            main_row.addLayout(rcol, 1)

            self._versions_layout.insertWidget(self._versions_layout.count() - 1, row_fr)
            self._version_widgets.append(row_fr)

    def _load_version_thumbnail(self, label: QLabel, img_url: str) -> None:
        if not img_url or not isinstance(img_url, str):
            return

        def _download() -> Optional[bytes]:
            import urllib.request

            try:
                with urllib.request.urlopen(img_url, timeout=12) as resp:
                    return resp.read()
            except Exception:
                return None

        w = ShotGridWorker(_download)
        w.finished.connect(lambda data, lbl=label: self._apply_version_thumbnail(lbl, data))
        w.start()
        self._workers.append(w)

    def _apply_version_thumbnail(self, label: QLabel, data: object) -> None:
        if not data or not isinstance(data, bytes):
            return
        pm = QPixmap()
        pm.loadFromData(data)
        if pm.isNull():
            return
        scaled = pm.scaled(
            _VERSION_THUMB_W,
            _VERSION_THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - _VERSION_THUMB_W) // 2)
        y = max(0, (scaled.height() - _VERSION_THUMB_H) // 2)
        cropped = scaled.copy(QRect(x, y, _VERSION_THUMB_W, _VERSION_THUMB_H))
        label.setPixmap(cropped)
        label.setText("")

    def _open_version_in_rv(self, version_code: str, shot_code: str) -> None:
        vc = (version_code or "").strip()
        sc = (shot_code or "").strip()
        if not vc or not sc:
            return
        proj = self._current_project_code
        if not proj:
            logger.warning("RV 버전: 프로젝트 코드 없음")
            return
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = find_server_root_auto(proj) or env_root
        if not server_root:
            logger.warning("RV 버전: 서버 루트 없음")
            return
        if open_comp_render_in_rv(sc, proj, server_root, version_code=vc):
            logger.info("RV 버전 열기: shot=%s version=%s", sc, vc)
        else:
            logger.warning("RV 버전 열기 실패: shot=%s version=%s", sc, vc)

    # ── Publish / Shot Builder dialogs ───────────────────────────────

    def _open_publish_dialog(self, task_data: Dict[str, Any]) -> None:
        from bpe.gui.tabs.publish_tab import PublishTab

        pub_uid: Optional[int] = self._user_id
        if pub_uid is None and self._me_sg_user and self._me_sg_user.get("id") is not None:
            pub_uid = int(self._me_sg_user["id"])
        if pub_uid is None:
            QMessageBox.warning(
                self,
                "담당자 미선택",
                "퍼블리쉬할 ShotGrid 사용자가 없습니다.\n"
                "담당자를 선택하거나 My Tasks로 이 PC 사용자를 먼저 인식해 주세요.",
            )
            return

        user_name = self._user_edit.text().strip()
        if not user_name and self._me_sg_user:
            user_name = _format_human_user_display(self._me_sg_user)

        dlg = QDialog(self)
        dlg.setWindowTitle("퍼블리쉬")
        dlg.setMinimumSize(1050, 880)
        dlg.resize(1100, 940)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        pub = PublishTab(task_data, pub_uid, user_name=user_name)
        lay.addWidget(pub)

        dlg.exec()

    def _open_shot_builder_dialog(self, task_data: Dict[str, Any]) -> None:
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab

        dlg = QDialog(self)
        dlg.setWindowTitle("Shot Builder")
        dlg.setMinimumSize(900, 750)
        dlg.resize(960, 820)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        sb = ShotBuilderTab(task_data=task_data)
        lay.addWidget(sb)
        dlg.exec()
