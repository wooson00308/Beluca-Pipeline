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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bpe.core.shot_builder import build_shot_paths, parse_shot_name
from bpe.core.nk_generator import generate_nk_content
from bpe.core.presets import load_presets
from bpe.core.settings import get_shot_builder_settings, save_shot_builder_settings


class ShotBuilderTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._last_paths: Optional[Dict[str, Path]] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 16)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        title = QLabel("Shot Builder")
        title.setProperty("class", "title")
        hdr.addWidget(title)
        subtitle = QLabel("샷 이름 하나로 NK 파일 + 경로 자동 생성")
        subtitle.setProperty("dim", True)
        hdr.addWidget(subtitle)
        hdr.addStretch()
        root.addLayout(hdr)
        root.addSpacing(12)

        # ── Form area ───────────────────────────────────────────
        form = QVBoxLayout()
        form.setSpacing(8)

        # Server root
        form.addWidget(self._make_section_label("STEP 1   서버 설정"))
        srv_row = QHBoxLayout()
        srv_row.setSpacing(6)
        form.addWidget(QLabel("서버 루트 경로"))
        self._server_root_edit = QLineEdit()
        self._server_root_edit.setPlaceholderText("예) W:/vfx/project_2026")
        srv_row.addWidget(self._server_root_edit, 1)
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_server_root)
        srv_row.addWidget(browse_btn)
        form.addLayout(srv_row)

        hint = QLabel(
            "서버에서 프로젝트 폴더들이 모여 있는 바로 위 폴더까지만 입력합니다.\n"
            "예) W:/vfx/project_2026/SBS_030 → W:/vfx/project_2026 까지만 입력"
        )
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        form.addWidget(hint)

        # Preset selection
        form.addWidget(QLabel("프리셋 선택"))
        self._preset_combo = QComboBox()
        self._refresh_preset_list()
        form.addWidget(self._preset_combo)

        hint2 = QLabel("프리셋 이름이 서버의 프로젝트 폴더명으로 사용됩니다.")
        hint2.setProperty("dim", True)
        form.addWidget(hint2)

        # ── Step 2 ──────────────────────────────────────────────
        form.addSpacing(8)
        form.addWidget(self._make_section_label("STEP 2   샷 정보"))

        form.addWidget(QLabel("샷 이름"))
        self._shot_name_edit = QLineEdit()
        self._shot_name_edit.setPlaceholderText("E107_S022_0080")
        self._shot_name_edit.textChanged.connect(self._update_path_preview)
        form.addWidget(self._shot_name_edit)

        form.addWidget(QLabel("NK 버전"))
        self._nk_version_spin = QSpinBox()
        self._nk_version_spin.setMinimum(1)
        self._nk_version_spin.setMaximum(999)
        self._nk_version_spin.setValue(1)
        self._nk_version_spin.setFixedWidth(100)
        form.addWidget(self._nk_version_spin)

        # Path preview
        form.addWidget(QLabel("경로 미리보기"))
        self._path_preview = QLabel("—")
        self._path_preview.setProperty("dim", True)
        self._path_preview.setWordWrap(True)
        self._path_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addWidget(self._path_preview)

        # ── Buttons ─────────────────────────────────────────────
        form.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        create_btn = QPushButton("NK 파일 생성")
        create_btn.setProperty("primary", True)
        create_btn.clicked.connect(self._create_nk)
        btn_row.addWidget(create_btn)

        self._open_folder_btn = QPushButton("폴더 열기")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self._open_folder_btn)

        btn_row.addStretch()
        form.addLayout(btn_row)

        root.addLayout(form)

        # ── Step 3 — Log ────────────────────────────────────────
        root.addSpacing(8)
        root.addWidget(self._make_section_label("STEP 3   실행 결과"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        root.addWidget(self._log, 1)

        # ── Restore saved settings ──────────────────────────────
        self._restore_settings()

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _make_section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #f08a24; font-weight: bold;")
        return lbl

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

    # ── Slots ────────────────────────────────────────────────────

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
            self._path_preview.setText("—")
            self._last_paths = None
            return

        paths = build_shot_paths(server_root, preset_name, shot_name)
        if paths is None:
            self._path_preview.setText("샷 이름을 파싱할 수 없습니다.")
            self._last_paths = None
            return

        self._last_paths = paths
        lines = [f"{key}: {val}" for key, val in paths.items()]
        self._path_preview.setText("\n".join(lines))

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
