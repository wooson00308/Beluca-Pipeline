"""다른 샷의 프레임을 샷 이름으로 찾아 참고 그림으로 고르는 작은 창.

컨펌 창의 메모에 「이 샷처럼」 하고 붙일 그림을 고른다. 영상은 읽기만 하고,
고른 한 장은 컨펌 창이 붙인 그림(Ctrl+V 로 붙인 것과 같은 자리)으로 받는다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_decode import build_still_command
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs
from bpe.gui.confirm import style
from bpe.gui.workers.sg_worker import ShotGridWorker

logger = get_logger("gui.confirm.ref_frame")

_PREVIEW_W, _PREVIEW_H = 720, 405
_STILL_EDGE = 1280
_DEBOUNCE_MS = 220
_STILL_TIMEOUT = 120
_PLATE_LABEL = "ORG plate"

Source = Dict[str, Any]  # {"label": 이름, "path": 파일, "frames": 프레임 수}


def read_still(path: str, index: int, lut_file: str = "") -> bytes:
    """영상의 *index* 번째 프레임을 PNG 바이트로 읽는다(뒤에서 돈다)."""
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg 를 찾지 못했습니다")
    cmd = build_still_command(str(ffmpeg), path, index, max_edge=_STILL_EDGE, lut_file=lut_file)
    done = subprocess.run(
        cmd, capture_output=True, timeout=_STILL_TIMEOUT, **no_console_subprocess_kwargs()
    )
    if done.returncode != 0 or not done.stdout:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        raise RuntimeError(tail[0] if tail else "프레임을 읽지 못했습니다")
    return done.stdout


class RefFrameDialog(QDialog):
    """샷 이름 → 그 샷의 영상(최신 작업본·원본·편집본) → 프레임 한 장 고르기."""

    frame_picked = Signal(object, str)  # QImage, 메모에 적을 한 줄

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        find_sources: Callable[[str], List[Source]],
        lut_file: str = "",
        frame_start: int = 1001,
        shot_hint: str = "",
        reader: Callable[[str, int, str], bytes] = read_still,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("다른 샷 프레임 붙이기")
        self.setModal(False)
        self._find_sources = find_sources
        self._reader = reader
        self._lut_file = lut_file
        self._frame_start = int(frame_start)
        self._workers: List[Any] = []
        self._sources: List[Source] = []
        self._shot = ""
        self._image: Optional[QImage] = None
        self._find_req = 0
        self._still_req = 0
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._load_still)
        self._build_ui(shot_hint)

    def _build_ui(self, shot_hint: str) -> None:
        self.setStyleSheet(f"QDialog {{ background: {style.PANEL}; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._shot_edit = QLineEdit(shot_hint)
        self._shot_edit.setPlaceholderText("샷 이름 (예: ep02_s048_0010)")
        self._shot_edit.returnPressed.connect(self._find)
        top.addWidget(self._shot_edit, 1)
        self._btn_find = QPushButton("찾기")
        self._btn_find.setAutoDefault(False)
        self._btn_find.clicked.connect(self._find)
        top.addWidget(self._btn_find)
        col.addLayout(top)

        pick = QHBoxLayout()
        pick.setSpacing(8)
        self._source = QComboBox()
        self._source.setMinimumWidth(440)
        self._source.currentIndexChanged.connect(self._on_source)
        pick.addWidget(self._source)
        self._lut_box = QCheckBox("룩업 씌우기")
        self._lut_box.setToolTip("로그로 된 영상(원본)에 프로젝트 룩업을 씌워 보여 줍니다")
        self._lut_box.setEnabled(bool(self._lut_file))
        self._lut_box.toggled.connect(lambda _on: self._timer.start())
        pick.addWidget(self._lut_box)
        pick.addStretch(1)
        col.addLayout(pick)

        self._preview = QLabel("샷 이름을 넣고 찾기를 눌러 주세요")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        self._preview.setStyleSheet(
            f"background: #141414; color: {style.DIM}; border: 1px solid {style.EDGE};"
        )
        col.addWidget(self._preview)

        frame = QHBoxLayout()
        frame.setSpacing(8)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setEnabled(False)
        self._slider.valueChanged.connect(self._on_slider)
        frame.addWidget(self._slider, 1)
        self._frame_lbl = QLabel("–")
        self._frame_lbl.setMinimumWidth(96)
        self._frame_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._frame_lbl.setStyleSheet(f"color: {style.TEXT}; {style.mono()}")
        frame.addWidget(self._frame_lbl)
        col.addLayout(frame)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._note = QLabel("")
        self._note.setStyleSheet(f"color: {style.DIM};")
        foot.addWidget(self._note, 1)
        self._btn_take = QPushButton("메모에 붙이기")
        self._btn_take.setAutoDefault(False)
        self._btn_take.setEnabled(False)
        self._btn_take.clicked.connect(self._take)
        foot.addWidget(self._btn_take)
        self._btn_close = QPushButton("닫기")
        self._btn_close.setAutoDefault(False)
        self._btn_close.clicked.connect(self.close)
        foot.addWidget(self._btn_close)
        col.addLayout(foot)

    # ── 찾기 ─────────────────────────────────────────────────────

    def _run(self, fn: Callable[[], Any], done: Callable[[object], None]) -> None:
        w = ShotGridWorker(fn)
        w.finished.connect(done)
        w.error.connect(self._on_error)
        w.start()
        self._workers.append(w)

    def _on_error(self, msg: str) -> None:
        if not self._closed:
            self._note.setText(f"못 읽었습니다: {msg}")

    def _find(self) -> None:
        shot = self._shot_edit.text().strip()
        if not shot:
            return
        self._find_req += 1
        req = self._find_req
        self._note.setText(f"{shot} 찾는 중…")
        find = self._find_sources
        self._run(lambda: find(shot), lambda r, q=req, s=shot: self._on_found(r, q, s))

    def _on_found(self, result: object, req: int, shot: str) -> None:
        if self._closed or req != self._find_req:
            return
        self.set_sources(shot, result if isinstance(result, list) else [])

    def set_sources(self, shot: str, sources: List[Source]) -> None:
        """찾은 영상들을 고르기 칸에 넣고 첫 영상의 가운데 프레임을 보여 준다."""
        self._shot = shot
        self._sources = [s for s in sources if s.get("path")]
        self._image = None
        self._btn_take.setEnabled(False)
        self._source.blockSignals(True)
        self._source.clear()
        for s in self._sources:
            self._source.addItem(f"{s.get('label')}  ·  {Path(str(s['path'])).name}")
        self._source.blockSignals(False)
        if not self._sources:
            self._slider.setEnabled(False)
            self._frame_lbl.setText("–")
            self._preview.setPixmap(QPixmap())
            self._preview.setText("이 이름의 샷 영상을 찾지 못했습니다")
            self._note.setText("")
            return
        self._note.setText("")
        self._on_source(0)

    def _current(self) -> Optional[Source]:
        i = self._source.currentIndex()
        return self._sources[i] if 0 <= i < len(self._sources) else None

    def _on_source(self, _index: int) -> None:
        src = self._current()
        if src is None:
            return
        frames = max(1, int(src.get("frames") or 1))
        self._slider.blockSignals(True)
        self._slider.setRange(0, frames - 1)
        self._slider.setValue((frames - 1) // 2)
        self._slider.blockSignals(False)
        self._slider.setEnabled(frames > 1)
        # 원본은 로그라서 룩업을 씌워 보여 주고, 작업본·편집본은 그대로 둔다(직접 바꿀 수 있다)
        self._lut_box.blockSignals(True)
        self._lut_box.setChecked(bool(self._lut_file) and src.get("label") == _PLATE_LABEL)
        self._lut_box.blockSignals(False)
        self._show_frame_number()
        self._load_still()

    def _on_slider(self, _value: int) -> None:
        self._show_frame_number()
        self._timer.start()

    def frame_number(self) -> int:
        return self._frame_start + self._slider.value()

    def _show_frame_number(self) -> None:
        last = self._frame_start + self._slider.maximum()
        self._frame_lbl.setText(f"{self.frame_number()} / {last}")

    # ── 한 장 읽기 ───────────────────────────────────────────────

    def _load_still(self) -> None:
        src = self._current()
        if src is None or self._closed:
            return
        self._still_req += 1
        req = self._still_req
        path, index = str(src["path"]), self._slider.value()
        lut = self._lut_file if self._lut_box.isChecked() else ""
        reader = self._reader
        self._note.setText("프레임 읽는 중…")
        self._run(lambda: reader(path, index, lut), lambda r, q=req: self._on_still(r, q))

    def _on_still(self, data: object, req: int) -> None:
        if self._closed or req != self._still_req:
            return
        image = QImage()
        if not isinstance(data, (bytes, bytearray)) or not image.loadFromData(bytes(data)):
            self._note.setText("프레임을 그림으로 바꾸지 못했습니다")
            return
        self._image = image
        self._preview.setText("")
        self._preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                _PREVIEW_W,
                _PREVIEW_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._note.setText("")
        self._btn_take.setEnabled(True)

    def caption(self) -> str:
        """메모에 적을 한 줄 — 어느 샷의 어느 영상 몇 프레임인지."""
        src = self._current()
        label = str(src.get("label")) if src else ""
        return f"참고: {self._shot} {label} {self.frame_number()}".strip()

    def _take(self) -> None:
        if self._image is None:
            return
        self.frame_picked.emit(self._image, self.caption())
        self._note.setText("메모에 붙였습니다 — 다른 프레임도 더 붙일 수 있습니다")

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._closed = True
        self._timer.stop()
        for w in self._workers:
            try:
                if w.isRunning():
                    w.wait(3000)
            except RuntimeError:
                pass
        self._workers.clear()
        super().closeEvent(event)
