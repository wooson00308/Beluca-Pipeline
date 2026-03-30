"""My Tasks tab — ShotGrid comp task list with thumbnails, NukeX open, shot folder."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices,
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
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
from bpe.gui import theme
from bpe.gui.widgets.clickable_image import ClickableImage
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.notes import download_attachment_bytes, get_note_attachments, list_notes_for_shots
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.tasks import list_comp_tasks_for_project_user
from bpe.shotgrid.users import guess_human_user_for_me, list_project_assignees, search_human_users
from bpe.shotgrid.versions import list_versions_for_shot

logger = get_logger("gui.tabs.my_tasks_tab")

_AUTOCOMPLETE_DELAY = 350
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

# 상태 필터 버튼 순서 (ALL 제외)
_STATUS_ORDER = [
    "wtg",
    "assign",
    "wip",
    "retake",
    "cfrm",
    "tm",
    "sv",
    "cto",
    "cts",
    "ctr",
    "fin",
    "hld",
    "omt",
]

_SORT_MODE_SHOT = 0
_SORT_MODE_DELIVERY = 1

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
        copy_btn = QPushButton("\u29c9")
        copy_btn.setFixedSize(18, 18)
        copy_btn.setToolTip("샷 이름 복사")
        _copy_style_default = (
            f"QPushButton {{ color: {theme.ACCENT}; background: transparent; "
            f"border: 1px solid {theme.ACCENT}; border-radius: 3px; font-size: 10px; padding: 0; "
            f"min-width: 18px; min-height: 18px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT}; color: {theme.BG}; }}"
        )
        _copy_style_ok = (
            f"QPushButton {{ color: {theme.SUCCESS}; background: transparent; "
            f"border: 1px solid {theme.SUCCESS}; border-radius: 3px; font-size: 10px; padding: 0; "
            f"min-width: 18px; min-height: 18px; }}"
            f"QPushButton:hover {{ background: {theme.SUCCESS}; color: {theme.BG}; }}"
        )
        copy_btn.setStyleSheet(_copy_style_default)

        def _on_copy_shot_name() -> None:
            QApplication.clipboard().setText(shot_code)
            copy_btn.setStyleSheet(_copy_style_ok)
            QTimer.singleShot(800, lambda: copy_btn.setStyleSheet(_copy_style_default))

        copy_btn.clicked.connect(_on_copy_shot_name)
        title_row.addWidget(title)
        title_row.addWidget(copy_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
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

        sb_btn = QPushButton("샷 빌더")
        sb_btn.setMinimumWidth(80)
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
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._on_spinner_tick)
        self._spinner_labels: Set[QLabel] = set()
        self._spinner_frame_idx: int = 0

        self._user_timer = QTimer(self)
        self._user_timer.setSingleShot(True)
        self._user_timer.timeout.connect(self._do_user_search)

        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)
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

        # ── Filter bar (grid: row0=한 줄 정렬, row1=담당자 ID만 아래) ─────────────
        filter_grid = QGridLayout()
        filter_grid.setHorizontalSpacing(12)
        filter_grid.setVerticalSpacing(4)
        filter_grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        proj_label = QLabel("프로젝트")
        proj_label.setObjectName("form_label")
        proj_label.setMinimumWidth(50)
        proj_label.setMaximumWidth(60)
        filter_grid.addWidget(proj_label, 0, 0, Qt.AlignmentFlag.AlignVCenter)

        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(100)
        self._project_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._project_combo.addItem("-- 로딩 중 --")
        self._project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        filter_grid.addWidget(self._project_combo, 0, 1, Qt.AlignmentFlag.AlignVCenter)

        user_label = QLabel("담당자")
        user_label.setObjectName("form_label")
        user_label.setFixedWidth(50)
        filter_grid.addWidget(user_label, 0, 2, Qt.AlignmentFlag.AlignVCenter)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("이름 입력 후 선택")
        self._user_edit.setMinimumWidth(200)
        self._user_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._user_edit.textChanged.connect(lambda: self._user_timer.start(_AUTOCOMPLETE_DELAY))
        filter_grid.addWidget(self._user_edit, 0, 3, Qt.AlignmentFlag.AlignVCenter)

        self._user_info = QLabel("")
        self._user_info.setObjectName("user_id_badge")
        self._user_info.setVisible(False)
        self._user_info.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: 11px; padding: 0; margin: 0;"
        )
        filter_grid.addWidget(
            self._user_info, 1, 3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        # 검색 결과: 레이아웃에 넣지 않고 담당자 입력 아래에만 뜨는 드롭다운 (중복 줄 제거)
        self._user_combo = QComboBox(self)
        self._user_combo.setVisible(False)
        self._user_combo.setEditable(False)
        self._user_combo.setMaxVisibleItems(12)
        self._user_combo.currentIndexChanged.connect(self._on_user_selected)

        self._user_list_btn = QPushButton(f"Assigned To  {chr(0x25BE)}")
        self._user_list_btn.setObjectName("filter_combo_like_btn")
        self._user_list_btn.setMinimumWidth(130)
        self._user_list_btn.setToolTip("프로젝트에 배정된 담당자 목록")
        self._user_list_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_list_btn.clicked.connect(self._toggle_user_assignee_popup)
        filter_grid.addWidget(self._user_list_btn, 0, 4, Qt.AlignmentFlag.AlignVCenter)

        self._me_btn = QPushButton("My Tasks")
        self._me_btn.setFixedWidth(80)
        self._me_btn.clicked.connect(self._guess_me)
        filter_grid.addWidget(self._me_btn, 0, 5, Qt.AlignmentFlag.AlignVCenter)

        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Shot Name", _SORT_MODE_SHOT)
        self._sort_combo.addItem("Delivery Date", _SORT_MODE_DELIVERY)
        self._sort_combo.setMinimumWidth(100)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_combo_changed)
        filter_grid.addWidget(self._sort_combo, 0, 6, Qt.AlignmentFlag.AlignVCenter)

        self._sort_dir_btn = QPushButton("\u25b2")
        self._sort_dir_btn.setFixedSize(40, 40)
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
        filter_grid.addWidget(self._sort_dir_btn, 0, 7, Qt.AlignmentFlag.AlignVCenter)
        self._update_sort_dir_button()

        refresh_btn = QPushButton("  조회  ")
        refresh_btn.setProperty("primary", True)
        refresh_btn.clicked.connect(self._refresh)
        filter_grid.addWidget(refresh_btn, 0, 8, Qt.AlignmentFlag.AlignVCenter)

        filter_grid.setColumnStretch(1, 3)
        filter_grid.setColumnStretch(3, 4)
        filter_grid.setColumnStretch(9, 1)
        root.addLayout(filter_grid)

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
        shot_sub = QLabel("배정 태스크")
        shot_sub.setObjectName("page_subtitle")
        shot_hdr.addWidget(shot_sub)
        shot_hdr.addStretch()
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
        p = self._user_assignee_popup
        if p is None or not p.isVisible():
            return
        if new is None:
            return
        w: Optional[QWidget] = new
        while w is not None:
            if w is p:
                return
            w = w.parentWidget()
        p.hide()

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
        self._project_users.clear()
        pid = self._project_combo.currentData()
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
            self._user_info.setText("자동 감지 실패")
            self._user_info.setVisible(True)
            return
        self._user_id = user.get("id")
        name = user.get("name") or user.get("login") or ""
        self._user_edit.setText(str(name))
        self._user_edit.setCursorPosition(0)
        self._user_info.setText(f"✓ #{self._user_id}")
        self._user_info.setVisible(True)

    def _position_user_results_combo(self) -> None:
        """담당자 자동완성 콤보를 입력란 바로 아래에만 표시 (필터 줄 중복 위젯 없음)."""
        w = max(220, self._user_edit.width())
        self._user_combo.setFixedWidth(w)
        top_left = self._user_edit.mapTo(self, QPoint(0, self._user_edit.height()))
        self._user_combo.move(top_left.x(), top_left.y())
        self._user_combo.raise_()

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
        self._user_combo.blockSignals(True)
        self._user_combo.clear()
        self._user_combo.blockSignals(False)
        if users:
            for u in users:
                label = f"{u.get('name', '')} ({u.get('login', '')})"
                self._user_combo.addItem(label, u.get("id"))
            self._user_combo.setVisible(True)
            self._position_user_results_combo()
            QTimer.singleShot(0, self._position_user_results_combo)
            self._user_combo.showPopup()
        else:
            self._user_combo.setVisible(False)

    def _on_user_selected(self, idx: int) -> None:
        if idx < 0:
            return
        uid = self._user_combo.itemData(idx)
        if uid is None:
            return
        text = self._user_combo.itemText(idx)
        self._user_id = int(uid)
        self._user_info.setText(f"✓ #{self._user_id}")
        self._user_info.setVisible(True)
        self._user_edit.setText(text)
        self._user_edit.setCursorPosition(0)
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
            for u in self._project_users:
                name = (u.get("name") or "").strip()
                login = (u.get("login") or "").strip()
                email = (u.get("email") or "").strip()
                line = f"{name} ({login})" if login else name
                if email:
                    line = f"{line} ({email})"
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
            uid = u.get("id")
            if uid is None:
                return
            self._user_id = int(uid)
            name = (u.get("name") or "").strip()
            login = (u.get("login") or "").strip()
            if name and login:
                self._user_edit.setText(f"{name} ({login})")
            elif name:
                self._user_edit.setText(name)
            else:
                self._user_edit.setText(login or str(uid))
            self._user_edit.setCursorPosition(0)
            self._user_info.setText(f"✓ #{self._user_id}")
            self._user_info.setVisible(True)
            popup.hide()

        lst.itemClicked.connect(_on_item_clicked)

        popup.setFixedSize(400, 420)
        g = self._user_list_btn.mapToGlobal(QPoint(0, self._user_list_btn.height()))
        popup.move(g)
        self._user_assignee_popup = popup
        popup.show()
        QTimer.singleShot(0, search.setFocus)

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
        if not self._all_tasks:
            return
        if self._active_status == code:
            return
        self._active_status = code
        self._update_status_button_styles()
        self._apply_filter_and_sort()

    def _apply_filter_and_sort(self) -> None:
        if not self._all_tasks:
            self._clear_cards()
            self._loading_label.setText("0개 Task 로드됨")
            return

        filtered = _filter_tasks_by_status(self._all_tasks, self._active_status)
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

        self._loading_label.setText(
            f"{len(sorted_tasks)}개 표시 (전체 {len(self._all_tasks)}개 Task)"
        )

        if self._last_shot_ids:
            self._load_notes(self._last_shot_ids, days_back=14)
        self._clear_versions_panel()
        if self._right_stack.currentIndex() == 1:
            self._versions_shot_lbl.setText("")
            self._add_version_placeholder("샷을 선택하세요.")

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

    def _refresh(self) -> None:
        if self._user_id is None:
            self._loading_label.setText("담당자를 먼저 선택하세요.")
            return

        project_id = self._project_combo.currentData()
        user_id = self._user_id

        self._loading_label.setText("조회 중...")
        self._clear_cards()

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_comp_tasks_for_project_user(
                sg,
                project_id=project_id,
                human_user_id=user_id,
                status_filter=None,
                task_content="",
            )

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_tasks_loaded)
        w.error.connect(lambda e: self._loading_label.setText(f"오류: {e}"))
        w.start()
        self._workers.append(w)

    def _on_tasks_loaded(self, result: object) -> None:
        tasks: List[Dict[str, Any]] = result if isinstance(result, list) else []
        self._all_tasks = tasks
        self._reset_notes_header_to_default()
        self._active_status = "all"
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
            self._add_note_placeholder("조회된 샷이 없습니다.")
            self._reset_notes_header_to_default()

        self._build_status_buttons()
        self._apply_filter_and_sort()

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

        if self._user_id is None:
            QMessageBox.warning(self, "담당자 미선택", "담당자를 먼저 선택하세요.")
            return

        user_name = self._user_edit.text().strip()

        dlg = QDialog(self)
        dlg.setWindowTitle("퍼블리쉬")
        dlg.setMinimumSize(1050, 880)
        dlg.resize(1100, 940)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        pub = PublishTab(task_data, self._user_id, user_name=user_name)
        lay.addWidget(pub)

        dlg.exec()

    def _open_shot_builder_dialog(self, _task_data: Dict[str, Any]) -> None:
        from bpe.gui.tabs.shot_builder_tab import ShotBuilderTab

        dlg = QDialog(self)
        dlg.setWindowTitle("Shot Builder")
        dlg.setMinimumSize(900, 750)
        dlg.resize(960, 820)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        sb = ShotBuilderTab()
        lay.addWidget(sb)
        dlg.exec()
