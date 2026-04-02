"""Time Log dialog — PROD + shots uploaded on selected date (all projects)."""

from __future__ import annotations

import re
import urllib.request
from datetime import date
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui import theme
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.projects import find_project_by_code
from bpe.shotgrid.tasks import find_tasks_for_shot, list_tasks_for_project_assignee
from bpe.shotgrid.timelogs import create_time_log, sum_duration_minutes_for_user_date
from bpe.shotgrid.versions import list_shots_uploaded_by_user_on_date

logger = get_logger("gui.widgets.time_log_dialog")

PROD_PROJECT_CODE = "PROD"
_THUMB_W = 56
_THUMB_H = 42
_MAX_DURATION_MIN = 1440
_CAL_MIN_W = int(320 * 1.5)
_CAL_MIN_H = int(220 * 1.5)


def _format_duration_minutes(total: int) -> str:
    if total <= 0:
        return "0h 0m"
    h, m = divmod(int(total), 60)
    return f"{h}h {m}m"


def _format_minutes_for_field(mins: int) -> str:
    m = max(0, min(_MAX_DURATION_MIN, int(mins)))
    if m == 0:
        return ""
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}h {mm}m"
    if h:
        return f"{h}h"
    return f"{mm}m"


def _parse_duration_minutes(text: str) -> int:
    """Parse free-text duration into minutes (cap 24h). Supports e.g. 1h 30m, 2h, 90m, 1.5h."""
    s = (text or "").strip().lower()
    if not s:
        return 0
    total = 0.0
    rest = s
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*h", rest):
        total += float(m.group(1)) * 60.0
    rest = re.sub(r"\d+(?:\.\d+)?\s*h", " ", rest)
    for m in re.finditer(r"(\d+)\s*m", rest):
        total += float(m.group(1))
    rest = re.sub(r"\d+\s*m", " ", rest)
    rest_stripped = re.sub(r"\s+", "", rest)
    if total <= 0 and rest_stripped:
        if re.fullmatch(r"\d+(?:\.\d+)?", rest_stripped):
            val = float(rest_stripped)
            if val <= 24 and (val != int(val) or val <= 12):
                total = val * 60.0
            else:
                total = val
    out = int(round(total))
    return max(0, min(_MAX_DURATION_MIN, out))


def _calendar_dark_stylesheet() -> str:
    return f"""
    QCalendarWidget {{
        background-color: {theme.PANEL_BG};
        color: {theme.TEXT};
    }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background-color: {theme.INPUT_BG};
        color: {theme.TEXT};
    }}
    QCalendarWidget QToolButton {{
        background-color: {theme.INPUT_BG};
        color: {theme.TEXT};
        border: 1px solid {theme.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-weight: 600;
    }}
    QCalendarWidget QToolButton:hover {{
        border-color: {theme.BORDER_FOCUS};
    }}
    QCalendarWidget QTableView {{
        background-color: {theme.BG};
        alternate-background-color: {theme.PANEL_BG};
        color: {theme.TEXT};
        gridline-color: {theme.BORDER};
        selection-background-color: {theme.ACCENT};
        selection-color: #ffffff;
        font-size: 15px;
    }}
    QCalendarWidget QAbstractItemView:enabled {{
        font-size: 15px;
    }}
    """


def _apply_dark_date_edit(date_edit: QDateEdit) -> None:
    date_edit.setStyleSheet(
        f"QDateEdit {{ background-color: {theme.INPUT_BG}; color: {theme.TEXT}; "
        f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 6px 10px; }}"
        f"QDateEdit:focus {{ border-color: {theme.BORDER_FOCUS}; }}"
    )
    cal = date_edit.calendarWidget()
    cal.setMinimumSize(_CAL_MIN_W, _CAL_MIN_H)
    cal.setStyleSheet(_calendar_dark_stylesheet())
    cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)


class _DurationWidget(QWidget):
    """Manual duration text field; +1h / −1h below, right-aligned."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        placeholder: str = "Duration:",
    ) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        outer.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._minus = QPushButton("−1h")
        self._minus.setFixedSize(52, 32)
        self._minus.clicked.connect(self._on_minus_h)
        self._plus = QPushButton("+1h")
        self._plus.setFixedSize(52, 32)
        self._plus.clicked.connect(self._on_plus_h)
        btn_row.addWidget(self._minus)
        btn_row.addWidget(self._plus)
        outer.addLayout(btn_row)

    def _on_minus_h(self) -> None:
        m = _parse_duration_minutes(self._edit.text())
        self._edit.setText(_format_minutes_for_field(max(0, m - 60)))

    def _on_plus_h(self) -> None:
        m = _parse_duration_minutes(self._edit.text())
        self._edit.setText(_format_minutes_for_field(min(_MAX_DURATION_MIN, m + 60)))

    def line_edit(self) -> QLineEdit:
        return self._edit

    def total_minutes(self) -> int:
        return _parse_duration_minutes(self._edit.text())

    def reset(self) -> None:
        self._edit.clear()


def _fetch_timelog_state(user_id: int, target_date: date, prod_code: str) -> Dict[str, Any]:
    """ShotGrid reads for dialog (runs in worker thread)."""
    sg = get_default_sg()
    prod = find_project_by_code(sg, prod_code)
    prod_id: Optional[int] = None
    if prod and prod.get("id") is not None:
        try:
            prod_id = int(prod["id"])
        except (TypeError, ValueError):
            prod_id = None
    prod_tasks = list_tasks_for_project_assignee(sg, prod_id, user_id) if prod_id else []
    shots = list_shots_uploaded_by_user_on_date(sg, user_id=user_id, target_date=target_date)
    for s in shots:
        s["tasks"] = find_tasks_for_shot(sg, int(s["shot_id"]))
    total_all = sum_duration_minutes_for_user_date(
        sg, user_id=user_id, target_date=target_date, project_id=None
    )
    total_prod = (
        sum_duration_minutes_for_user_date(
            sg, user_id=user_id, target_date=target_date, project_id=prod_id
        )
        if prod_id
        else 0
    )
    return {
        "prod_id": prod_id,
        "prod_tasks": prod_tasks,
        "shots": shots,
        "total_all": total_all,
        "total_prod": total_prod,
        "prod_missing": prod is None,
    }


def _resolve_shot_task_label_and_id(
    srec: Dict[str, Any],
) -> tuple[str, Optional[int]]:
    tasks = srec.get("tasks") or []
    default_tid = int(srec.get("default_task_id") or 0)
    if not tasks:
        if default_tid > 0:
            return (f"Task #{default_tid}", default_tid)
        return ("(Task 없음)", None)
    for t in tasks:
        tid = t.get("id")
        try:
            tid_i = int(tid) if tid is not None else 0
        except (TypeError, ValueError):
            tid_i = 0
        if default_tid > 0 and tid_i == default_tid:
            content = (t.get("content") or "").strip() or f"Task #{tid_i}"
            return (content, tid_i)
    if default_tid > 0:
        return (f"Task #{default_tid}", default_tid)
    t0 = tasks[0]
    tid0 = t0.get("id")
    try:
        tid_i = int(tid0) if tid0 is not None else None
    except (TypeError, ValueError):
        tid_i = None
    content = (t0.get("content") or "").strip() or (f"Task #{tid_i}" if tid_i else "Task")
    return (content, tid_i)


class TimeLogDialog(QDialog):
    """Modal dialog for logging time to PROD tasks and shot tasks."""

    def __init__(
        self,
        parent: QWidget,
        user_id: int,
        append_worker: Callable[[ShotGridWorker], None],
        *,
        user_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TimeLogDialog")
        self.setWindowTitle("Time Log")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(1080, 900)
        self.resize(1120, 940)
        self.setStyleSheet(
            f"QDialog#TimeLogDialog {{ background-color: {theme.BG}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )
        self._user_id = int(user_id)
        self._user_display = (user_name or "").strip() or f"HumanUser #{self._user_id}"
        self._append_worker = append_worker
        self._req_seq = 0
        self._cached_total_all = 0
        self._cached_total_prod = 0
        self._prod_id: Optional[int] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        info_row = QHBoxLayout()
        self._user_hdr = QLabel(f"기록 대상: {self._user_display}")
        self._user_hdr.setStyleSheet(
            f"color: {theme.ACCENT}; font-weight: 600; background: transparent;"
        )
        info_row.addWidget(self._user_hdr)
        info_row.addStretch()
        self._total_lbl = QLabel("선택일 전체 기록: —")
        self._total_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: 700; font-size: 15px; background: transparent;"
        )
        info_row.addWidget(self._total_lbl)
        root.addLayout(info_row)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("날짜 선택"))
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.dateChanged.connect(self._on_date_changed)
        _apply_dark_date_edit(self._date_edit)
        date_row.addWidget(self._date_edit)
        date_row.addStretch()
        root.addLayout(date_row)

        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet(f"background-color: {theme.BORDER}; max-height: 1px;")
        root.addWidget(line1)

        self._fetch_err = QLabel("")
        self._fetch_err.setObjectName("status_msg")
        self._fetch_err.setStyleSheet(f"color: {theme.ERROR};")
        self._fetch_err.setVisible(False)
        self._fetch_err.setWordWrap(True)
        root.addWidget(self._fetch_err)

        shot_hdr = QHBoxLayout()
        st = QLabel("업로드 샷")
        st.setObjectName("log_title")
        shot_hdr.addWidget(st)
        shot_hdr.addStretch()
        root.addLayout(shot_hdr)

        self._shot_scroll = QScrollArea()
        self._shot_scroll.setWidgetResizable(True)
        self._shot_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._shot_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._shot_host = QWidget()
        self._shot_layout = QVBoxLayout(self._shot_host)
        self._shot_layout.setContentsMargins(0, 0, 0, 0)
        self._shot_layout.setSpacing(10)
        self._shot_scroll.setWidget(self._shot_host)
        self._shot_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._shot_scroll, 1)

        self._prod_toggle = QToolButton()
        self._prod_toggle.setCheckable(True)
        self._prod_toggle.setChecked(False)
        self._prod_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._prod_toggle.setAutoRaise(True)
        self._prod_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prod_toggle.toggled.connect(self._on_prod_panel_toggled)
        prod_toggle_row = QHBoxLayout()
        prod_toggle_row.addWidget(self._prod_toggle)
        prod_toggle_row.addStretch()
        root.addLayout(prod_toggle_row)

        self._prod_panel = QWidget()
        prod_lay = QVBoxLayout(self._prod_panel)
        prod_lay.setContentsMargins(0, 4, 0, 0)
        prod_lay.setSpacing(10)

        prod_hdr = QHBoxLayout()
        prod_title = QLabel("PROD")
        prod_title.setObjectName("log_title")
        prod_hdr.addWidget(prod_title)
        self._prod_sum_lbl = QLabel("합계: —")
        self._prod_sum_lbl.setObjectName("page_subtitle")
        prod_hdr.addWidget(self._prod_sum_lbl)
        prod_hdr.addStretch()
        prod_lay.addLayout(prod_hdr)

        self._prod_err = QLabel("")
        self._prod_err.setObjectName("status_msg")
        self._prod_err.setStyleSheet(f"color: {theme.ERROR};")
        self._prod_err.setVisible(False)
        self._prod_err.setWordWrap(True)
        prod_lay.addWidget(self._prod_err)

        self._prod_combo = QComboBox()
        self._prod_combo.setMinimumWidth(280)
        prod_task_row = QHBoxLayout()
        prod_task_row.addWidget(QLabel("Task"))
        prod_task_row.addWidget(self._prod_combo, 1)
        prod_lay.addLayout(prod_task_row)

        self._prod_desc = QLineEdit()
        self._prod_desc.setPlaceholderText("Description:")
        prod_lay.addLayout(self._form_row("Description:", self._prod_desc))

        self._prod_time = _DurationWidget(placeholder="Duration:")
        prod_lay.addWidget(self._prod_time)

        self._prod_log_btn = QPushButton("기록")
        self._prod_log_btn.setProperty("primary", True)
        self._prod_log_btn.clicked.connect(self._on_prod_log)
        self._prod_time.line_edit().textChanged.connect(self._sync_prod_log_enabled)
        self._prod_combo.currentIndexChanged.connect(self._sync_prod_log_enabled)
        prod_btn_row = QHBoxLayout()
        prod_btn_row.addStretch()
        prod_btn_row.addWidget(self._prod_log_btn)
        prod_lay.addLayout(prod_btn_row)

        self._prod_panel.setVisible(False)
        root.addWidget(self._prod_panel)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignBottom)
        bottom.addWidget(
            QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )
        root.addLayout(bottom)

        self._sync_prod_toggle_text()
        self._reload_data()
        self._sync_prod_log_enabled()

    def _on_prod_panel_toggled(self, expanded: bool) -> None:
        self._prod_panel.setVisible(expanded)
        self._sync_prod_toggle_text()

    def _sync_prod_toggle_text(self) -> None:
        expanded = self._prod_toggle.isChecked()
        arrow = "▼" if expanded else "▶"
        sum_txt = _format_duration_minutes(self._cached_total_prod)
        self._prod_toggle.setText(f"{arrow} PROD · 합계 {sum_txt}")

    def _form_row(self, label: str, w: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setObjectName("form_label")
        lbl.setFixedWidth(100)
        row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(w, 1)
        return row

    def _log_date(self) -> date:
        qd = self._date_edit.date()
        return date(qd.year(), qd.month(), qd.day())

    def _bump_seq(self) -> int:
        self._req_seq += 1
        return self._req_seq

    def _on_date_changed(self) -> None:
        self._reload_data()

    def _reload_data(self) -> None:
        seq = self._bump_seq()
        target = self._log_date()
        uid = self._user_id

        def _work() -> Dict[str, Any]:
            return _fetch_timelog_state(uid, target, PROD_PROJECT_CODE)

        w = ShotGridWorker(_work)
        w.finished.connect(lambda r, s=seq: self._on_load_done(r, s))
        w.error.connect(lambda e, s=seq: self._on_load_error(e, s))
        self._append_worker(w)
        w.start()

    def _on_load_error(self, err: str, seq: int) -> None:
        if seq != self._req_seq:
            return
        logger.warning("TimeLog load error: %s", err)
        self._fetch_err.setText(f"불러오기 실패: {err}")
        self._fetch_err.setVisible(True)
        self._clear_shot_rows()

    def _on_load_done(self, result: object, seq: int) -> None:
        if seq != self._req_seq:
            return
        self._fetch_err.setVisible(False)
        self._fetch_err.clear()
        self._prod_err.setVisible(False)
        if not isinstance(result, dict):
            return
        self._prod_id = result.get("prod_id")
        self._cached_total_all = int(result.get("total_all") or 0)
        self._cached_total_prod = int(result.get("total_prod") or 0)
        self._update_total_labels()

        if result.get("prod_missing"):
            self._prod_err.setText("ShotGrid에서 PROD 프로젝트를 찾을 수 없습니다.")
            self._prod_err.setVisible(True)
            self._prod_toggle.setChecked(True)
            self._prod_combo.clear()
            self._prod_combo.setEnabled(False)
            self._prod_log_btn.setEnabled(False)
        else:
            self._prod_err.setVisible(False)
            self._prod_combo.clear()
            tasks = result.get("prod_tasks") or []
            if not tasks:
                self._prod_combo.addItem("(배정된 Task 없음)", None)
                self._prod_combo.setEnabled(False)
                self._prod_log_btn.setEnabled(False)
            else:
                for t in tasks:
                    tid = t.get("id")
                    content = (t.get("content") or "").strip() or f"Task #{tid}"
                    self._prod_combo.addItem(content, int(tid) if tid is not None else None)
                self._prod_combo.setEnabled(True)
                self._sync_prod_log_enabled()

        self._clear_shot_rows()
        shots = result.get("shots") or []
        if not shots:
            empty = QLabel("이 날짜에 올린 샷이 없습니다.")
            empty.setObjectName("status_msg")
            self._shot_layout.addWidget(empty)
        else:
            for srec in shots:
                self._add_shot_row(srec)
        self._shot_layout.addStretch()

    def _clear_shot_rows(self) -> None:
        while self._shot_layout.count():
            item = self._shot_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_shot_row(self, srec: Dict[str, Any]) -> None:
        fr = QFrame()
        fr.setObjectName("card")
        v = QVBoxLayout(fr)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        top = QHBoxLayout()
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        thumb.setText("—")
        top.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        line1 = QHBoxLayout()
        code_lbl = QLabel((srec.get("shot_code") or "—").strip())
        code_lbl.setStyleSheet(f"font-weight: bold; color: {theme.ACCENT}; border: none;")
        line1.addWidget(code_lbl)
        proj_lbl = QLabel((srec.get("project_name") or "—").strip())
        proj_lbl.setObjectName("page_subtitle")
        line1.addWidget(proj_lbl)
        line1.addStretch()
        meta_col.addLayout(line1)

        ver_desc = (srec.get("version_description") or "").strip()
        if ver_desc:
            lines = ver_desc.splitlines()
            ver_display = "\n".join(
                normalize_path_str(line) if line.strip() else line for line in lines
            )
            desc_lbl = QLabel(ver_display)
            desc_lbl.setObjectName("status_msg")
            desc_lbl.setWordWrap(True)
            desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            meta_col.addWidget(desc_lbl)

        task_label_text, task_id = _resolve_shot_task_label_and_id(srec)
        task_row = QHBoxLayout()
        task_row.addWidget(QLabel("Task:"))
        task_val = QLabel(task_label_text)
        task_val.setWordWrap(True)
        task_val.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        task_row.addWidget(task_val, 1)
        meta_col.addLayout(task_row)

        desc = QLineEdit()
        desc.setPlaceholderText("Description:")
        meta_col.addLayout(self._form_row("Description:", desc))

        tw = _DurationWidget(placeholder="Duration:")
        meta_col.addWidget(tw)

        log_btn = QPushButton("기록")
        log_btn.setProperty("primary", True)
        row_btn = QHBoxLayout()
        row_btn.addStretch()
        row_btn.addWidget(log_btn)
        meta_col.addLayout(row_btn)

        top.addLayout(meta_col, 1)
        v.addLayout(top)

        self._shot_layout.addWidget(fr)

        pid = int(srec.get("project_id") or 0)
        url = (srec.get("thumb_url") or "").strip()
        if url:
            self._load_thumb(thumb, url)

        dur_edit = tw.line_edit()

        def _sync_shot_log() -> None:
            tid_ok = task_id is not None
            log_btn.setEnabled(tid_ok and tw.total_minutes() >= 1)

        dur_edit.textChanged.connect(_sync_shot_log)
        _sync_shot_log()

        def _do_log() -> None:
            self._submit_shot_log(
                project_id=pid,
                task_id=task_id,
                tw=tw,
                desc=desc,
                btn=log_btn,
                sync_shot_log=_sync_shot_log,
            )

        log_btn.clicked.connect(_do_log)

    def _load_thumb(self, label: QLabel, img_url: str) -> None:
        def _download() -> Optional[bytes]:
            try:
                with urllib.request.urlopen(img_url, timeout=12) as resp:
                    return resp.read()
            except Exception:
                return None

        w = ShotGridWorker(_download)
        w.finished.connect(lambda data, lbl=label: self._apply_thumb(lbl, data))
        self._append_worker(w)
        w.start()

    def _apply_thumb(self, label: QLabel, data: object) -> None:
        if not data or not isinstance(data, bytes):
            return
        pm = QPixmap()
        pm.loadFromData(data)
        if pm.isNull():
            return
        scaled = pm.scaled(
            _THUMB_W,
            _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - _THUMB_W) // 2)
        y = max(0, (scaled.height() - _THUMB_H) // 2)
        label.setPixmap(scaled.copy(x, y, _THUMB_W, _THUMB_H))
        label.setStyleSheet("border: none;")

    def _sync_prod_log_enabled(self) -> None:
        tid = self._prod_combo.currentData()
        ok_combo = tid is not None and self._prod_combo.isEnabled()
        self._prod_log_btn.setEnabled(ok_combo and self._prod_time.total_minutes() >= 1)

    def _update_total_labels(self) -> None:
        self._total_lbl.setText(
            f"선택일 전체 기록: {_format_duration_minutes(self._cached_total_all)}"
        )
        self._prod_sum_lbl.setText(f"합계: {_format_duration_minutes(self._cached_total_prod)}")
        self._sync_prod_toggle_text()

    def _on_prod_log(self) -> None:
        tid = self._prod_combo.currentData()
        if tid is None or self._prod_id is None:
            return
        mins = self._prod_time.total_minutes()
        if mins < 1:
            return
        desc = self._prod_desc.text().strip()
        self._prod_log_btn.setEnabled(False)

        def _create() -> Dict[str, Any]:
            sg = get_default_sg()
            return create_time_log(
                sg,
                project_id=int(self._prod_id),
                task_id=int(tid),
                user_id=self._user_id,
                duration_minutes=mins,
                description=desc,
                log_date=self._log_date(),
            )

        w = ShotGridWorker(_create)
        w.finished.connect(lambda _r: self._on_prod_log_done(mins))
        w.error.connect(lambda e: self._on_prod_log_fail(e))
        self._append_worker(w)
        w.start()

    def _on_prod_log_done(self, mins: int) -> None:
        self._cached_total_all += mins
        self._cached_total_prod += mins
        self._update_total_labels()
        self._flash_btn(self._prod_log_btn, ok=True)
        self._prod_time.reset()
        self._prod_desc.clear()
        self._sync_prod_log_enabled()

    def _on_prod_log_fail(self, err: str) -> None:
        logger.warning("PROD timelog failed: %s", err)
        self._flash_btn(self._prod_log_btn, ok=False)
        self._sync_prod_log_enabled()

    def _submit_shot_log(
        self,
        *,
        project_id: int,
        task_id: Optional[int],
        tw: _DurationWidget,
        desc: QLineEdit,
        btn: QPushButton,
        sync_shot_log: Callable[[], None],
    ) -> None:
        if task_id is None or project_id <= 0:
            return
        mins = tw.total_minutes()
        if mins < 1:
            return
        txt = desc.text().strip()
        btn.setEnabled(False)

        def _create() -> Dict[str, Any]:
            sg = get_default_sg()
            return create_time_log(
                sg,
                project_id=project_id,
                task_id=int(task_id),
                user_id=self._user_id,
                duration_minutes=mins,
                description=txt,
                log_date=self._log_date(),
            )

        w = ShotGridWorker(_create)
        w.finished.connect(
            lambda _r, m=mins, b=btn, t=tw, d=desc, s=sync_shot_log: self._on_shot_log_done(
                m, b, t, d, s
            )
        )
        w.error.connect(lambda e, b=btn, s=sync_shot_log: self._on_shot_log_fail(e, b, s))
        self._append_worker(w)
        w.start()

    def _on_shot_log_done(
        self,
        mins: int,
        btn: QPushButton,
        tw: _DurationWidget,
        desc: QLineEdit,
        sync_fn: Callable[[], None],
    ) -> None:
        self._cached_total_all += mins
        self._update_total_labels()
        self._flash_btn(btn, ok=True)
        tw.reset()
        desc.clear()
        sync_fn()
        btn.setEnabled(True)

    def _on_shot_log_fail(self, err: str, btn: QPushButton, sync_fn: Callable[[], None]) -> None:
        logger.warning("Shot timelog failed: %s", err)
        self._flash_btn(btn, ok=False)
        sync_fn()
        btn.setEnabled(True)

    def _flash_btn(self, btn: QPushButton, *, ok: bool) -> None:
        orig = btn.text()
        if ok:
            btn.setText("✓ 기록됨")
            btn.setStyleSheet(f"color: {theme.SUCCESS}; font-weight: bold;")
        else:
            btn.setText("✗ 실패")
            btn.setStyleSheet(f"color: {theme.ERROR}; font-weight: bold;")

        def _restore() -> None:
            btn.setText(orig)
            btn.setStyleSheet("")

        QTimer.singleShot(1500, _restore)
