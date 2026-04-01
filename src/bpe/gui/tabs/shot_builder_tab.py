"""Shot Builder tab — build server paths and generate NK files from presets."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.core.nk_finder import find_nukex_exe_and_args, find_server_root_auto
from bpe.core.nk_generator import generate_nk_content
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.presets import load_presets
from bpe.core.settings import get_shot_builder_settings, save_shot_builder_settings
from bpe.core.shot_builder import (
    build_shot_paths,
    comp_devl_structure_exists,
    ensure_comp_folder_structure,
    parse_shot_name,
)
from bpe.gui import theme

_NK_VERSION = "v001"
_LOG_RULE = "─" * 42
_LOG_FONT_PX = theme.FONT_SIZE + 2


def _resolve_preset_key(presets: Dict[str, Any], name: str) -> Optional[str]:
    """presets.json 키와 대소문자만 다른 경우에도 매칭한다."""
    n = (name or "").strip()
    if not n:
        return None
    if n in presets:
        return n
    for k in presets:
        if k.upper() == n.upper():
            return k
    return None


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
    """My Tasks에서 열 때는 *task_data*로 자동 세팅(읽기 전용). 단독 호출 시 수동 입력."""

    def __init__(
        self,
        task_data: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._last_open_folder_path: Optional[Path] = None
        self._last_nk_path: Optional[Path] = None
        self._auto_mode = task_data is not None
        self._server_root_str: str = ""
        self._preset_name_str: str = ""
        self._shot_display_str: str = ""

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

        form = QVBoxLayout()
        form.setSpacing(16)

        if self._auto_mode:
            self._build_form_auto(form, task_data or {})
        else:
            self._build_form_manual(form)

        root.addLayout(form)

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

        self._open_nukex_btn = QPushButton("NukeX로 열기")
        self._open_nukex_btn.setEnabled(False)
        self._open_nukex_btn.clicked.connect(self._open_nukex)
        btn_row.addWidget(self._open_nukex_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addSpacing(24)
        log_title = QLabel("실행 결과")
        log_title.setObjectName("log_title")
        root.addWidget(log_title)
        root.addSpacing(8)

        self._log = QPlainTextEdit()
        self._log.setObjectName("log_area")
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"QPlainTextEdit#log_area {{ font-size: {_LOG_FONT_PX}px; }}")
        root.addWidget(self._log, 1)

        if not self._auto_mode:
            self._restore_settings()

    def _build_form_auto(self, form: QVBoxLayout, task_data: Dict[str, Any]) -> None:
        shot_code = (task_data.get("shot_code") or "").strip()
        project_code = (
            task_data.get("project_code") or task_data.get("project_folder") or ""
        ).strip()
        env_root = (os.environ.get("BPE_SERVER_ROOT") or "").strip()
        server_root = (find_server_root_auto(project_code) if project_code else None) or env_root
        self._server_root_str = server_root.strip()
        self._preset_name_str = project_code

        parsed = parse_shot_name(shot_code)
        self._shot_display_str = parsed["full"] if parsed else shot_code.upper()

        self._path_label = QLabel("")
        self._path_label.setWordWrap(True)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_label.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE}px;")

        if self._server_root_str and project_code and parsed:
            paths = build_shot_paths(self._server_root_str, project_code, shot_code)
            if paths:
                nk_v001 = paths["nuke_dir"] / _NK_VERSION
                self._path_label.setText(normalize_path_str(str(nk_v001)))
            else:
                self._path_label.setText("(경로를 계산할 수 없습니다)")
        else:
            missing: List[str] = []
            if not self._server_root_str:
                missing.append("서버 루트")
            if not project_code:
                missing.append("프로젝트 코드")
            if not parsed:
                missing.append("샷 이름 형식")
            self._path_label.setText(
                "자동 설정 실패: "
                + ", ".join(missing)
                + ". BPE_SERVER_ROOT 또는 드라이브 매핑을 확인하세요."
            )

        form.addLayout(_form_row("NK 작업 경로", self._path_label))

        hint_auto = QLabel("선택된 샷 기준으로 v001 폴더까지의 경로입니다. (자동)")
        hint_auto.setProperty("dim", True)
        hint_auto.setWordWrap(True)
        hint_auto.setContentsMargins(132, 0, 0, 0)
        form.addWidget(hint_auto)

        self._preset_label_ro = QLabel(project_code or "—")
        self._preset_label_ro.setStyleSheet(f"color: {theme.TEXT};")
        form.addLayout(_form_row("프로젝트(프리셋)", self._preset_label_ro))

        self._shot_label_ro = QLabel(self._shot_display_str or "—")
        self._shot_label_ro.setStyleSheet(f"color: {theme.TEXT};")
        form.addLayout(_form_row("샷 이름", self._shot_label_ro))

        self._server_root_edit = None
        self._preset_combo = None
        self._shot_name_edit = None

    def _build_form_manual(self, form: QVBoxLayout) -> None:
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

        hint = QLabel("프로젝트 폴더들이 모여 있는 바로 위 폴더까지만 입력합니다.")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        hint.setContentsMargins(132, 0, 0, 0)
        form.addWidget(hint)

        self._preset_combo = QComboBox()
        self._refresh_preset_list()
        form.addLayout(_form_row("프리셋 선택", self._preset_combo))

        hint2 = QLabel("프리셋 이름이 서버의 프로젝트 폴더명으로 사용됩니다.")
        hint2.setProperty("dim", True)
        hint2.setContentsMargins(132, 0, 0, 0)
        form.addWidget(hint2)

        self._shot_name_edit = QLineEdit()
        self._shot_name_edit.setPlaceholderText("E107_S022_0080")
        form.addLayout(_form_row("샷 이름", self._shot_name_edit))

        self._path_label = None
        self._preset_label_ro = None
        self._shot_label_ro = None

    def _refresh_preset_list(self) -> None:
        if self._preset_combo is None:
            return
        presets = load_presets()
        self._preset_combo.clear()
        self._preset_combo.addItems(sorted(presets.keys()))

    def _restore_settings(self) -> None:
        if self._server_root_edit is None:
            return
        settings = get_shot_builder_settings()
        if settings.get("server_root"):
            self._server_root_edit.setText(normalize_path_str(settings["server_root"]))
        if settings.get("preset") and self._preset_combo is not None:
            idx = self._preset_combo.findText(settings["preset"])
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)

    def _save_settings(self) -> None:
        if self._server_root_edit is None or self._preset_combo is None:
            return
        save_shot_builder_settings(
            {
                "server_root": self._server_root_edit.text().strip(),
                "preset": self._preset_combo.currentText(),
            }
        )

    def _append_success_log(
        self,
        preset_name: str,
        shot_display: str,
        nk_path: Path,
        paths: Dict[str, Path],
        warnings: List[str],
    ) -> None:
        self._log.appendPlainText("[성공] NK 파일이 생성되었습니다.")
        self._log.appendPlainText(_LOG_RULE)
        self._log.appendPlainText(f"샷 이름      : {shot_display}")
        self._log.appendPlainText(f"프리셋       : {preset_name}")
        self._log.appendPlainText(_LOG_RULE)
        self._log.appendPlainText(f"NK 파일      : {normalize_path_str(nk_path)}")
        self._log.appendPlainText(f"플레이트 경로 : {normalize_path_str(paths['plate_hi'])}")
        self._log.appendPlainText(f"Edit 경로    : {normalize_path_str(paths['edit'])}")
        self._log.appendPlainText(f"렌더 경로    : {normalize_path_str(paths['renders'])}")
        self._log.appendPlainText(f"엘리먼트 경로 : {normalize_path_str(paths['element'])}")
        self._log.appendPlainText(f"샷 루트      : {normalize_path_str(paths['shot_root'])}")
        self._log.appendPlainText(_LOG_RULE)
        self._log.appendPlainText(
            "※ 이 NK는 v001 전용입니다. 버전업·덮어쓰기는 NukeX에서 직접 진행하세요."
        )
        if warnings:
            self._log.appendPlainText(_LOG_RULE)
            for w in warnings:
                self._log.appendPlainText(w)

    def _browse_server_root(self) -> None:
        if self._server_root_edit is None:
            return
        path = QFileDialog.getExistingDirectory(
            self, "서버 루트 경로 선택", self._server_root_edit.text()
        )
        if path:
            self._server_root_edit.setText(normalize_path_str(path))

    def _gather_inputs(self) -> Optional[tuple[str, str, str]]:
        """Returns (server_root, preset_name, shot_name_raw) or None if invalid."""
        if self._auto_mode:
            if not self._server_root_str:
                return None
            if not self._preset_name_str:
                return None
            if not self._shot_display_str:
                return None
            return (self._server_root_str, self._preset_name_str, self._shot_display_str)

        assert self._server_root_edit is not None
        assert self._preset_combo is not None
        assert self._shot_name_edit is not None
        return (
            self._server_root_edit.text().strip(),
            self._preset_combo.currentText().strip(),
            self._shot_name_edit.text().strip(),
        )

    def _create_nk(self) -> None:
        self._log.clear()
        self._open_folder_btn.setEnabled(False)
        self._last_open_folder_path = None

        g = self._gather_inputs()
        if g is None:
            if self._auto_mode:
                self._log.appendPlainText(
                    "[오류] 서버 루트 또는 샷 정보를 확인할 수 없습니다. "
                    "BPE_SERVER_ROOT 환경 변수 또는 프로젝트 폴더 매핑을 확인하세요."
                )
            else:
                self._log.appendPlainText("[오류] 서버 루트·프리셋·샷 이름을 입력해주세요.")
            return

        server_root, preset_name, shot_name = g
        server_root = normalize_path_str(server_root)

        if not self._auto_mode:
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

        shot_display = parsed["full"]

        presets = load_presets()
        preset_key = _resolve_preset_key(presets, preset_name)
        if preset_key is None:
            self._log.appendPlainText(f"[오류] 프리셋 '{preset_name}'을(를) 찾을 수 없습니다.")
            return
        preset_data = presets[preset_key]
        if not isinstance(preset_data, dict):
            self._log.appendPlainText(f"[오류] 프리셋 '{preset_key}' 데이터가 올바르지 않습니다.")
            return

        paths = build_shot_paths(server_root, preset_key, shot_name)
        if paths is None:
            self._log.appendPlainText("[오류] 경로를 생성할 수 없습니다.")
            return

        nuke_dir = paths["nuke_dir"]
        nk_v001_dir = nuke_dir / _NK_VERSION
        nk_filename = f"{shot_display}_comp_{_NK_VERSION}.nk"
        nk_path = nk_v001_dir / nk_filename

        if nk_v001_dir.exists():
            existing_nks = list(nk_v001_dir.glob("*.nk"))
            if existing_nks:
                self._log.appendPlainText(
                    "[오류] v001 폴더에 이미 NK 파일이 있습니다. "
                    "덮어쓰기·버전업은 NukeX에서 직접 진행해주세요."
                )
                for p in sorted(existing_nks):
                    self._log.appendPlainText(f"  - {normalize_path_str(p)}")
                return

        if not nk_v001_dir.exists():
            if not comp_devl_structure_exists(paths):
                msg = (
                    "comp/devl 아래 표준 폴더 구조(nuke, renders, element)가 없습니다.\n"
                    "지금 생성할까요?"
                )
            else:
                msg = "nuke/v001 폴더가 없습니다. 생성할까요?"
            reply = QMessageBox.question(
                self,
                "폴더 생성",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._log.appendPlainText("[취소] 폴더를 만들지 않아 NK를 생성하지 않았습니다.")
                return
            try:
                created = ensure_comp_folder_structure(paths, _NK_VERSION)
                if created:
                    self._log.appendPlainText("[안내] 생성된 폴더:")
                    for c in created:
                        self._log.appendPlainText(f"  - {normalize_path_str(c)}")
            except OSError as e:
                self._log.appendPlainText(f"[오류] 폴더 생성 실패: {e}")
                return

        nk_content, warnings = generate_nk_content(preset_data, shot_display, paths, _NK_VERSION)

        try:
            nk_v001_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log.appendPlainText(f"[오류] 폴더 생성 실패: {e}")
            return

        try:
            nk_path.write_text(nk_content, encoding="utf-8")
        except OSError as e:
            self._log.appendPlainText(f"[오류] NK 파일 저장 실패: {e}")
            return

        self._last_open_folder_path = nk_v001_dir
        self._last_nk_path = nk_path
        self._open_folder_btn.setEnabled(True)
        self._open_nukex_btn.setEnabled(True)

        self._append_success_log(preset_key, shot_display, nk_path, paths, warnings)

        if not self._auto_mode:
            self._save_settings()

    def _open_folder(self) -> None:
        if self._last_open_folder_path is None:
            return
        target = self._last_open_folder_path
        if not target.exists():
            return

        path_str = normalize_path_str(target)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path_str])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path_str])
        else:
            subprocess.Popen(["xdg-open", path_str])

    def _open_nukex(self) -> None:
        if self._last_nk_path is None or not self._last_nk_path.is_file():
            return
        exe, extra_args = find_nukex_exe_and_args()
        if exe is None:
            QMessageBox.warning(
                self,
                "NukeX",
                "NukeX 실행 파일을 찾지 못했습니다.\n"
                "Nuke 설치 후 다시 시도하거나 BPE_NUKEX_EXE 환경 변수를 설정하세요.",
            )
            return
        try:
            subprocess.Popen(
                [str(exe), *extra_args, normalize_path_str(self._last_nk_path)],
                close_fds=True,
            )
        except OSError as e:
            QMessageBox.warning(self, "NukeX", f"NK 파일을 열 수 없습니다:\n{e}")
