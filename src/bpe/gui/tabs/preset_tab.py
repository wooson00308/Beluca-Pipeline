"""Preset Manager tab — project settings form + preset list."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bpe.core.presets import delete_preset, load_presets, upsert_preset
from bpe.core.cache import load_colorspaces_cache, load_datatypes_cache, load_nuke_formats_cache
from bpe.gui.widgets.search_combo import SearchComboBox


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

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(28, 24, 28, 0)
        title = QLabel("Preset Manager")
        title.setProperty("class", "title")
        subtitle = QLabel("프로젝트별 Nuke 세팅을 저장하고 팀과 공유하세요")
        subtitle.setProperty("dim", True)
        hdr.addWidget(title)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)

        # Splitter: form | preset list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(20, 12, 20, 16)

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
        layout.setContentsMargins(8, 0, 8, 8)

        layout.addWidget(self._build_project_group())
        layout.addWidget(self._build_ocio_group())
        layout.addWidget(self._build_read_group())
        layout.addWidget(self._build_write_group())
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_project_group(self) -> QGroupBox:
        grp = QGroupBox("프로젝트 정보")
        form = QFormLayout(grp)

        self._inputs["project_type"] = QComboBox()
        self._inputs["project_type"].addItems(["드라마(OTT)", "영화", "광고", "기타"])
        form.addRow("프로젝트 타입", self._inputs["project_type"])

        self._inputs["project_code"] = QLineEdit()
        self._inputs["project_code"].setPlaceholderText("예: BLC_2026")
        form.addRow("프로젝트 코드", self._inputs["project_code"])

        self._inputs["fps"] = QComboBox()
        self._inputs["fps"].addItems(["23.976", "24", "25", "29.97", "30"])
        form.addRow("FPS", self._inputs["fps"])

        self._inputs["plate_width"] = QLineEdit()
        self._inputs["plate_width"].setPlaceholderText("예: 4096")
        self._inputs["plate_height"] = QLineEdit()
        self._inputs["plate_height"].setPlaceholderText("예: 2160")
        res_row = QHBoxLayout()
        res_row.addWidget(self._inputs["plate_width"])
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._inputs["plate_height"])
        form.addRow("플레이트 해상도", res_row)

        return grp

    def _build_ocio_group(self) -> QGroupBox:
        grp = QGroupBox("OCIO")
        form = QFormLayout(grp)

        row = QHBoxLayout()
        self._inputs["ocio_path"] = QLineEdit()
        self._inputs["ocio_path"].setPlaceholderText("OCIO config 경로")
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._browse_ocio)
        row.addWidget(self._inputs["ocio_path"], 1)
        row.addWidget(browse_btn)
        form.addRow("Config 경로", row)
        return grp

    def _build_read_group(self) -> QGroupBox:
        grp = QGroupBox("Read")
        form = QFormLayout(grp)

        self._inputs["read_input_transform"] = SearchComboBox()
        colorspaces = load_colorspaces_cache()
        if colorspaces:
            self._inputs["read_input_transform"].set_items(colorspaces)
        form.addRow("Input Transform", self._inputs["read_input_transform"])
        return grp

    def _build_write_group(self) -> QGroupBox:
        grp = QGroupBox("Write")
        form = QFormLayout(grp)

        formats = load_nuke_formats_cache()
        datatypes = load_datatypes_cache()

        self._inputs["delivery_format"] = QComboBox()
        if isinstance(formats, dict):
            self._inputs["delivery_format"].addItems(list(formats.keys()))
        form.addRow("납품 포맷", self._inputs["delivery_format"])

        self._inputs["write_channels"] = QComboBox()
        self._inputs["write_channels"].addItems(["rgb", "rgba", "all"])
        form.addRow("Channels", self._inputs["write_channels"])

        self._inputs["write_datatype"] = QComboBox()
        if datatypes:
            self._inputs["write_datatype"].addItems(datatypes)
        form.addRow("Datatype", self._inputs["write_datatype"])

        self._inputs["write_compression"] = QComboBox()
        self._inputs["write_compression"].addItems(
            ["none", "Zip (1 scanline)", "Zip (16 scanlines)", "PIZ", "DWAA", "DWAB"]
        )
        form.addRow("Compression", self._inputs["write_compression"])

        self._inputs["write_metadata"] = QComboBox()
        self._inputs["write_metadata"].addItems(
            ["no metadata", "default metadata", "all metadata"]
        )
        form.addRow("Metadata", self._inputs["write_metadata"])

        self._inputs["write_transform_type"] = QComboBox()
        self._inputs["write_transform_type"].addItems(
            ["Colorspace", "Display/View"]
        )
        form.addRow("Transform Type", self._inputs["write_transform_type"])

        colorspaces = load_colorspaces_cache()

        self._inputs["write_out_colorspace"] = SearchComboBox()
        if colorspaces:
            self._inputs["write_out_colorspace"].set_items(colorspaces)
        form.addRow("Output Colorspace", self._inputs["write_out_colorspace"])

        self._inputs["write_output_display"] = QComboBox()
        form.addRow("Output Display", self._inputs["write_output_display"])

        self._inputs["write_output_view"] = QComboBox()
        form.addRow("Output View", self._inputs["write_output_view"])

        return grp

    # --- right column: preset list ---

    def _build_list_column(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(8, 0, 8, 8)

        lbl = QLabel("저장된 프리셋")
        lbl.setProperty("class", "title")
        layout.addWidget(lbl)

        self._preset_list = QListWidget()
        layout.addWidget(self._preset_list, 1)

        btn_row = QHBoxLayout()
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

        return col

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
