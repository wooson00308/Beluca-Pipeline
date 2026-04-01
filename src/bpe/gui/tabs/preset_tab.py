"""Preset Manager tab — 4-zone layout: preset list, node tree, NK analysis, create."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nk_parser import (
    merge_nodetree_content,
    merge_parsed_into_preset,
    parse_nk_file,
)
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.presets import (
    delete_preset,
    get_preset_template_path,
    load_preset_template,
    load_presets,
    save_preset_template,
    upsert_preset,
)
from bpe.core.settings import get_presets_dir, set_presets_dir
from bpe.gui import theme
from bpe.gui.widgets.drop_zone import DropZone
from bpe.gui.widgets.preset_review_dialog import PresetDetailPanel


def _truncate_path(path: str, max_len: int = 48) -> str:
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1) :]


class PresetTab(QWidget):
    """Preset Manager — green: list, yellow: node tree, blue: detail, red: create."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._nk_last_dir: str = ""
        self._nk_merged: Optional[Dict[str, Any]] = None
        self._nk_parsed_raw: Optional[Dict[str, Any]] = None
        self._nk_node_stats: Optional[Dict[str, Any]] = None
        self._nk_raw_content: Optional[str] = None
        self._nk_source_path: str = ""
        self._preset_detail_panel: Optional[PresetDetailPanel] = None
        self._build_ui()
        self._refresh_preset_list()
        self._update_presets_dir_label()
        self._sync_selection_state()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(theme.CONTENT_MARGIN, 24, theme.CONTENT_MARGIN, 0)
        hdr.setSpacing(12)
        title = QLabel("Preset Manager")
        title.setObjectName("page_title")
        subtitle = QLabel("NK 드래그앤드롭으로 프리셋 생성 · 관리")
        subtitle.setObjectName("page_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignBottom)
        hdr.addWidget(title)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setContentsMargins(
            theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN, theme.CONTENT_MARGIN
        )
        main_split.addWidget(self._build_left_split())
        main_split.addWidget(self._build_right_column())
        main_split.setStretchFactor(0, 2)
        main_split.setStretchFactor(1, 3)

        root.addWidget(main_split, 1)

    def _build_left_split(self) -> QWidget:
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 12, 0)
        outer.setSpacing(0)

        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.addWidget(self._build_green_zone())
        v_split.addWidget(self._build_yellow_zone())
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 2)
        v_split.setSizes([220, 320])

        outer.addWidget(v_split, 1)
        return wrap

    def _build_green_zone(self) -> QWidget:
        col = QWidget()
        col.setMinimumHeight(160)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(8)

        lbl = QLabel("저장된 프리셋")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
        layout.addWidget(lbl)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self._presets_dir_lbl = QLabel("")
        self._presets_dir_lbl.setWordWrap(True)
        self._presets_dir_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        ch_dir_btn = QPushButton("변경")
        ch_dir_btn.setFixedWidth(72)
        ch_dir_btn.clicked.connect(self._browse_presets_dir)
        dir_row.addWidget(self._presets_dir_lbl, 1)
        dir_row.addWidget(ch_dir_btn)
        layout.addLayout(dir_row)

        self._preset_list = QListWidget()
        self._preset_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preset_list.setStyleSheet(
            f"QListWidget::item {{ min-height: 34px; padding: 6px 8px; "
            f"font-size: {theme.FONT_SIZE_SMALL + 1}px; }}"
        )
        self._preset_list.currentItemChanged.connect(self._on_preset_list_changed)
        layout.addWidget(self._preset_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._analyze_btn = QPushButton("세부 설정 보기")
        self._analyze_btn.setToolTip(
            "선택한 프리셋의 세부 세팅(FPS, OCIO, Write 등)을 오른쪽 패널에 표시합니다"
        )
        self._analyze_btn.clicked.connect(self._show_selected_preset_detail)
        self._delete_btn = QPushButton("삭제")
        self._delete_btn.clicked.connect(self._delete_selected)
        btn_row.addStretch()
        btn_row.addWidget(self._analyze_btn)
        btn_row.addWidget(self._delete_btn)
        layout.addLayout(btn_row)

        analyze_hint = QLabel("선택한 프리셋의 세부 세팅 내용을 확인하려면 위 버튼을 누르세요.")
        analyze_hint.setWordWrap(True)
        analyze_hint.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        layout.addWidget(analyze_hint)

        return col

    def _build_yellow_zone(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER};")
        lay.addWidget(sep)

        ttl = QLabel("노드트리 수정")
        ttl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
        lay.addWidget(ttl)

        hint = QLabel(".txt / .nk 파일을 드래그하거나, 아래 칸에 포커스 후 Ctrl+V로 붙여넣으세요.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        lay.addWidget(hint)

        self._nt_drop = DropZone(
            placeholder=".txt / .nk 파일을 여기에 드래그",
            allowed_extensions=[".txt", ".nk"],
        )
        self._nt_drop.file_dropped.connect(self._on_nt_file_dropped)
        self._nt_drop.paste_text.connect(self._on_nt_paste)
        lay.addWidget(self._nt_drop)

        self._nt_edit = QPlainTextEdit()
        self._nt_edit.setObjectName("log_area")
        self._nt_edit.setPlaceholderText("Nuke 노드 창에서 복사한 텍스트를 붙여넣으세요…")
        self._nt_edit.setMinimumHeight(120)
        lay.addWidget(self._nt_edit, 1)

        nt_row = QHBoxLayout()
        clear_btn = QPushButton("지우기")
        clear_btn.clicked.connect(self._nt_edit.clear)
        self._nt_apply_btn = QPushButton("노드트리 수정하기")
        self._nt_apply_btn.setProperty("primary", True)
        self._nt_apply_btn.clicked.connect(self._on_apply_nodetree)
        nt_row.addWidget(clear_btn)
        nt_row.addStretch()
        nt_row.addWidget(self._nt_apply_btn)
        lay.addLayout(nt_row)

        self._nt_status = QLabel("")
        self._nt_status.setWordWrap(True)
        self._nt_status.setObjectName("status_msg")
        self._nt_status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        lay.addWidget(self._nt_status)

        self._yellow_frame = box
        return box

    def _build_right_column(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(12, 0, 0, 8)
        layout.setSpacing(10)

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._build_nk_import_page())
        self._right_stack.addWidget(self._build_preset_view_page())
        layout.addWidget(self._right_stack, 1)

        red = QFrame()
        red.setProperty("class", "card")
        red_lay = QVBoxLayout(red)
        red_lay.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("프리셋 이름"))
        self._preset_name_edit = QLineEdit()
        self._preset_name_edit.setPlaceholderText("예) SBS_030")
        self._preset_name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self._preset_name_edit, 1)
        red_lay.addLayout(name_row)

        self._hint_lbl = QLabel("영문·숫자·_ 만 사용 (저장 시 대문자로 통일)")
        self._hint_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        red_lay.addWidget(self._hint_lbl)

        self._dup_lbl = QLabel("")
        self._dup_lbl.setWordWrap(True)
        self._dup_lbl.setVisible(False)
        self._dup_lbl.setStyleSheet(f"color: #ffb74d; font-size: {theme.FONT_SIZE_SMALL}px;")
        red_lay.addWidget(self._dup_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_create_btn = QPushButton("취소")
        self._cancel_create_btn.clicked.connect(self._on_cancel_create_flow)
        self._create_preset_btn = QPushButton("프리셋 생성")
        self._create_preset_btn.setProperty("primary", True)
        self._create_preset_btn.clicked.connect(self._on_create_preset)
        self._create_preset_btn.setEnabled(False)
        btn_row.addWidget(self._cancel_create_btn)
        btn_row.addWidget(self._create_preset_btn)
        red_lay.addLayout(btn_row)

        layout.addWidget(red)
        self._on_name_changed()
        return col

    def _build_nk_import_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)

        lbl = QLabel("NK 파일에서 가져오기")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
        lay.addWidget(lbl)

        self._nk_drop_zone = DropZone(
            placeholder=".nk 파일을 드래그하거나 아래에서 선택하세요",
            allowed_extensions=[".nk"],
        )
        self._nk_drop_zone.file_dropped.connect(self._on_nk_dropped)
        lay.addWidget(self._nk_drop_zone)

        nk_row = QHBoxLayout()
        nk_row.setSpacing(8)
        self._nk_path_edit = QLineEdit()
        self._nk_path_edit.setPlaceholderText("NK 파일 경로를 입력하거나 찾아보기...")
        nk_browse_btn = QPushButton("찾아보기")
        nk_browse_btn.setFixedWidth(100)
        nk_browse_btn.clicked.connect(self._browse_nk_import)
        nk_row.addWidget(self._nk_path_edit, 1)
        nk_row.addWidget(nk_browse_btn)
        lay.addLayout(nk_row)

        nk_analyze_btn = QPushButton("NK 분석하기")
        nk_analyze_btn.setProperty("primary", True)
        nk_analyze_btn.clicked.connect(self._analyze_nk)
        lay.addWidget(nk_analyze_btn)

        self._nk_feedback_lbl = QLabel("")
        self._nk_feedback_lbl.setWordWrap(True)
        self._nk_feedback_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        lay.addWidget(self._nk_feedback_lbl)

        self._nk_result_container = QWidget()
        self._nk_result_layout = QVBoxLayout(self._nk_result_container)
        self._nk_result_layout.setContentsMargins(0, 0, 0, 0)
        self._nk_placeholder_text = "NK 분석하기를 누르면 여기에 분석 결과가 표시됩니다."
        self._nk_placeholder = self._make_dim_placeholder(self._nk_placeholder_text)
        self._nk_result_layout.addWidget(self._nk_placeholder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._nk_result_container)
        lay.addWidget(scroll, 1)

        return page

    def _build_preset_view_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        top = QHBoxLayout()
        back_btn = QPushButton("← NK 임포트")
        back_btn.clicked.connect(self._go_nk_import_page)
        open_tpl_btn = QPushButton("템플릿 파일 열기")
        open_tpl_btn.clicked.connect(self._open_preset_template_file)
        top.addWidget(back_btn)
        top.addStretch()
        top.addWidget(open_tpl_btn)
        lay.addLayout(top)

        self._preset_view_host = QWidget()
        self._preset_view_layout = QVBoxLayout(self._preset_view_host)
        self._preset_view_layout.setContentsMargins(0, 0, 0, 0)
        ph = QLabel("저장된 프리셋을 선택한 뒤 왼쪽에서 분석하기를 누르세요.")
        ph.setWordWrap(True)
        ph.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        self._preset_view_layout.addWidget(ph)
        self._preset_view_placeholder = ph

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._preset_view_host)
        lay.addWidget(scroll, 1)

        return page

    def _go_nk_import_page(self) -> None:
        self._right_stack.setCurrentIndex(0)

    def _make_dim_placeholder(self, text: str) -> QLabel:
        ph = QLabel(text)
        ph.setWordWrap(True)
        ph.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        return ph

    def _set_nk_result_widget(self, widget: Optional[QWidget]) -> None:
        while self._nk_result_layout.count():
            item = self._nk_result_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if widget is None:
            self._nk_placeholder = self._make_dim_placeholder(self._nk_placeholder_text)
            self._nk_result_layout.addWidget(self._nk_placeholder)
        else:
            self._nk_result_layout.addWidget(widget, 1)

    def _update_presets_dir_label(self) -> None:
        p = normalize_path_str(get_presets_dir())
        self._presets_dir_lbl.setText(f"저장 위치: {_truncate_path(p, 52)}")
        self._presets_dir_lbl.setToolTip(p)

    def _browse_presets_dir(self) -> None:
        cur = str(get_presets_dir())
        path = QFileDialog.getExistingDirectory(self, "프리셋 저장 폴더 선택", cur)
        if path:
            set_presets_dir(path)
            self._update_presets_dir_label()
            self._refresh_preset_list()
            self._on_preset_list_changed()

    def _refresh_preset_list(self) -> None:
        self._preset_list.clear()
        presets = load_presets()
        for name in sorted(presets.keys()):
            self._preset_list.addItem(name)

    def _delete_selected(self) -> None:
        item = self._preset_list.currentItem()
        if item is None:
            return
        name = item.text()
        reply = QMessageBox.question(
            self,
            "프리셋 삭제",
            f"'{name}' 프리셋을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_preset(name)
            self._refresh_preset_list()
            self._clear_preset_view_page()

    def _on_preset_list_changed(self) -> None:
        self._sync_selection_state()

    def _sync_selection_state(self) -> None:
        item = self._preset_list.currentItem()
        has_sel = item is not None
        self._analyze_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._yellow_frame.setEnabled(has_sel)
        if not has_sel:
            self._nt_status.setText("")

    def _show_selected_preset_detail(self) -> None:
        item = self._preset_list.currentItem()
        if item is None:
            return
        name = item.text()
        presets = load_presets()
        data = presets.get(name)
        if not isinstance(data, dict):
            QMessageBox.warning(self, "오류", "프리셋 데이터를 읽을 수 없습니다.")
            return
        node_stats: Dict[str, Any] = {}
        tpl = get_preset_template_path(name)
        if tpl.exists():
            try:
                p = parse_nk_file(str(tpl))
                node_stats = p.pop("_node_stats", {})
            except ValueError:
                pass

        while self._preset_view_layout.count():
            it = self._preset_view_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

        panel = PresetDetailPanel(
            mode="preset_view",
            merged=data,
            parsed_raw=data,
            node_stats=node_stats,
            preset_name=name,
            parent=self._preset_view_host,
        )
        self._preset_view_layout.addWidget(panel, 1)
        self._preset_detail_panel = panel
        self._right_stack.setCurrentIndex(1)

    def _clear_preset_view_page(self) -> None:
        while self._preset_view_layout.count():
            it = self._preset_view_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        ph = QLabel("저장된 프리셋을 선택한 뒤 왼쪽에서 분석하기를 누르세요.")
        ph.setWordWrap(True)
        ph.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        self._preset_view_layout.addWidget(ph)
        self._preset_view_placeholder = ph
        self._preset_detail_panel = None

    def _open_preset_template_file(self) -> None:
        item = self._preset_list.currentItem()
        if item is None:
            return
        name = item.text()
        tpl_path = get_preset_template_path(name)
        if not tpl_path.exists():
            QMessageBox.warning(
                self,
                "템플릿 없음",
                f"'{name}' 프리셋에 저장된 NK 템플릿이 없습니다.\n"
                "NK 임포트로 프리셋을 만들면 템플릿이 생성됩니다.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(normalize_path_str(tpl_path.resolve())))

    def _on_nt_file_dropped(self, path: str) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self._nt_status.setText(f"읽기 실패: {e}")
            self._nt_status.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
            return
        self._nt_edit.setPlainText(text)
        self._nt_status.setText("파일 내용을 편집 영역에 불러왔습니다.")
        self._nt_status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )

    def _on_nt_paste(self, text: str) -> None:
        self._nt_edit.setPlainText(text)
        self._nt_status.setText("클립보드 내용을 붙여넣었습니다.")
        self._nt_status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )

    def _on_apply_nodetree(self) -> None:
        item = self._preset_list.currentItem()
        if item is None:
            return
        name = item.text()
        old = load_preset_template(name)
        if not old:
            self._nt_status.setText(
                "저장된 NK 템플릿이 없습니다. NK 임포트로 프리셋을 먼저 저장하세요."
            )
            self._nt_status.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
            return
        text = self._nt_edit.toPlainText().strip()
        if not text:
            self._nt_status.setText("노드 내용을 붙여넣거나 파일을 드롭하세요.")
            self._nt_status.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
            return
        try:
            merged = merge_nodetree_content(old, text)
        except ValueError as e:
            self._nt_status.setText(f"적용 실패: {e}")
            self._nt_status.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
            return
        save_preset_template(name, merged)
        self._nt_edit.clear()
        self._nt_status.setText(f"'{name}' 템플릿 노드트리가 갱신되었습니다.")
        self._nt_status.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )

    def _on_nk_dropped(self, path: str) -> None:
        norm = normalize_path_str(os.path.normpath(path))
        if not norm.lower().endswith(".nk"):
            self._nk_feedback("NK(.nk) 파일만 지원합니다.", theme.ERROR)
            return
        self._nk_path_edit.setText(norm)
        self._nk_last_dir = os.path.dirname(norm)

    def _browse_nk_import(self) -> None:
        init_dir = self._nk_last_dir
        cur = self._nk_path_edit.text().strip()
        if cur and os.path.isfile(cur):
            init_dir = os.path.dirname(cur)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "가져올 NK 파일 선택",
            init_dir,
            "Nuke Script (*.nk);;All Files (*)",
        )
        if path:
            norm = normalize_path_str(os.path.normpath(path))
            self._nk_path_edit.setText(norm)
            self._nk_drop_zone.setText(norm)
            self._nk_drop_zone.setProperty("has_file", True)
            self._nk_drop_zone.style().unpolish(self._nk_drop_zone)
            self._nk_drop_zone.style().polish(self._nk_drop_zone)
            self._nk_last_dir = os.path.dirname(norm)

    def _nk_feedback(self, text: str, color: str = "") -> None:
        c = color or theme.TEXT_DIM
        self._nk_feedback_lbl.setStyleSheet(f"color: {c}; font-size: {theme.FONT_SIZE_SMALL}px;")
        self._nk_feedback_lbl.setText(text)

    def _analyze_nk(self) -> None:
        nk_path = self._nk_path_edit.text().strip()
        if not nk_path:
            self._nk_feedback("NK 경로가 비어 있습니다.", theme.ERROR)
            self._nk_path_edit.setFocus()
            return
        nk_path = os.path.normpath(nk_path)
        if not nk_path.lower().endswith(".nk"):
            self._nk_feedback("NK(.nk) 파일만 지원합니다.", theme.ERROR)
            return
        if not os.path.isfile(nk_path):
            self._nk_feedback(f"파일을 찾을 수 없습니다: {nk_path}", theme.ERROR)
            return
        try:
            raw = parse_nk_file(nk_path)
            node_stats = raw.pop("_node_stats", {})
            parsed_flat = dict(raw)
            merged = merge_parsed_into_preset(dict(raw))
            try:
                nk_raw_content = Path(nk_path).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self._nk_feedback(f"NK 읽기 실패: {e}", theme.ERROR)
                return
        except ValueError as e:
            self._nk_feedback(f"NK 분석 실패: {e}", theme.ERROR)
            return

        self._nk_merged = merged
        self._nk_parsed_raw = parsed_flat
        self._nk_node_stats = node_stats
        self._nk_raw_content = nk_raw_content
        self._nk_source_path = nk_path

        panel = PresetDetailPanel(
            mode="nk_import",
            merged=merged,
            parsed_raw=parsed_flat,
            node_stats=node_stats,
            parent=self._nk_result_container,
        )
        self._set_nk_result_widget(panel)
        self._go_nk_import_page()
        self._nk_feedback("분석 완료 — 아래에 이름을 입력하고 프리셋을 저장하세요.", theme.SUCCESS)
        self._on_name_changed()

    def _on_name_changed(self) -> None:
        raw = self._preset_name_edit.text().strip()
        up = raw.upper()
        valid = bool(raw) and bool(re.fullmatch(r"[A-Za-z0-9_]+", raw))
        presets = load_presets()
        dup = valid and up in presets
        nk_ready = self._nk_merged is not None and self._nk_raw_content is not None
        self._create_preset_btn.setEnabled(valid and nk_ready)
        if dup:
            self._dup_lbl.setText(f"'{up}' 프리셋이 이미 있습니다. 덮어씁니다.")
            self._dup_lbl.setVisible(True)
            self._create_preset_btn.setText("기존 프리셋 덮어쓰기")
        else:
            self._dup_lbl.setVisible(False)
            self._create_preset_btn.setText("프리셋 생성")
        if valid:
            color = "#ffb74d" if dup else theme.SUCCESS
            self._hint_lbl.setText(f"'{up}' 로 저장됩니다")
            self._hint_lbl.setStyleSheet(f"color: {color}; font-size: {theme.FONT_SIZE_SMALL}px;")
        elif raw and not re.fullmatch(r"[A-Za-z0-9_]+", raw):
            self._hint_lbl.setText("영문/숫자/_ 만 사용 (저장 시 대문자로 통일)")
            self._hint_lbl.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
        else:
            self._hint_lbl.setText("프리셋 이름을 입력하세요 (영문/숫자/_)")
            self._hint_lbl.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )

    def _on_cancel_create_flow(self) -> None:
        self._preset_name_edit.clear()
        self._nk_merged = None
        self._nk_parsed_raw = None
        self._nk_node_stats = None
        self._nk_raw_content = None
        self._nk_source_path = ""
        self._nk_path_edit.clear()
        self._nk_drop_zone.setText(".nk 파일을 드래그하거나 아래에서 선택하세요")
        self._nk_drop_zone.setProperty("has_file", False)
        self._nk_drop_zone.style().unpolish(self._nk_drop_zone)
        self._nk_drop_zone.style().polish(self._nk_drop_zone)
        self._set_nk_result_widget(None)
        self._nk_feedback("", theme.TEXT_DIM)
        self._on_name_changed()

    def _on_create_preset(self) -> None:
        if not self._nk_raw_content or self._nk_merged is None:
            QMessageBox.warning(self, "오류", "NK를 먼저 분석하세요.")
            return
        name = self._preset_name_edit.text().strip().upper()
        if not name or not re.fullmatch(r"[A-Z0-9_]+", name):
            return
        cur = os.path.normpath(self._nk_source_path) if self._nk_source_path else ""
        if cur and not os.path.isfile(cur):
            QMessageBox.warning(self, "오류", "NK 파일을 찾을 수 없습니다.")
            return

        presets = load_presets()
        if name in presets:
            reply = QMessageBox.question(
                self,
                "프리셋 덮어쓰기",
                f"'{name}' 프리셋이 이미 있습니다.\n덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        data = dict(self._nk_merged)
        data["project_code"] = name
        upsert_preset(name, data)
        save_preset_template(name, self._nk_raw_content)
        self._refresh_preset_list()
        items = self._preset_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self._preset_list.setCurrentItem(items[0])
        self._nk_feedback(
            f"프리셋 '{name}' 저장됨 — 세팅 + 노드트리 템플릿({name}_template.nk)",
            theme.SUCCESS,
        )
        self._on_cancel_create_flow()
