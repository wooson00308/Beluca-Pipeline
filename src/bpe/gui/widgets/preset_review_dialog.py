"""Preset detail panel — NK analysis or saved preset (single scroll page)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from bpe.core.nk_parser import parse_nk_file
from bpe.core.presets import get_preset_template_path
from bpe.gui import theme

_IMPORTANT_KEYS = frozenset(
    {
        "fps",
        "plate_width",
        "ocio_path",
        "write_datatype",
        "write_compression",
        "read_input_transform",
    }
)


def _badge_nk_import(
    key: str,
    merged: Dict[str, Any],
    parsed_raw: Dict[str, Any],
    important: set,
) -> Tuple[str, str]:
    if key in parsed_raw and parsed_raw.get(key) not in (None, ""):
        return "✓ 감지", theme.SUCCESS
    if key in important:
        val = merged.get(key) or ""
        if not val:
            return "⚠ 미감지", theme.ERROR
    return "– 기본값", theme.TEXT_DIM


def _badge_preset_view(key: str, merged: Dict[str, Any]) -> Tuple[str, str]:
    val = merged.get(key)
    if val not in (None, ""):
        return "✓ 저장됨", theme.SUCCESS
    return "– 없음", theme.TEXT_DIM


def _row_widget(label: str, value: str, badge: str, badge_color: str) -> QWidget:
    row = QHBoxLayout()
    row.setSpacing(8)
    key_lbl = QLabel(label)
    key_lbl.setFixedWidth(160)
    key_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
    val_lbl = QLabel(value)
    val_lbl.setWordWrap(True)
    val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    val_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE_SMALL}px;")
    bd = QLabel(badge)
    bd.setFixedWidth(72)
    bd.setStyleSheet(f"color: {badge_color}; font-size: {theme.FONT_SIZE_SMALL}px;")
    row.addWidget(key_lbl)
    row.addWidget(val_lbl, 1)
    row.addWidget(bd)
    w = QWidget()
    w.setLayout(row)
    return w


def _section_header(text: str) -> QLabel:
    h = QLabel(text)
    h.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px; font-weight: 600; padding-top: 8px;")
    return h


class PresetDetailPanel(QWidget):
    """NK import review or saved preset detail — one scrollable page."""

    def __init__(
        self,
        mode: str,
        merged: Dict[str, Any],
        parsed_raw: Dict[str, Any],
        node_stats: Dict[str, Any],
        preset_name: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._merged = dict(merged)
        self._parsed_raw = dict(parsed_raw)
        self._node_stats = dict(node_stats)
        self._preset_name = preset_name

        if mode == "preset_view" and preset_name and not self._node_stats.get("total"):
            tpl = get_preset_template_path(preset_name)
            if tpl.exists():
                try:
                    p = parse_nk_file(str(tpl))
                    self._node_stats = p.pop("_node_stats", {})
                except ValueError:
                    pass

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(4)
        self._populate_single_page(lay)
        lay.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    def _has_mov(self) -> bool:
        ms = self._node_stats
        m = self._merged
        return bool(
            (
                ms.get("write_names")
                and any(
                    m.get(k)
                    for k in (
                        "mov_codec",
                        "mov_profile",
                        "mov_colorspace",
                        "mov_fps",
                        "mov_channels",
                    )
                )
            )
            or m.get("mov_codec")
            or m.get("mov_profile")
            or m.get("mov_fps")
            or m.get("mov_channels")
        )

    def _populate_single_page(self, lay: QVBoxLayout) -> None:
        self._populate_summary(lay)
        self._populate_project_ocio(lay)
        lay.addWidget(_section_header("EXR Output"))
        self._populate_exr(lay)
        lay.addWidget(_section_header("MOV Output"))
        if self._has_mov():
            self._populate_mov(lay)
        else:
            mov_lbl = QLabel("MOV Write 노드가 감지되지 않았습니다.")
            mov_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;")
            lay.addWidget(mov_lbl)
        lay.addWidget(_section_header("Plate·노드트리"))
        self._populate_plate_nodes(lay)

    def _populate_summary(self, lay: QVBoxLayout) -> None:
        lay.addWidget(_section_header("요약"))

        important = set(_IMPORTANT_KEYS)
        missing: List[str] = []
        if self._mode == "nk_import":
            for k in sorted(important):
                if k not in self._parsed_raw or not self._parsed_raw.get(k):
                    missing.append(k)
            if missing:
                warn = QLabel(f"⚠ 미감지 {len(missing)}항목 — " + ", ".join(missing))
                warn.setWordWrap(True)
                warn.setStyleSheet(f"color: {theme.ERROR}; font-size: {theme.FONT_SIZE_SMALL}px;")
                lay.addWidget(warn)
        else:
            for k in sorted(important):
                v = self._merged.get(k)
                if v in (None, ""):
                    missing.append(k)
            if missing:
                warn = QLabel(f"⚠ 값 없음 {len(missing)}항목 — " + ", ".join(missing))
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px;"
                )
                lay.addWidget(warn)

        m = self._merged
        pr = self._parsed_raw

        def add_row(key: str, label: str, disp: Optional[str] = None) -> None:
            val = disp if disp is not None else (m.get(key) or "")
            if self._mode == "nk_import":
                b, c = _badge_nk_import(key, m, pr, important if key in important else set())
            else:
                b, c = _badge_preset_view(key, m)
            lay.addWidget(_row_widget(label, str(val) if val else "—", b, c))

        add_row("fps", "FPS")
        wv, hv = m.get("plate_width", ""), m.get("plate_height", "")
        res = f"{wv} × {hv}" if wv and hv else "—"
        if self._mode == "nk_import":
            if "plate_width" in pr and "plate_height" in pr:
                rb, rc = "✓ 감지", theme.SUCCESS
            elif not wv or not hv:
                rb, rc = "⚠ 미감지", theme.ERROR
            else:
                rb, rc = "– 기본값", theme.TEXT_DIM
        else:
            rb, rc = _badge_preset_view("plate_width", m)
        lay.addWidget(_row_widget("해상도", res, rb, rc))

        pfn = m.get("plate_format_name") or ""
        if self._mode == "nk_import":
            pb, pc = _badge_nk_import("plate_format_name", m, pr, set())
        else:
            pb, pc = _badge_preset_view("plate_format_name", m)
        lay.addWidget(_row_widget("포맷 이름", pfn or "—", pb, pc))

        ocio = m.get("ocio_path") or ""
        ocio_disp = str(Path(ocio).name) if ocio else "—"
        if self._mode == "nk_import":
            ob, oc = _badge_nk_import("ocio_path", m, pr, {"ocio_path"})
        else:
            ob, oc = _badge_preset_view("ocio_path", m)
        lay.addWidget(_row_widget("Config 경로", ocio_disp, ob, oc))

        add_row("write_datatype", "EXR Datatype")
        add_row("write_compression", "Compression")
        add_row("read_input_transform", "Read Transform")

    def _populate_project_ocio(self, lay: QVBoxLayout) -> None:
        lay.addWidget(_section_header("프로젝트 기본"))
        m = self._merged
        pr = self._parsed_raw
        important = set(_IMPORTANT_KEYS)

        for key, label in [
            ("fps", "FPS"),
        ]:
            if self._mode == "nk_import":
                b, c = _badge_nk_import(key, m, pr, important)
            else:
                b, c = _badge_preset_view(key, m)
            lay.addWidget(_row_widget(label, str(m.get(key, "") or "—"), b, c))

        wv, hv = m.get("plate_width", ""), m.get("plate_height", "")
        res = f"{wv} × {hv}" if wv and hv else "—"
        if self._mode == "nk_import":
            if "plate_width" in pr and "plate_height" in pr:
                rb, rc = "✓ 감지", theme.SUCCESS
            elif not wv or not hv:
                rb, rc = "⚠ 미감지", theme.ERROR
            else:
                rb, rc = "– 기본값", theme.TEXT_DIM
        else:
            rb, rc = _badge_preset_view("plate_width", m)
        lay.addWidget(_row_widget("해상도", res, rb, rc))

        pfn = m.get("plate_format_name") or ""
        if self._mode == "nk_import":
            pb, pc = _badge_nk_import("plate_format_name", m, pr, set())
        else:
            pb, pc = _badge_preset_view("plate_format_name", m)
        lay.addWidget(_row_widget("포맷 이름", pfn or "—", pb, pc))

        lay.addWidget(_section_header("Color Management (OCIO)"))
        for k, label in [
            ("color_management", "Color Management"),
            ("ocio_path", "Config 경로"),
            ("working_space_lut", "Working Space"),
            ("monitor_lut", "Monitor"),
            ("int8_lut", "8-bit files"),
            ("int16_lut", "16-bit files"),
            ("log_lut", "log files"),
            ("float_lut", "float files"),
            ("viewer_process", "Viewer Process"),
        ]:
            val = m.get(k) or ""
            if k == "ocio_path" and val:
                disp = str(val)
            else:
                disp = val or "—"
            if self._mode == "nk_import":
                ocio_imp = {"ocio_path"} if k == "ocio_path" else set()
                b, c = _badge_nk_import(k, m, pr, ocio_imp)
            else:
                b, c = _badge_preset_view(k, m)
            lay.addWidget(_row_widget(label, disp, b, c))

    def _populate_exr(self, lay: QVBoxLayout) -> None:
        m = self._merged
        pr = self._parsed_raw
        important = set(_IMPORTANT_KEYS)

        for k, label in [
            ("delivery_format", "납품 포맷"),
            ("write_datatype", "Datatype"),
            ("write_compression", "Compression"),
            ("write_out_colorspace", "Output Colorspace"),
            ("write_channels", "Channels"),
            ("write_metadata", "Metadata"),
            ("write_transform_type", "Transform Type"),
            ("write_output_display", "Display"),
            ("write_output_view", "View"),
        ]:
            val = m.get(k) or ""
            imp = important if k in ("write_datatype", "write_compression") else set()
            if self._mode == "nk_import":
                b, c = _badge_nk_import(k, m, pr, imp)
            else:
                b, c = _badge_preset_view(k, m)
            lay.addWidget(_row_widget(label, str(val) or "—", b, c))

    def _populate_mov(self, lay: QVBoxLayout) -> None:
        m = self._merged
        pr = self._parsed_raw

        for k, label in [
            ("mov_codec", "Codec"),
            ("mov_profile", "Codec Profile"),
            ("mov_fps", "FPS"),
            ("mov_channels", "Channels"),
            ("mov_colorspace", "Output Colorspace"),
            ("mov_display", "Display"),
            ("mov_view", "View"),
        ]:
            val = m.get(k) or ""
            if self._mode == "nk_import":
                b, c = _badge_nk_import(k, m, pr, set())
            else:
                b, c = _badge_preset_view(k, m)
            lay.addWidget(_row_widget(label, str(val) or "—", b, c))

    def _populate_plate_nodes(self, lay: QVBoxLayout) -> None:
        m = self._merged
        pr = self._parsed_raw
        important = set(_IMPORTANT_KEYS)
        ns = self._node_stats

        lay.addWidget(_section_header("Plate Input (Read)"))
        rit = m.get("read_input_transform") or ""
        if self._mode == "nk_import":
            b, c = _badge_nk_import("read_input_transform", m, pr, important)
        else:
            b, c = _badge_preset_view("read_input_transform", m)
        lay.addWidget(_row_widget("Input Transform", str(rit) or "—", b, c))

        lay.addWidget(_section_header("노드트리"))
        total = ns.get("total", 0)
        wnames = ", ".join(ns.get("write_names", [])) or "—"
        rnames = ", ".join(ns.get("read_names", [])) or "—"
        lay.addWidget(
            _row_widget(
                "전체 노드 수",
                str(total),
                "✓ 감지" if total else "–",
                theme.SUCCESS if total else theme.TEXT_DIM,
            )
        )
        lay.addWidget(
            _row_widget(
                "Write 노드",
                wnames,
                "✓ 감지" if wnames != "—" else "–",
                theme.TEXT_DIM,
            )
        )
        lay.addWidget(
            _row_widget(
                "Read 노드",
                rnames,
                "✓ 감지" if rnames != "—" else "–",
                theme.TEXT_DIM,
            )
        )
        tpl_note = "—"
        if self._mode == "preset_view" and self._preset_name:
            tpl_path = get_preset_template_path(self._preset_name)
            tpl_note = "저장됨" if tpl_path.exists() else "없음"
        elif self._mode == "nk_import":
            tpl_note = "프리셋 저장 시 NK 템플릿으로 저장"
        lay.addWidget(
            _row_widget(
                "NK 템플릿",
                tpl_note,
                "✓" if tpl_note != "없음" else "–",
                theme.SUCCESS if tpl_note != "없음" else theme.TEXT_DIM,
            )
        )
