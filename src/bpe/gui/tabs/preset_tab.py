"""Preset Manager tab — project settings form + preset list."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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

from bpe.core.presets import delete_preset, load_presets, upsert_preset
from bpe.core.cache import load_colorspaces_cache, load_datatypes_cache, load_nuke_formats_cache
from bpe.gui.widgets.search_combo import SearchComboBox
from bpe.gui import theme


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
        splitter.setContentsMargins(theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN, theme.CONTENT_MARGIN)

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
        browse_btn.setFixedWidth(80)
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
        self._inputs["write_metadata"].addItems(
            ["no metadata", "default metadata", "all metadata"]
        )
        layout.addLayout(_form_row("Metadata", self._inputs["write_metadata"]))

        self._inputs["write_transform_type"] = QComboBox()
        self._inputs["write_transform_type"].addItems(
            ["Colorspace", "Display/View"]
        )
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
        lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;"
        )
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
