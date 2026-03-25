"""Shot Builder tab — build server paths and generate NK files from presets."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bpe.core.shot_builder import build_shot_paths, parse_shot_name
from bpe.core.nk_generator import generate_nk_content
from bpe.core.presets import load_presets
from bpe.core.settings import get_shot_builder_settings, save_shot_builder_settings


def _form_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label_text)
    lbl.setObjectName("form_label")
    lbl.setFixedWidth(120)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


class ShotBuilderTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._last_paths: Optional[Dict[str, Path]] = None

        # ── Outer layout (holds scroll area) ──────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        title = QLabel("Shot Builder")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        subtitle = QLabel("샷 폴더 구조 · NK 파일 자동 생성")
        subtitle.setObjectName("page_subtitle")
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(24)

        # ── Form area ─────────────────────────────────────────────
        form = QVBoxLayout()
        form.setSpacing(16)

        # Server root — browse button sits next to the input
        srv_input = QWidget()
        srv_layout = QHBoxLayout(srv_input)
        srv_layout.setContentsMargins(0, 0, 0, 0)
        srv_layout.setSpacing(8)
        self._server_root_edit = QLineEdit()
        self._server_root_edit.setPlaceholderText("예) W:/vfx/project_2026")
        srv_layout.addWidget(self._server_root_edit, 1)
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_server_root)
        srv_layout.addWidget(browse_btn)
        form.addLayout(_form_row("서버 루트 경로", srv_input))

        # Server root hint (dim, indented past label)
        hint = QLabel(
            "프로젝트 폴더들이 모여 있는 바로 위 폴더까지만 입력합니다."
        )
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        hint.setContentsMargins(132, 0, 0, 0)
        form.addWidget(hint)

        # Preset selection
        self._preset_combo = QComboBox()
        self._refresh_preset_list()
        form.addLayout(_form_row("프리셋 선택", self._preset_combo))

        hint2 = QLabel("프리셋 이름이 서버의 프로젝트 폴더명으로 사용됩니다.")
        hint2.setProperty("dim", True)
        hint2.setContentsMargins(132, 0, 0, 0)
        form.addWidget(hint2)

        # Shot name
        self._shot_name_edit = QLineEdit()
        self._shot_name_edit.setPlaceholderText("E107_S022_0080")
        self._shot_name_edit.textChanged.connect(self._update_path_preview)
        form.addLayout(_form_row("샷 이름", self._shot_name_edit))

        # NK version
        self._nk_version_spin = QSpinBox()
        self._nk_version_spin.setMinimum(1)
        self._nk_version_spin.setMaximum(999)
        self._nk_version_spin.setValue(1)
        self._nk_version_spin.setFixedWidth(100)
        form.addLayout(_form_row("NK 버전", self._nk_version_spin))

        # Path preview — individual dim labels
        preview_title_lbl = QLabel("경로 미리보기")
        preview_title_lbl.setObjectName("form_label")
        preview_title_lbl.setFixedWidth(120)
        preview_title_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        self._path_preview_container = QVBoxLayout()
        self._path_preview_container.setSpacing(4)
        self._path_preview_placeholder = QLabel("—")
        self._path_preview_placeholder.setProperty("dim", True)
        self._path_preview_placeholder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._path_preview_container.addWidget(self._path_preview_placeholder)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        preview_row.addWidget(preview_title_lbl, 0, Qt.AlignmentFlag.AlignTop)
        preview_right = QWidget()
        preview_right.setLayout(self._path_preview_container)
        preview_row.addWidget(preview_right, 1)
        form.addLayout(preview_row)

        root.addLayout(form)

        # ── Buttons ───────────────────────────────────────────────
        root.addSpacing(24)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        create_btn = QPushButton("NK 파일 생성")
        create_btn.setProperty("primary", True)
        create_btn.clicked.connect(self._create_nk)
        btn_row.addWidget(create_btn)

        self._open_folder_btn = QPushButton("폴더 열기")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self._open_folder_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── Log area ──────────────────────────────────────────────
        root.addSpacing(24)
        log_title = QLabel("실행 결과")
        log_title.setObjectName("log_title")
        root.addWidget(log_title)
        root.addSpacing(8)

        self._log = QPlainTextEdit()
        self._log.setObjectName("log_area")
        self._log.setReadOnly(True)
        root.addWidget(self._log, 1)

        # ── Restore saved settings ────────────────────────────────
        self._restore_settings()

    # ── Helpers ───────────────────────────────────────────────────

    def _refresh_preset_list(self) -> None:
        presets = load_presets()
        self._preset_combo.clear()
        self._preset_combo.addItems(sorted(presets.keys()))

    def _restore_settings(self) -> None:
        settings = get_shot_builder_settings()
        if settings.get("server_root"):
            self._server_root_edit.setText(settings["server_root"])
        if settings.get("preset"):
            idx = self._preset_combo.findText(settings["preset"])
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)

    def _save_settings(self) -> None:
        save_shot_builder_settings({
            "server_root": self._server_root_edit.text().strip(),
            "preset": self._preset_combo.currentText(),
        })

    def _clear_path_preview(self) -> None:
        while self._path_preview_container.count():
            item = self._path_preview_container.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _set_path_preview_lines(self, lines: list[str]) -> None:
        self._clear_path_preview()
        for line in lines:
            lbl = QLabel(line)
            lbl.setProperty("dim", True)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._path_preview_container.addWidget(lbl)

    # ── Slots ─────────────────────────────────────────────────────

    def _browse_server_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "서버 루트 경로 선택", self._server_root_edit.text()
        )
        if path:
            self._server_root_edit.setText(path)

    def _update_path_preview(self) -> None:
        server_root = self._server_root_edit.text().strip()
        preset_name = self._preset_combo.currentText().strip()
        shot_name = self._shot_name_edit.text().strip()

        if not server_root or not preset_name or not shot_name:
            self._clear_path_preview()
            placeholder = QLabel("—")
            placeholder.setProperty("dim", True)
            self._path_preview_container.addWidget(placeholder)
            self._last_paths = None
            return

        paths = build_shot_paths(server_root, preset_name, shot_name)
        if paths is None:
            self._clear_path_preview()
            err = QLabel("샷 이름을 파싱할 수 없습니다.")
            err.setProperty("dim", True)
            self._path_preview_container.addWidget(err)
            self._last_paths = None
            return

        self._last_paths = paths
        self._set_path_preview_lines(
            [f"{key}: {val}" for key, val in paths.items()]
        )

    def _create_nk(self) -> None:
        self._log.clear()

        server_root = self._server_root_edit.text().strip()
        preset_name = self._preset_combo.currentText().strip()
        shot_name = self._shot_name_edit.text().strip()

        if not server_root:
            self._log.appendPlainText("[오류] 서버 루트 경로를 입력해주세요.")
            return
        if not preset_name:
            self._log.appendPlainText("[오류] 프리셋을 선택해주세요.")
            return
        if not shot_name:
            self._log.appendPlainText("[오류] 샷 이름을 입력해주세요.")
            return

        parsed = parse_shot_name(shot_name)
        if parsed is None:
            self._log.appendPlainText("[오류] 샷 이름 형식이 올바르지 않습니다. 예) E107_S022_0080")
            return

        paths = build_shot_paths(server_root, preset_name, shot_name)
        if paths is None:
            self._log.appendPlainText("[오류] 경로를 생성할 수 없습니다.")
            return

        presets = load_presets()
        preset_data = presets.get(preset_name)
        if not preset_data or not isinstance(preset_data, dict):
            self._log.appendPlainText(f"[오류] 프리셋 '{preset_name}'을(를) 찾을 수 없습니다.")
            return

        nk_version = f"v{self._nk_version_spin.value():03d}"
        nk_content, warnings = generate_nk_content(
            preset_data, shot_name, paths, nk_version
        )

        # Ensure directories exist
        nuke_dir = paths["nuke_dir"]
        try:
            nuke_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log.appendPlainText(f"[오류] 폴더 생성 실패: {e}")
            return

        nk_filename = f"{shot_name}_comp_{nk_version}.nk"
        nk_path = nuke_dir / nk_filename

        try:
            nk_path.write_text(nk_content, encoding="utf-8")
        except OSError as e:
            self._log.appendPlainText(f"[오류] NK 파일 저장 실패: {e}")
            return

        self._last_paths = paths
        self._open_folder_btn.setEnabled(True)

        self._log.appendPlainText(f"NK 파일 생성 완료: {nk_path}")
        for w in warnings:
            self._log.appendPlainText(w)

        # Save last used settings
        self._save_settings()

    def _open_folder(self) -> None:
        if self._last_paths is None:
            return
        target = self._last_paths.get("nuke_dir")
        if target is None or not target.exists():
            target = self._last_paths.get("shot_root")
        if target is None:
            return

        path_str = str(target)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path_str])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path_str])
        else:
            subprocess.Popen(["xdg-open", path_str])
