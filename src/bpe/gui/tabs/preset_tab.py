"""Preset Manager tab — project settings form + preset list."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bpe.core.cache import load_colorspaces_cache, load_datatypes_cache, load_nuke_formats_cache
from bpe.core.nk_parser import parse_nk_for_preset
from bpe.core.presets import delete_preset, load_presets, upsert_preset
from bpe.gui import theme
from bpe.gui.widgets.search_combo import SearchComboBox


def _form_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setObjectName("form_label")
    lbl.setFixedWidth(theme.FORM_LABEL_WIDTH)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {theme.TEXT}; font-size: 14px; font-weight: 600; "
        f"padding-top: 8px; padding-bottom: 2px;"
    )
    return lbl


class PresetTab(QWidget):
    """Preset Manager — left form + right preset list."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._inputs: Dict[str, Any] = {}
        self._build_ui()
        self._refresh_preset_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(theme.CONTENT_MARGIN, 24, theme.CONTENT_MARGIN, 0)
        hdr.setSpacing(12)
        title = QLabel("Preset Manager")
        title.setObjectName("page_title")
        subtitle = QLabel("프리셋 저장 · 로드 · NK 설정 관리")
        subtitle.setObjectName("page_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignBottom)
        hdr.addWidget(title)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)

        # Splitter: form | preset list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(
            theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN, theme.CONTENT_MARGIN
        )

        splitter.addWidget(self._build_form_column())
        splitter.addWidget(self._build_list_column())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, 1)

    # --- left column: form ---

    def _build_form_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 12, 8)
        layout.setSpacing(theme.FORM_SPACING)

        # -- 프로젝트 정보 --
        layout.addWidget(_section_label("프로젝트 정보"))

        self._inputs["project_type"] = QComboBox()
        self._inputs["project_type"].addItems(["드라마(OTT)", "영화", "광고", "기타"])
        layout.addLayout(_form_row("프로젝트 타입", self._inputs["project_type"]))

        self._inputs["project_code"] = QLineEdit()
        self._inputs["project_code"].setPlaceholderText("예: BLC_2026")
        layout.addLayout(_form_row("프로젝트 코드", self._inputs["project_code"]))

        self._inputs["fps"] = QComboBox()
        self._inputs["fps"].addItems(["23.976", "24", "25", "29.97", "30"])
        layout.addLayout(_form_row("FPS", self._inputs["fps"]))

        self._inputs["plate_width"] = QLineEdit()
        self._inputs["plate_width"].setPlaceholderText("예: 4096")
        self._inputs["plate_height"] = QLineEdit()
        self._inputs["plate_height"].setPlaceholderText("예: 2160")
        res_row = QHBoxLayout()
        res_row.setSpacing(8)
        res_row.addWidget(self._inputs["plate_width"], 1)
        x_lbl = QLabel("x")
        x_lbl.setFixedWidth(12)
        x_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        res_row.addWidget(x_lbl)
        res_row.addWidget(self._inputs["plate_height"], 1)
        res_container = QWidget()
        res_container.setLayout(res_row)
        res_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addLayout(_form_row("플레이트 해상도", res_container))

        # -- OCIO --
        layout.addWidget(_section_label("OCIO"))

        ocio_row = QHBoxLayout()
        ocio_row.setSpacing(8)
        self._inputs["ocio_path"] = QLineEdit()
        self._inputs["ocio_path"].setPlaceholderText("OCIO config 경로")
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_ocio)
        ocio_row.addWidget(self._inputs["ocio_path"], 1)
        ocio_row.addWidget(browse_btn)
        ocio_container = QWidget()
        ocio_container.setLayout(ocio_row)
        ocio_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addLayout(_form_row("Config 경로", ocio_container))

        # -- Read --
        layout.addWidget(_section_label("Read"))

        self._inputs["read_input_transform"] = SearchComboBox()
        colorspaces = load_colorspaces_cache()
        if colorspaces:
            self._inputs["read_input_transform"].set_items(colorspaces)
        layout.addLayout(_form_row("Input Transform", self._inputs["read_input_transform"]))

        # -- Write --
        layout.addWidget(_section_label("Write"))

        formats = load_nuke_formats_cache()
        datatypes = load_datatypes_cache()

        self._inputs["delivery_format"] = QComboBox()
        if isinstance(formats, dict):
            self._inputs["delivery_format"].addItems(list(formats.keys()))
        layout.addLayout(_form_row("납품 포맷", self._inputs["delivery_format"]))

        self._inputs["write_channels"] = QComboBox()
        self._inputs["write_channels"].addItems(["rgb", "rgba", "all"])
        layout.addLayout(_form_row("Channels", self._inputs["write_channels"]))

        self._inputs["write_datatype"] = QComboBox()
        if datatypes:
            self._inputs["write_datatype"].addItems(datatypes)
        layout.addLayout(_form_row("Datatype", self._inputs["write_datatype"]))

        self._inputs["write_compression"] = QComboBox()
        self._inputs["write_compression"].addItems(
            ["none", "Zip (1 scanline)", "Zip (16 scanlines)", "PIZ", "DWAA", "DWAB"]
        )
        layout.addLayout(_form_row("Compression", self._inputs["write_compression"]))

        self._inputs["write_metadata"] = QComboBox()
        self._inputs["write_metadata"].addItems(["no metadata", "default metadata", "all metadata"])
        layout.addLayout(_form_row("Metadata", self._inputs["write_metadata"]))

        self._inputs["write_transform_type"] = QComboBox()
        self._inputs["write_transform_type"].addItems(["Colorspace", "Display/View"])
        layout.addLayout(_form_row("Transform Type", self._inputs["write_transform_type"]))

        colorspaces_w = load_colorspaces_cache()

        self._inputs["write_out_colorspace"] = SearchComboBox()
        if colorspaces_w:
            self._inputs["write_out_colorspace"].set_items(colorspaces_w)
        layout.addLayout(_form_row("Output Colorspace", self._inputs["write_out_colorspace"]))

        self._inputs["write_output_display"] = QComboBox()
        layout.addLayout(_form_row("Output Display", self._inputs["write_output_display"]))

        self._inputs["write_output_view"] = QComboBox()
        layout.addLayout(_form_row("Output View", self._inputs["write_output_view"]))

        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    # --- right column: preset list ---

    def _build_list_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(12, 0, 0, 8)
        layout.setSpacing(12)

        lbl = QLabel("저장된 프리셋")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
        layout.addWidget(lbl)

        self._preset_list = QListWidget()
        self._preset_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._preset_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        load_btn = QPushButton("불러오기")
        load_btn.clicked.connect(self._load_selected)
        del_btn = QPushButton("삭제")
        del_btn.clicked.connect(self._delete_selected)
        save_btn = QPushButton("저장")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save_preset)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        # NK Import section
        self._build_nk_import_section(layout)

        layout.addStretch()

        scroll.setWidget(col)
        return scroll

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_ocio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "OCIO Config 선택", "", "OCIO Config (*.ocio);;All Files (*)"
        )
        if path:
            self._inputs["ocio_path"].setText(path)

    def _refresh_preset_list(self) -> None:
        self._preset_list.clear()
        presets = load_presets()
        for name in sorted(presets.keys()):
            self._preset_list.addItem(name)

    def _collect_form(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for key, widget in self._inputs.items():
            if isinstance(widget, (QComboBox, SearchComboBox)):
                data[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text()
        return data

    def _apply_form(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            widget = self._inputs.get(key)
            if widget is None:
                continue
            if isinstance(widget, SearchComboBox):
                widget.set_current(str(value))
            elif isinstance(widget, QComboBox):
                idx = widget.findText(str(value))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))

    def _save_preset(self) -> None:
        code = self._inputs["project_code"].text().strip()
        if not code:
            QMessageBox.warning(self, "저장 실패", "프로젝트 코드를 입력하세요.")
            return
        upsert_preset(code, self._collect_form())
        self._refresh_preset_list()

    def _load_selected(self) -> None:
        item = self._preset_list.currentItem()
        if item is None:
            return
        presets = load_presets()
        data = presets.get(item.text())
        if isinstance(data, dict):
            self._apply_form(data)

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

    # ------------------------------------------------------------------
    # NK Import
    # ------------------------------------------------------------------

    def _build_nk_import_section(self, parent_layout: QVBoxLayout) -> None:
        """Build the NK Import UI block inside the right column."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER};")
        parent_layout.addWidget(sep)

        lbl = QLabel("NK 파일에서 가져오기")
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
        parent_layout.addWidget(lbl)

        # File path row
        nk_row = QHBoxLayout()
        nk_row.setSpacing(8)
        self._nk_path_edit = QLineEdit()
        self._nk_path_edit.setPlaceholderText("NK 파일 경로를 입력하거나 찾아보기...")
        nk_browse_btn = QPushButton("찾아보기")
        nk_browse_btn.setFixedWidth(100)
        nk_browse_btn.clicked.connect(self._browse_nk_import)
        nk_row.addWidget(self._nk_path_edit, 1)
        nk_row.addWidget(nk_browse_btn)
        parent_layout.addLayout(nk_row)

        nk_analyze_btn = QPushButton("NK 분석하기")
        nk_analyze_btn.setProperty("primary", True)
        nk_analyze_btn.clicked.connect(self._analyze_nk)
        parent_layout.addWidget(nk_analyze_btn)

        # Feedback label
        self._nk_feedback_lbl = QLabel("")
        self._nk_feedback_lbl.setWordWrap(True)
        self._nk_feedback_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        parent_layout.addWidget(self._nk_feedback_lbl)

        # Review panel (hidden initially)
        self._nk_review_widget = QWidget()
        self._nk_review_widget.setVisible(False)
        review_layout = QVBoxLayout(self._nk_review_widget)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(8)

        review_title = QLabel("NK 분석 결과")
        review_title.setStyleSheet(f"color: {theme.ACCENT}; font-size: 14px; font-weight: 600;")
        review_layout.addWidget(review_title)

        self._nk_review_file_lbl = QLabel("")
        self._nk_review_file_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        review_layout.addWidget(self._nk_review_file_lbl)

        # Review rows container
        self._nk_review_rows_widget = QWidget()
        self._nk_review_rows_layout = QVBoxLayout(self._nk_review_rows_widget)
        self._nk_review_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._nk_review_rows_layout.setSpacing(2)
        review_layout.addWidget(self._nk_review_rows_widget)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {theme.BORDER};")
        review_layout.addWidget(sep2)

        # Preset name input
        name_lbl = QLabel("프리셋 이름")
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE}px; font-weight: 600;"
        )
        review_layout.addWidget(name_lbl)

        self._nk_name_edit = QLineEdit()
        self._nk_name_edit.setPlaceholderText("예) SBS_030")
        self._nk_name_edit.textChanged.connect(self._on_nk_name_changed)
        self._nk_name_edit.returnPressed.connect(self._on_nk_name_return)
        review_layout.addWidget(self._nk_name_edit)

        self._nk_name_hint_lbl = QLabel("프리셋 코드를 입력하세요 (예: SBS_030)")
        self._nk_name_hint_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        review_layout.addWidget(self._nk_name_hint_lbl)

        self._nk_duplicate_lbl = QLabel("")
        self._nk_duplicate_lbl.setWordWrap(True)
        self._nk_duplicate_lbl.setStyleSheet(
            f"color: #ffb74d; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        self._nk_duplicate_lbl.setVisible(False)
        review_layout.addWidget(self._nk_duplicate_lbl)

        note_lbl = QLabel(
            "미감지 항목은 기본값으로 채워집니다. "
            "왼쪽 폼에서 확인/수정 후 필요 시 저장으로 다시 기록하세요."
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
        review_layout.addWidget(note_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        hide_btn = QPushButton("분석 숨기기")
        hide_btn.setFixedWidth(100)
        hide_btn.clicked.connect(self._hide_nk_review)
        btn_row.addWidget(hide_btn)
        btn_row.addStretch()
        self._nk_create_btn = QPushButton("프리셋 생성")
        self._nk_create_btn.setProperty("primary", True)
        self._nk_create_btn.setEnabled(False)
        self._nk_create_btn.clicked.connect(self._confirm_nk_import)
        btn_row.addWidget(self._nk_create_btn)
        review_layout.addLayout(btn_row)

        parent_layout.addWidget(self._nk_review_widget)

        # Internal state
        self._nk_pending_parsed: Optional[Dict[str, Any]] = None
        self._nk_last_dir = ""

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
            norm = os.path.normpath(path)
            self._nk_path_edit.setText(norm)
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
        if not os.path.isfile(nk_path):
            self._nk_feedback(f"파일을 찾을 수 없습니다: {nk_path}", theme.ERROR)
            return
        try:
            data = parse_nk_for_preset(nk_path)
        except ValueError as e:
            self._nk_feedback(f"NK 분석 실패: {e}", theme.ERROR)
            return
        self._show_nk_review(nk_path, data)

    def _show_nk_review(self, nk_path: str, parsed: Dict[str, Any]) -> None:
        self._nk_pending_parsed = parsed
        self._nk_review_file_lbl.setText(f"파일: {Path(nk_path).name}")
        self._populate_nk_review_rows(parsed)
        self._nk_name_edit.clear()
        self._nk_review_widget.setVisible(True)
        self._nk_feedback("분석 완료 — 이름 입력 후 프리셋 생성", theme.ACCENT)
        self._nk_name_edit.setFocus()
        self._update_nk_create_btn_state()

    def _hide_nk_review(self) -> None:
        self._nk_review_widget.setVisible(False)
        self._nk_pending_parsed = None
        self._nk_name_edit.clear()
        self._nk_feedback("")

    def _populate_nk_review_rows(self, d: Dict[str, Any]) -> None:
        # Clear existing rows
        while self._nk_review_rows_layout.count():
            item = self._nk_review_rows_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

        rows: List[Tuple[str, str]] = [
            ("FPS", d.get("fps") or "미감지"),
            (
                "해상도",
                f"{d.get('plate_width', '?')} x {d.get('plate_height', '?')}"
                if d.get("plate_width") and d.get("plate_height")
                else "미감지",
            ),
            ("OCIO Config", Path(d["ocio_path"]).name if d.get("ocio_path") else "미감지"),
            ("Read Input Transform", d.get("read_input_transform") or "미감지"),
            ("납품 포맷", d.get("delivery_format") or "미감지"),
            ("Channels", d.get("write_channels") or "미감지"),
            ("Datatype", d.get("write_datatype") or "미감지"),
            ("Compression", d.get("write_compression") or "미감지"),
            ("Metadata", d.get("write_metadata") or "미감지"),
            ("Transform Type", d.get("write_transform_type") or "미감지"),
            ("Output Transform", d.get("write_out_colorspace") or "미감지"),
            ("Display", d.get("write_output_display") or "미감지"),
            ("View", d.get("write_output_view") or "미감지"),
        ]
        for label, value in rows:
            detected = value != "미감지"
            row = QHBoxLayout()
            row.setSpacing(8)
            key_lbl = QLabel(label)
            key_lbl.setFixedWidth(140)
            key_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
            val_color = theme.ACCENT if detected else theme.TEXT_DIM
            val_lbl = QLabel(str(value))
            val_lbl.setStyleSheet(f"color: {val_color}; font-size: {theme.FONT_SIZE_SMALL}px;")
            row.addWidget(key_lbl)
            row.addWidget(val_lbl, 1)
            container = QWidget()
            container.setLayout(row)
            self._nk_review_rows_layout.addWidget(container)

    def _on_nk_name_changed(self) -> None:
        self._update_nk_create_btn_state()

    def _update_nk_create_btn_state(self) -> None:
        raw = self._nk_name_edit.text().strip()
        up = raw.upper()
        valid = bool(raw) and bool(re.fullmatch(r"[A-Za-z0-9_]+", raw))
        presets = load_presets()
        dup = valid and up in presets

        self._nk_create_btn.setEnabled(valid)
        if dup:
            self._nk_duplicate_lbl.setText(
                f"'{up}' 프리셋이 이미 있습니다. 생성 시 기존 데이터가 교체됩니다."
            )
            self._nk_duplicate_lbl.setVisible(True)
            self._nk_create_btn.setText("기존 프리셋 덮어쓰기")
        else:
            self._nk_duplicate_lbl.setVisible(False)
            self._nk_create_btn.setText("프리셋 생성")

        if valid:
            hint = f"'{up}' 로 저장됩니다"
            if dup:
                hint += " — 기존 프리셋을 덮어씁니다"
            color = "#ffb74d" if dup else theme.SUCCESS
            self._nk_name_hint_lbl.setText(hint)
            self._nk_name_hint_lbl.setStyleSheet(
                f"color: {color}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
        elif raw and not re.fullmatch(r"[A-Za-z0-9_]+", raw):
            self._nk_name_hint_lbl.setText(
                "영문/숫자/_ 만 사용 (대소문자 무관, 저장 시 대문자로 통일)"
            )
            self._nk_name_hint_lbl.setStyleSheet(
                f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
        else:
            self._nk_name_hint_lbl.setText("프리셋 코드를 입력하세요 (예: SBS_030)")
            self._nk_name_hint_lbl.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
            )

    def _on_nk_name_return(self) -> None:
        if self._nk_create_btn.isEnabled():
            self._confirm_nk_import()

    def _confirm_nk_import(self) -> None:
        if not self._nk_pending_parsed:
            return
        name = self._nk_name_edit.text().strip().upper()
        if not name or not re.fullmatch(r"[A-Z0-9_]+", name):
            return

        presets = load_presets()
        if name in presets:
            reply = QMessageBox.question(
                self,
                "프리셋 덮어쓰기",
                f"'{name}' 프리셋이 이미 있습니다.\n"
                "기존 설정이 NK 기준으로 덮어써집니다. 진행하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        data = dict(self._nk_pending_parsed)
        data["project_code"] = name
        upsert_preset(name, data)
        self._refresh_preset_list()
        self._apply_form(data)
        self._hide_nk_review()
        self._nk_feedback(
            f"프리셋 '{name}' 저장됨 — 왼쪽 폼에서 값을 확인/수정할 수 있습니다.",
            theme.SUCCESS,
        )
