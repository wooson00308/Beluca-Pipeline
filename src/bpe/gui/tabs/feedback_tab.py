"""Feedback / review tab — SV·TM queue, FFmpeg preview, annotations, ShotGrid Notes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.core.nk_finder import find_comp_render_video, find_server_root_auto
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui import theme
from bpe.gui.widgets.annotation_overlay import AnnotationTool
from bpe.gui.widgets.video_player_widget import VideoPlayerWidget
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.notes import create_note
from bpe.shotgrid.projects import list_active_projects
from bpe.shotgrid.tasks import (
    BELUCA_TASK_STATUS_PRESETS,
    list_review_tasks_for_project,
    update_task_status,
)

logger = get_logger("gui.tabs.feedback_tab")

_THUMB_W = 120
_THUMB_H = 82


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

        self._build_ui()
        self._load_projects()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("피드백")
        title.setObjectName("page_title")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # ── Left column ─────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("프로젝트"))
        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(220)
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)
        row1.addWidget(self._project_combo, 1)
        self._refresh_btn = QPushButton("조회")
        self._refresh_btn.clicked.connect(self._reload_tasks)
        row1.addWidget(self._refresh_btn)
        ll.addLayout(row1)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("상태 필터:"))
        self._btn_all = QPushButton("전체 (SV+TM)")
        self._btn_sv = QPushButton("SV만")
        self._btn_tm = QPushButton("TM만")
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
        ll.addLayout(filt)

        self._task_status_lbl = QLabel("")
        self._task_status_lbl.setObjectName("page_subtitle")
        ll.addWidget(self._task_status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 8, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_host)
        ll.addWidget(scroll, 1)

        split.addWidget(left)

        # ── Right column ────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        self._video = VideoPlayerWidget()
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl.addWidget(self._video, 1)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("도구:"))
        self._tool_none = QPushButton("끔")
        self._tool_pen = QPushButton("펜")
        self._tool_arrow = QPushButton("화살표")
        self._tool_rect = QPushButton("사각형")
        self._tool_ell = QPushButton("원")
        self._tool_txt = QPushButton("텍스트")
        self._tool_clear = QPushButton("지우기")
        for b in (
            self._tool_none,
            self._tool_pen,
            self._tool_arrow,
            self._tool_rect,
            self._tool_ell,
            self._tool_txt,
            self._tool_clear,
        ):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tools.addWidget(b)
        tools.addSpacing(16)
        tools.addWidget(QLabel("색:"))
        palette = [
            ("#ff0000", "빨강"),
            ("#ffff00", "노랑"),
            ("#ffffff", "흰색"),
            ("#3b82f6", "파랑"),
            ("#22c55e", "초록"),
        ]
        for hex_c, tip in palette:
            btn = QPushButton("●")
            btn.setToolTip(tip)
            btn.setStyleSheet(f"color: {hex_c}; font-size: 16px; border: none;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _=False, h=hex_c: self._video.annotation_overlay.set_color(QColor(h))
            )
            tools.addWidget(btn)
        tools.addStretch()
        rl.addLayout(tools)

        self._tool_none.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.NONE))
        self._tool_pen.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.PEN))
        self._tool_arrow.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.ARROW))
        self._tool_rect.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.RECT))
        self._tool_ell.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.ELLIPSE))
        self._tool_txt.clicked.connect(lambda: self._set_ann_tool(AnnotationTool.TEXT))
        self._tool_clear.clicked.connect(self._video.annotation_overlay.clear_all)

        rl.addWidget(QLabel("코멘트"))
        self._comment = QPlainTextEdit()
        self._comment.setPlaceholderText("작업자에게 전달할 피드백을 입력하세요.")
        self._comment.setMinimumHeight(180)
        self._comment.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        rl.addWidget(self._comment, 1)

        submit = QPushButton("ShotGrid에 노트 제출")
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.clicked.connect(self._submit_note)
        rl.addWidget(submit)

        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 6)
        root.addWidget(split, 1)

    def _set_ann_tool(self, tool: AnnotationTool) -> None:
        self._video.annotation_overlay.set_tool(tool)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._video.setFocus()

    def _on_filter_group_id(self, btn_id: int) -> None:
        if btn_id == 0:
            self._set_filter(["sv", "tm"])
        elif btn_id == 1:
            self._set_filter(["sv"])
        elif btn_id == 2:
            self._set_filter(["tm"])

    def _set_filter(self, statuses: List[str]) -> None:
        self._filter_statuses = [s.strip().lower() for s in statuses if s.strip()]
        self._reload_tasks()

    def _load_projects(self) -> None:
        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_active_projects(sg)

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_projects_loaded)
        w.error.connect(lambda e: self._task_status_lbl.setText(f"프로젝트 오류: {e}"))
        w.start()
        self._workers.append(w)

    def _on_projects_loaded(self, result: object) -> None:
        self._projects = result if isinstance(result, list) else []
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        for p in self._projects:
            name = (p.get("name") or p.get("code") or "").strip()
            self._project_combo.addItem(name, p.get("id"))
        self._project_combo.blockSignals(False)
        if self._project_combo.count():
            self._on_project_changed()

    def _on_project_changed(self, _idx: int = 0) -> None:
        self._reload_tasks()

    def _reload_tasks(self) -> None:
        pid = self._project_combo.currentData()
        if pid is None:
            self._task_status_lbl.setText("프로젝트를 선택하세요.")
            self._clear_cards()
            return
        self._task_status_lbl.setText("조회 중…")
        st = list(self._filter_statuses)

        def _fetch() -> List[Dict[str, Any]]:
            sg = get_default_sg()
            return list_review_tasks_for_project(sg, int(pid), statuses=st)

        w = ShotGridWorker(_fetch)
        w.finished.connect(self._on_tasks_loaded)
        w.error.connect(lambda e: self._task_status_lbl.setText(f"오류: {e}"))
        w.start()
        self._workers.append(w)

    def _on_tasks_loaded(self, result: object) -> None:
        tasks = result if isinstance(result, list) else []
        self._tasks = tasks
        self._task_status_lbl.setText(f"{len(tasks)}개 샷 (SV/TM 필터)")
        self._rebuild_cards()

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
        code = (task.get("shot_code") or "").strip() or "—"
        shot_lbl = QLabel(code)
        shot_lbl.setStyleSheet(f"font-weight: bold; color: {theme.ACCENT}; border: none;")
        shot_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        col.addWidget(shot_lbl)

        ver_line = (task.get("latest_version_code") or "").strip()
        ver_lbl = QLabel(ver_line if ver_line else "—")
        ver_lbl.setStyleSheet(
            f"color: {theme.ACCENT_TEXT}; font-size: 11px; font-weight: 500; border: none;"
        )
        ver_lbl.setWordWrap(True)
        ver_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        col.addWidget(ver_lbl)

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
        fr._task_data = task  # type: ignore[attr-defined]

        def _press(e: QMouseEvent) -> None:
            if e.button() == Qt.MouseButton.LeftButton:
                self._select_shot_card(fr)
            else:
                QFrame.mousePressEvent(fr, e)

        fr.mousePressEvent = _press  # type: ignore[method-assign]

        return fr

    def _on_task_status_combo(self, task: Dict[str, Any], combo: QComboBox) -> None:
        code = combo.currentData()
        if not code:
            return
        tid = task.get("task_id")
        if tid is None:
            return
        sfn = (task.get("status_field") or "sg_status_list").strip()

        def _do() -> str:
            sg = get_default_sg()
            update_task_status(sg, int(tid), str(code), field_name=sfn or None)
            return str(code).strip().lower()

        w = ShotGridWorker(_do)

        def _done(new_st: object) -> None:
            self._after_status_update(task, new_st)
            self._apply_combo_status_colors(combo, new_st)

        w.finished.connect(_done)
        w.error.connect(lambda e: QMessageBox.warning(self, "상태 변경", str(e)))
        w.start()
        self._workers.append(w)

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
        if not url or not isinstance(url, str) or lbl is None:
            return

        def _dl() -> Optional[bytes]:
            import urllib.request

            try:
                with urllib.request.urlopen(url, timeout=12) as resp:
                    return resp.read()
            except Exception:
                return None

        w = ShotGridWorker(_dl)
        w.finished.connect(lambda data, ref=lbl: self._apply_thumb(ref, data))
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

    def _select_shot_card(self, card: QFrame) -> None:
        task = getattr(card, "_task_data", None)
        if not isinstance(task, dict):
            return
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

        self._load_mov_for_selection()

    def _server_root_for_task(self, task: Dict[str, Any]) -> str:
        proj = (task.get("project_code") or "").strip()
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        return (find_server_root_auto(proj) or env_root).strip()

    def _load_mov_for_selection(self) -> None:
        task = self._selected_task
        if not task:
            self._video.clear()
            return
        shot = (task.get("shot_code") or "").strip()
        proj = (task.get("project_code") or "").strip()
        root = self._server_root_for_task(task)
        self._video.annotation_overlay.set_tool(AnnotationTool.NONE)

        if not shot or not proj:
            self._video.clear()
            return

        if not root:
            self._video.clear()
            QMessageBox.warning(
                self,
                "서버 루트 없음",
                "프로젝트 서버 경로를 찾지 못했습니다.\n"
                "• 환경 변수 BPE_SERVER_ROOT 를 설정하거나\n"
                "• 드라이브에 vfx/project_연도/<프로젝트코드> 구조가 있는지 확인하세요.",
            )
            return

        vc = (self._selected_version_code or "").strip() or None
        tried: List[str] = []
        mov: Optional[Path] = None

        sg_raw = (task.get("latest_version_sg_path") or "").strip()
        if sg_raw:
            norm_sg = normalize_path_str(sg_raw)
            tried.append(f"ShotGrid 경로: {norm_sg}")
            p_sg = Path(norm_sg)
            if p_sg.is_file():
                mov = p_sg
            else:
                logger.info("ShotGrid sg_path_to_movie 파일 없음 또는 접근 불가: %s", norm_sg)

        if mov is None:
            mov = find_comp_render_video(shot, proj, root, version_code=vc)
            if mov is not None:
                tried.append(f"샷 폴더 검색: {normalize_path_str(str(mov))}")
            else:
                tried.append(
                    f"로컬 검색 실패 — 샷={shot}, 버전={vc or '최신'}, "
                    f"루트={normalize_path_str(root)}"
                )

        if mov is None:
            self._video.clear()
            detail = "\n".join(tried) if tried else "(진단 정보 없음)"
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

        path = normalize_path_str(str(mov))
        ok = self._video.load_mov(path)
        if not ok:
            QMessageBox.warning(
                self,
                "재생 실패",
                f"ffmpeg·ffprobe가 PATH에 있어야 하고, 파일을 읽을 수 있어야 합니다.\n파일: {path}",
            )
        self._video.setFocus()

    def _submit_note(self) -> None:
        task = self._selected_task
        if not task:
            QMessageBox.warning(self, "제출", "샷을 먼저 선택하세요.")
            return
        text = self._comment.toPlainText().strip()
        if not text and not self._video.annotation_overlay.has_content():
            QMessageBox.warning(self, "제출", "코멘트 또는 그림 중 하나는 필요합니다.")
            return
        pid = task.get("project_id")
        sid = task.get("shot_id")
        if pid is None or sid is None:
            QMessageBox.warning(self, "제출", "프로젝트/샷 정보가 없습니다.")
            return

        shot_code = (task.get("shot_code") or "").strip()
        subject = f"BPE 피드백 — {shot_code}"
        vid = self._selected_version_id
        png_bytes: Optional[bytes] = None
        if self._video.annotation_overlay.has_content():
            png_bytes = self._video.capture_annotated_png_bytes()

        tmp_path: Optional[str] = None
        if png_bytes:
            fd, tmp_path = tempfile.mkstemp(prefix="bpe_note_", suffix=".png")
            os.close(fd)
            Path(tmp_path).write_bytes(png_bytes)

        att = tmp_path

        def _do() -> None:
            sg = get_default_sg()
            create_note(
                sg,
                project_id=int(pid),
                shot_id=int(sid),
                subject=subject,
                content=text or "(이미지 피드백)",
                version_id=vid,
                attachment_path=att,
            )

        w = ShotGridWorker(_do)
        w.finished.connect(lambda _r: self._on_note_submitted(tmp_path))
        w.error.connect(lambda e: self._on_note_failed(e, tmp_path))
        w.start()
        self._workers.append(w)

    def _on_note_submitted(self, tmp_path: Optional[str]) -> None:
        if tmp_path and Path(tmp_path).is_file():
            Path(tmp_path).unlink(missing_ok=True)
        self._comment.clear()
        self._video.annotation_overlay.clear_all()
        QMessageBox.information(self, "완료", "ShotGrid에 노트가 등록되었습니다.")

    def _on_note_failed(self, msg: str, tmp_path: Optional[str]) -> None:
        if tmp_path and Path(tmp_path).is_file():
            Path(tmp_path).unlink(missing_ok=True)
        QMessageBox.warning(self, "제출 실패", msg)
