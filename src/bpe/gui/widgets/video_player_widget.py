"""FFmpeg-based video preview with frame stepping (ProRes-friendly)."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from typing import Any, Optional, Tuple

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from bpe.core.logging import get_logger
from bpe.gui import theme
from bpe.gui.widgets.annotation_overlay import AnnotationOverlay

logger = get_logger("gui.widgets.video_player_widget")


def _find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _find_ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def probe_video(path: str) -> Tuple[float, int, int, int]:
    """Return (fps, total_frames, width, height). fps/frame count are best-effort."""
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return 24.0, 1, 640, 360
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            return 24.0, 1, 640, 360
        data = json.loads(proc.stdout)
    except Exception as exc:
        logger.debug("ffprobe failed: %s", exc)
        return 24.0, 1, 640, 360

    streams = data.get("streams") or []
    st = streams[0] if streams else {}
    w = int(st.get("width") or 640)
    h = int(st.get("height") or 360)

    def _parse_rate(s: Any) -> float:
        if not s or not isinstance(s, str):
            return 0.0
        s = s.strip()
        if "/" in s:
            a, b = s.split("/", 1)
            try:
                return float(a) / max(float(b), 1e-9)
            except ValueError:
                return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    fps = _parse_rate(st.get("r_frame_rate")) or _parse_rate(st.get("avg_frame_rate")) or 24.0
    nb = st.get("nb_frames")
    total = 0
    if nb is not None:
        try:
            total = int(str(nb).strip())
        except ValueError:
            total = 0
    if total <= 0:
        fmt = data.get("format") or {}
        dur_s = fmt.get("duration")
        try:
            d = float(dur_s)
        except (TypeError, ValueError):
            d = 0.0
        total = max(1, int(round(d * fps))) if d > 0 and fps > 0 else 1

    return max(fps, 0.001), max(1, total), max(1, w), max(1, h)


def extract_frame_png(path: str, frame_index: int, fps: float) -> Optional[bytes]:
    """Decode a single frame as PNG bytes via ffmpeg."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    t = float(frame_index) / max(float(fps), 0.001)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{t:.6f}",
        "-i",
        path,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-an",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if proc.returncode != 0 or len(proc.stdout) < 32:
            return None
        return proc.stdout
    except Exception as exc:
        logger.debug("ffmpeg frame extract failed: %s", exc)
        return None


class _DecodeThread(QThread):
    """One-shot PNG decode for *frame_index*."""

    done = Signal(int, object)  # frame_index, QPixmap or None

    def __init__(self, path: str, frame_index: int, fps: float) -> None:
        super().__init__()
        self._path = path
        self._frame_index = frame_index
        self._fps = fps

    def run(self) -> None:
        data = extract_frame_png(self._path, self._frame_index, self._fps)
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.done.emit(self._frame_index, pm)
        else:
            self.done.emit(self._frame_index, None)


class VideoPlayerWidget(QWidget):
    """Frame-accurate stepping with Left/Right; slider scrubs by frame index."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = ""
        self._fps = 24.0
        self._total_frames = 1
        self._current_frame = 0
        self._native_w = 640
        self._native_h = 360
        self._raw_pixmap: Optional[QPixmap] = None
        self._playing = False
        self._scrub_active = False
        self._was_playing_before_scrub = False
        self._seq = 0
        self._decode_thread: Optional[_DecodeThread] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_play_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._host = QWidget()
        self._host.setMinimumHeight(280)
        self._host.setStyleSheet(f"background-color: {theme.BORDER}; border-radius: 4px;")
        root.addWidget(self._host, 1)

        self._display = QLabel(self._host)
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setScaledContents(False)
        self._display.setText("영상 없음")

        self._overlay = AnnotationOverlay(self._host)

        ctl = QHBoxLayout()
        self._play_btn = QPushButton("재생")
        self._play_btn.setFixedWidth(72)
        self._play_btn.clicked.connect(self._toggle_play)
        ctl.addWidget(self._play_btn)

        self._info_lbl = QLabel("—")
        self._info_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
        ctl.addWidget(self._info_lbl, 1)
        root.addLayout(ctl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.valueChanged.connect(self._on_slider_value_changed_user)
        root.addWidget(self._slider)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def annotation_overlay(self) -> AnnotationOverlay:
        return self._overlay

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = self._host.width()
        h = self._host.height()
        self._display.setGeometry(0, 0, w, h)
        self._overlay.setGeometry(0, 0, w, h)
        self._apply_scaled_pixmap()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        k = event.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._pause()
            self._seek_frame(self._current_frame + 1)
            event.accept()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._pause()
            self._seek_frame(self._current_frame - 1)
            event.accept()
            return
        if k == Qt.Key.Key_Space:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def load_mov(self, path: str) -> bool:
        """Load a movie file; returns False if ffmpeg missing or probe fails."""
        self._pause()
        self._path = (path or "").strip()
        self._overlay.clear_all()
        if not self._path:
            self._display.setText("경로 없음")
            self._slider.setMaximum(0)
            return False
        if not _find_ffmpeg() or not _find_ffprobe():
            self._display.setText("ffmpeg/ffprobe를 PATH에 설치하세요")
            self._slider.setMaximum(0)
            return False
        self._fps, self._total_frames, self._native_w, self._native_h = probe_video(self._path)
        self._slider.blockSignals(True)
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(0, self._total_frames - 1))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._current_frame = 0
        self._seek_frame(0, force=True)
        return True

    def clear(self) -> None:
        self._pause()
        self._path = ""
        self._raw_pixmap = None
        self._display.clear()
        self._display.setText("영상 없음")
        self._slider.setMaximum(0)
        self._overlay.clear_all()

    def capture_annotated_png_bytes(self) -> Optional[bytes]:
        """Composite current frame + overlay; returns PNG bytes."""
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return None
        w = self._display.width()
        h = self._display.height()
        if w < 2 or h < 2:
            return None
        scaled = self._raw_pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        ox = (w - scaled.width()) // 2
        oy = (h - scaled.height()) // 2
        comp = QPixmap(w, h)
        comp.fill(Qt.GlobalColor.black)
        painter = QPainter(comp)
        painter.drawPixmap(ox, oy, scaled)
        if self._overlay.has_content():
            ann = self._overlay.render_to_pixmap(QSize(w, h))
            painter.drawPixmap(0, 0, ann)
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        comp.save(buf, "PNG")
        data = bytes(buf.data())
        return data if data else None

    def _pause(self) -> None:
        self._playing = False
        self._timer.stop()
        self._play_btn.setText("재생")

    def _toggle_play(self) -> None:
        if not self._path:
            return
        self._playing = not self._playing
        if self._playing:
            ms = int(max(1, round(1000.0 / self._fps)))
            self._timer.start(ms)
            self._play_btn.setText("일시정지")
        else:
            self._timer.stop()
            self._play_btn.setText("재생")

    def _on_play_tick(self) -> None:
        if self._current_frame >= self._total_frames - 1:
            self._pause()
            return
        self._seek_frame(self._current_frame + 1)

    def _on_slider_pressed(self) -> None:
        self._scrub_active = True
        self._was_playing_before_scrub = self._playing
        self._pause()

    def _on_slider_moved(self, value: int) -> None:
        if self._scrub_active:
            self._seek_frame(int(value), force=True)

    def _on_slider_released(self) -> None:
        self._scrub_active = False
        if self._was_playing_before_scrub:
            self._toggle_play()
        self._was_playing_before_scrub = False

    def _on_slider_value_changed_user(self, value: int) -> None:
        """Click-to-jump on the slider track (when not dragging — handled in moved)."""
        if self._scrub_active:
            return
        if self._slider.signalsBlocked():
            return
        self._seek_frame(int(value), force=True)

    def _seek_frame(self, idx: int, *, force: bool = False) -> None:
        if not self._path:
            return
        idx = max(0, min(int(idx), self._total_frames - 1))
        if idx == self._current_frame and not force and self._raw_pixmap is not None:
            return
        self._current_frame = idx
        self._slider.blockSignals(True)
        self._slider.setValue(idx)
        self._slider.blockSignals(False)
        self._seq += 1
        seq = self._seq
        th = _DecodeThread(self._path, idx, self._fps)

        def _on_done(fi: int, pm: object) -> None:
            if seq != self._seq:
                return
            if pm is not None and isinstance(pm, QPixmap) and not pm.isNull():
                self._raw_pixmap = pm
                self._apply_scaled_pixmap()
            else:
                self._display.setText("프레임 디코딩 실패")
            tc = self._frame_timecode(idx)
            self._info_lbl.setText(f"{tc}  ·  프레임 {idx + 1}/{self._total_frames}")

        th.done.connect(_on_done)
        th.finished.connect(th.deleteLater)
        th.start()
        self._decode_thread = th

    def _frame_timecode(self, idx: int) -> str:
        secs = idx / max(self._fps, 0.001)
        s = int(math.floor(secs))
        ms = int(round((secs - s) * 1000))
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"

    def _apply_scaled_pixmap(self) -> None:
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return
        w = self._display.width()
        h = self._display.height()
        if w < 2 or h < 2:
            return
        scaled = self._raw_pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._display.setPixmap(scaled)
        self._display.setText("")
