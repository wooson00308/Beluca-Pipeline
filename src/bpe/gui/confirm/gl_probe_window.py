"""컨펌 창 1단계 — 이 PC 에서 화면 계산(16비트·차이·게인·감마)이 되는지 보는 시험 창.

새 컨펌 창은 영상을 그래픽 카드로 계산해서 보여 준다. 그 방식이 팀 PC·원격 접속·
빌드된 exe 에서 통하는지 먼저 확인하려고 만든 작은 창이다.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_test_pattern import make_test_pattern
from bpe.core.confirm_view_math import (
    CHANNEL_B,
    CHANNEL_G,
    CHANNEL_LUMA,
    CHANNEL_R,
    CHANNEL_RGB,
    VIEW_MODE_A,
    VIEW_MODE_B,
    VIEW_MODE_DIFF,
)
from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from bpe.core.logging import get_logger
from bpe.gui import theme
from bpe.gui.confirm.gl_selfcheck import GLSelfCheck, run_gl_selfcheck
from bpe.gui.confirm.viewer_gl import SLOT_A, SLOT_B, ConfirmGLView
from bpe.gui.workers.confirm_decode_worker import FirstFrameDecodeWorker

logger = get_logger("gui.confirm.gl_probe_window")

_PATTERN_W, _PATTERN_H = 960, 540
_GAIN_STEPS_PER_STOP = 4
_GAMMA_SCALE = 100
_WORKER_WAIT_MS = 5000
_VERDICT_STYLE = f"font-size: {theme.FONT_SIZE + 2}px; font-weight: bold;"
_VIDEO_FILTER = "영상 (*.mov *.mp4 *.mxf *.mkv *.m4v);;모든 파일 (*)"


class ConfirmGLProbeWindow(QWidget):
    """화면 계산 시험 창 — 부모 없는 독립 창으로 띄운다."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BPE 컨펌 창 — 화면 계산 시험")
        self.resize(1280, 720)
        self._closed = False
        self._aumid_applied = False
        self._workers: List[FirstFrameDecodeWorker] = []
        self._selfcheck: Optional[GLSelfCheck] = None
        self._view_info = ""
        self._file_info = ""
        self._build_ui()
        self._load_test_pattern()

    # ── 화면 구성 ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._view = ConfirmGLView()
        self._view.gl_ready.connect(self._on_view_ready)
        self._view.gl_failed.connect(self._on_view_failed)
        root.addWidget(self._view, 1)

        side = QWidget()
        side.setFixedWidth(360)
        side.setStyleSheet(f"background: {theme.PANEL_BG};")
        col = QVBoxLayout(side)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(8)

        self._verdict = QLabel("확인하는 중…")
        self._verdict.setWordWrap(True)
        self._verdict.setStyleSheet(_VERDICT_STYLE)
        col.addWidget(self._verdict)

        self._report = QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setMinimumHeight(220)
        col.addWidget(self._report, 1)

        col.addWidget(self._caption("보는 판"))
        self._mode = QComboBox()
        self._mode.addItem("A", VIEW_MODE_A)
        self._mode.addItem("B (가운데 네모만 조금 밝음)", VIEW_MODE_B)
        self._mode.addItem("차이 (A − B)", VIEW_MODE_DIFF)
        self._mode.currentIndexChanged.connect(self._apply_view)
        col.addWidget(self._mode)

        col.addWidget(self._caption("채널"))
        self._channel = QComboBox()
        for label, ch in (
            ("RGB", CHANNEL_RGB),
            ("R", CHANNEL_R),
            ("G", CHANNEL_G),
            ("B", CHANNEL_B),
            ("밝기만", CHANNEL_LUMA),
        ):
            self._channel.addItem(label, ch)
        self._channel.currentIndexChanged.connect(self._apply_view)
        col.addWidget(self._channel)

        self._gain_label = self._caption("게인 1.00")
        col.addWidget(self._gain_label)
        self._gain = QSlider(Qt.Orientation.Horizontal)
        self._gain.setRange(-3 * _GAIN_STEPS_PER_STOP, 6 * _GAIN_STEPS_PER_STOP)
        self._gain.setValue(0)
        self._gain.valueChanged.connect(self._apply_view)
        col.addWidget(self._gain)

        self._gamma_label = self._caption("감마 1.00")
        col.addWidget(self._gamma_label)
        self._gamma = QSlider(Qt.Orientation.Horizontal)
        self._gamma.setRange(40, 300)
        self._gamma.setValue(_GAMMA_SCALE)
        self._gamma.valueChanged.connect(self._apply_view)
        col.addWidget(self._gamma)

        row = QHBoxLayout()
        reset = QPushButton("보기 원래대로")
        reset.clicked.connect(self._reset_view)
        row.addWidget(reset)
        again = QPushButton("다시 확인")
        again.clicked.connect(self._run_selfcheck)
        row.addWidget(again)
        col.addLayout(row)

        row2 = QHBoxLayout()
        open_btn = QPushButton("영상 파일 열기…")
        open_btn.clicked.connect(self._open_file)
        row2.addWidget(open_btn)
        pattern_btn = QPushButton("시험 그림으로")
        pattern_btn.clicked.connect(self._load_test_pattern)
        row2.addWidget(pattern_btn)
        col.addLayout(row2)

        copy_btn = QPushButton("결과 복사")
        copy_btn.clicked.connect(self._copy_report)
        col.addWidget(copy_btn)

        root.addWidget(side)

    @staticmethod
    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {theme.TEXT_LABEL};")
        return lbl

    # ── 보기 ────────────────────────────────────────────────────

    def _load_test_pattern(self) -> None:
        a = make_test_pattern(_PATTERN_W, _PATTERN_H)
        b = make_test_pattern(_PATTERN_W, _PATTERN_H, with_block=True)
        self._view.set_image(SLOT_A, a, _PATTERN_W, _PATTERN_H)
        self._view.set_image(SLOT_B, b, _PATTERN_W, _PATTERN_H)
        self._file_info = ""
        self._refresh_report()

    def _gain_value(self) -> float:
        return float(2.0 ** (self._gain.value() / _GAIN_STEPS_PER_STOP))

    def _gamma_value(self) -> float:
        return self._gamma.value() / _GAMMA_SCALE

    def _apply_view(self) -> None:
        gain, gamma = self._gain_value(), self._gamma_value()
        self._gain_label.setText(f"게인 {gain:.2f}")
        self._gamma_label.setText(f"감마 {gamma:.2f}")
        self._view.set_view(
            gain=gain,
            gamma=gamma,
            mode=int(self._mode.currentData()),
            channel=str(self._channel.currentData()),
        )

    def _reset_view(self) -> None:
        self._gain.setValue(0)
        self._gamma.setValue(_GAMMA_SCALE)
        self._mode.setCurrentIndex(0)
        self._channel.setCurrentIndex(0)

    # ── 확인 결과 ────────────────────────────────────────────────

    def _on_view_ready(self, info: str) -> None:
        self._view_info = f"화면: {info}"
        self._refresh_report()

    def _on_view_failed(self, info: str) -> None:
        self._view_info = f"화면을 켜지 못함: {info}"
        self._refresh_report()

    def _run_selfcheck(self) -> None:
        self._selfcheck = run_gl_selfcheck()
        logger.info(
            "confirm gl probe: ok=%s renderer=%s", self._selfcheck.ok, self._selfcheck.renderer
        )
        self._refresh_report()

    def report_text(self) -> str:
        """화면에 보이는 확인 결과 전체(복사용)."""
        import PySide6

        lines: List[str] = []
        sc = self._selfcheck
        if sc is None:
            lines.append("판정: 확인 전")
        elif sc.ok:
            lines.append("판정: 통과 — 이 PC 에서 컨펌 창 화면 계산이 됩니다")
        else:
            lines.append("판정: 실패 — 이 PC 에서는 컨펌 창 화면 계산이 안 됩니다")
        if sc is not None:
            lines.append(f"그래픽: {sc.renderer or '모름'}")
            lines.append(f"OpenGL: {sc.version or '모름'}")
            lines.extend(sc.lines)
        if self._view_info:
            lines.append(self._view_info)
        ffmpeg, ffprobe = resolve_ffmpeg(), resolve_ffprobe()
        lines.append(
            f"ffmpeg: {'있음' if ffmpeg else '없음'} · ffprobe: {'있음' if ffprobe else '없음'}"
        )
        if self._file_info:
            lines.append(self._file_info)
        frozen = "빌드된 exe" if getattr(sys, "frozen", False) else "개발 실행"
        lines.append(f"PySide6 {PySide6.__version__} · Python {sys.version.split()[0]} · {frozen}")
        return "\n".join(lines)

    def _refresh_report(self) -> None:
        text = self.report_text()
        self._report.setPlainText(text)
        sc = self._selfcheck
        if sc is None:
            self._verdict.setText("확인하는 중…")
            self._verdict.setStyleSheet(_VERDICT_STYLE)
        elif sc.ok:
            self._verdict.setText("통과 — 화면 계산이 됩니다")
            self._verdict.setStyleSheet(f"{_VERDICT_STYLE} color: {theme.SUCCESS};")
        else:
            self._verdict.setText("실패 — 화면 계산이 안 됩니다")
            self._verdict.setStyleSheet(f"{_VERDICT_STYLE} color: {theme.ERROR};")

    def _copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.report_text())

    # ── 영상 파일 ────────────────────────────────────────────────

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "영상 파일 고르기", "", _VIDEO_FILTER)
        if path:
            self.load_video_file(path)

    def load_video_file(self, path: str) -> None:
        """영상의 첫 프레임을 뒤에서 풀어 A·B 두 판에 올린다."""
        self._file_info = f"영상 푸는 중: {os.path.basename(path)}"
        self._refresh_report()
        w = FirstFrameDecodeWorker(path)
        name = os.path.basename(path)
        w.decoded.connect(
            lambda data, ww, hh, desc, n=name: self._on_decoded(n, data, ww, hh, desc)
        )
        w.failed.connect(lambda msg, n=name: self._on_decode_failed(n, msg))
        w.start()
        self._workers.append(w)

    def _on_decoded(self, name: str, data: bytes, width: int, height: int, desc: str) -> None:
        if self._closed:
            return
        self._view.set_image(SLOT_A, data, width, height)
        self._view.set_image(SLOT_B, data, width, height)
        self._file_info = f"영상: {name}\n  {desc}"
        self._refresh_report()

    def _on_decode_failed(self, name: str, msg: str) -> None:
        if self._closed:
            return
        self._file_info = f"영상을 열지 못함: {name}\n  {msg}"
        self._refresh_report()

    # ── 창 수명 ──────────────────────────────────────────────────

    def is_closed(self) -> bool:
        return self._closed

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._aumid_applied:
            self._aumid_applied = True
            if sys.platform == "win32":
                from bpe.core.windows_app_id import apply_app_user_model_id_to_hwnd

                apply_app_user_model_id_to_hwnd(int(self.winId()))
        if self._selfcheck is None:
            QTimer.singleShot(0, self._run_selfcheck)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closed = True
        for w in self._workers:
            w.stop()
        for w in self._workers:
            w.wait(_WORKER_WAIT_MS)
        self._workers.clear()
        super().closeEvent(event)
