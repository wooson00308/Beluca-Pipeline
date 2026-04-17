"""Feedback video preview: Qt Multimedia smooth playback, FFmpeg frame fallback."""

from __future__ import annotations

import json
import math
import subprocess
from enum import IntEnum
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QEventLoop,
    QIODevice,
    QObject,
    QPointF,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.feedback_file_log import append_feedback_log
from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.win_subprocess import no_console_subprocess_kwargs
from bpe.gui import theme
from bpe.gui.feedback_panel_png import (
    FEEDBACK_MEDIA_CTL_ICON_PX,
    FEEDBACK_PANEL_ICON_PX,
    beluca_placeholder_logo_path,
    load_feedback_panel_icon,
)
from bpe.gui.feedback_tool_icons import (
    make_media_pause_icon,
    make_media_play_icon,
)
from bpe.gui.widgets.annotation_overlay import AnnotationOverlay, AnnotationTool

logger = get_logger("gui.widgets.video_player_widget")


def _feedback_logo_pixmap_transparent_bg(src: QPixmap) -> QPixmap:
    """검정·거의 검정 배경을 알파로 제거해 글자만 남긴다 (불투명 PNG 대비)."""
    if src.isNull():
        return src
    img = src.toImage()
    if img.isNull():
        return src
    fmt = QImage.Format.Format_ARGB32
    if img.format() != fmt:
        img = img.convertToFormat(fmt)
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = QColor(img.pixel(x, y))
            if c.alpha() == 0:
                continue
            if c.red() < 28 and c.green() < 28 and c.blue() < 28:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    out = QPixmap.fromImage(img)
    return out if not out.isNull() else src


_GESTURE_CLICK_PX = 10.0
_ZOOM_DRAG_SENS = 0.007


class _PreviewMode(IntEnum):
    NONE = 0
    MEDIA = 1
    FFMPEG_FRAMES = 2


def probe_video(path: str) -> Tuple[float, int, int, int]:
    """Return (fps, total_frames, width, height). fps/frame count are best-effort."""
    ffprobe = resolve_ffprobe()
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
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **no_console_subprocess_kwargs(),
        )
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
    """Decode a single frame as PNG bytes via ffmpeg (0-based frame index).

    ``-ss`` is placed **after** ``-i`` so the extracted frame matches that index
    more closely than a fast seek before input (important for feedback captures).
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    t = float(frame_index) / max(float(fps), 0.001)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-ss",
        f"{max(0.0, t):.6f}",
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
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            check=False,
            **no_console_subprocess_kwargs(),
        )
        if proc.returncode != 0 or len(proc.stdout) < 32:
            return None
        return proc.stdout
    except Exception as exc:
        logger.debug("ffmpeg frame extract failed: %s", exc)
        return None


def extract_frame_png_at_time(path: str, t_sec: float) -> Optional[bytes]:
    """Decode one frame at *t_sec* as PNG via ffmpeg."""
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, float(t_sec)):.6f}",
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
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            check=False,
            **no_console_subprocess_kwargs(),
        )
        if proc.returncode != 0 or len(proc.stdout) < 32:
            return None
        return proc.stdout
    except Exception as exc:
        logger.debug("ffmpeg frame extract failed: %s", exc)
        return None


class _DecodeThread(QThread):
    done = Signal(int, object)

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


class _ExtractPngBytesThread(QThread):
    """Run ``extract_frame_png`` off the GUI thread; subprocess stays out of the event loop."""

    done = Signal(object)

    def __init__(self, path: str, frame_index: int, fps: float) -> None:
        super().__init__()
        self._path = path
        self._frame_index = frame_index
        self._fps = fps

    def run(self) -> None:
        self.done.emit(extract_frame_png(self._path, self._frame_index, self._fps))


class VideoPlayerWidget(QWidget):
    """QMediaPlayer + QVideoSink QLabel preview with AnnotationOverlay; FFmpeg fallback."""

    frame_index_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = ""
        self._fps = 24.0
        self._total_frames = 1
        self._native_w = 640
        self._native_h = 360
        self._raw_pixmap: Optional[QPixmap] = None
        self._playing = False
        self._scrub_active = False
        self._was_playing_before_scrub = False
        self._decode_target = 0
        self._decode_busy = False
        self._decode_thread: Optional[_DecodeThread] = None
        self._displayed_frame = 0
        self._preview_mode = _PreviewMode.NONE
        self._slider_is_ms = False
        self._slider_block_position = False
        self._loop_enabled = True
        self._view_zoom = 1.0
        self._view_pan_x = 0.0
        self._view_pan_y = 0.0
        self._clip_footer_text = ""
        self._feedback_frame_start = 1001
        self._last_emitted_frame_idx: Optional[int] = None

        self._ctrl_zoom_drag = False
        self._alt_pan_active = False
        self._alt_pan_last_global = QPointF()
        self._gesture_last_global_y = 0.0
        self._video_gesture_mode: Optional[str] = None
        self._video_gesture_press_global: Optional[QPointF] = None
        self._video_scrub_anchor_x = 0.0
        self._slider_scrub_origin_value = 0
        self._was_playing_before_video_scrub = False
        self._pending_media_scrub_ms: Optional[int] = None
        self._pending_ffmpeg_scrub_idx: Optional[int] = None
        self._scrub_coalesce_timer = QTimer(self)
        self._scrub_coalesce_timer.setInterval(16)
        self._scrub_coalesce_timer.timeout.connect(self._apply_coalesced_scrub)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(1.0)
        self._player.setAudioOutput(self._audio)
        self._video_sink = QVideoSink(self)
        self._video_sink.videoFrameChanged.connect(self._on_sink_video_frame)
        self._player.errorOccurred.connect(self._on_media_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.durationChanged.connect(self._on_media_duration_changed)
        self._player.positionChanged.connect(self._on_media_position_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._host = QWidget()
        self._host.setMinimumHeight(280)
        self._host.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._host.setStyleSheet(f"background-color: {theme.BORDER}; border-radius: 4px;")
        root.addWidget(self._host, 1)

        self._display = QLabel(self._host)
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setScaledContents(False)
        self._display.setText("영상 없음")

        self._feedback_project_selected = False
        self._placeholder_logo_src = QPixmap()
        _logo_p = beluca_placeholder_logo_path()
        if _logo_p.is_file():
            raw = QPixmap(str(_logo_p))
            if not raw.isNull():
                self._placeholder_logo_src = _feedback_logo_pixmap_transparent_bg(raw)
        self._placeholder_logo = QLabel(self._host)
        self._placeholder_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._placeholder_logo.setAutoFillBackground(False)
        self._placeholder_logo.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._placeholder_logo.setStyleSheet("background: transparent; border: none;")
        self._placeholder_logo.setContentsMargins(0, 0, 0, 0)
        self._placeholder_logo.setVisible(False)
        self._placeholder_opacity_fx = QGraphicsOpacityEffect(self._placeholder_logo)
        # 프로젝트 미선택 시 로고는 선명하게(100%)
        self._placeholder_opacity_fx.setOpacity(1.0)
        self._placeholder_logo.setGraphicsEffect(self._placeholder_opacity_fx)

        self._overlay = AnnotationOverlay(self._host)

        self._display.installEventFilter(self)
        self._host.installEventFilter(self)
        self._overlay.installEventFilter(self)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setTracking(True)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.valueChanged.connect(self._on_slider_value_changed_user)
        root.addWidget(self._slider)

        ctl = QHBoxLayout()
        ctl.setSpacing(8)

        self._clip_footer = QLabel("")
        self._clip_footer.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; border: none;")
        self._clip_footer.setMinimumWidth(120)
        self._clip_footer.setWordWrap(False)

        _ctl_icon_px = FEEDBACK_MEDIA_CTL_ICON_PX
        _ic = QColor(theme.TEXT)
        _ctl_btn = max(28, round(40 / 1.2))
        self._play_btn = QToolButton()
        self._play_btn.setAutoRaise(True)
        self._play_btn.setIcon(make_media_play_icon(_ctl_icon_px, _ic))
        self._play_btn.setIconSize(QSize(_ctl_icon_px, _ctl_icon_px))
        self._play_btn.setToolTip("재생/일시정지")
        self._play_btn.setFixedSize(_ctl_btn, _ctl_btn)
        self._play_btn.setStyleSheet(
            "QToolButton { background: transparent; border: none; padding: 4px; }\n"
            "QToolButton:hover { background-color: rgba(255,255,255,24); border-radius: 4px; }\n"
            "QToolButton:pressed { background-color: rgba(255,255,255,40); }"
        )
        self._play_btn.clicked.connect(self._toggle_play)

        self._info_lbl = QLabel("—")
        self._info_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14px; border: none; font-weight: 500;"
        )

        self._btn_loop = QToolButton()
        self._btn_loop.setCheckable(True)
        self._btn_loop.setAutoRaise(True)
        self._btn_loop.setIcon(load_feedback_panel_icon("feedback_loop", FEEDBACK_PANEL_ICON_PX))
        self._btn_loop.setIconSize(QSize(FEEDBACK_PANEL_ICON_PX, FEEDBACK_PANEL_ICON_PX))
        self._btn_loop.setToolTip("반복 재생")
        _side_ctl = max(36, round(50 / 1.2))
        self._btn_loop.setFixedSize(_side_ctl, _side_ctl)
        self._btn_loop.setChecked(True)
        self._btn_loop.toggled.connect(self._on_loop_toggled)
        _ico_fx = QGraphicsOpacityEffect(self._btn_loop)
        _ico_fx.setOpacity(0.8)
        self._btn_loop.setGraphicsEffect(_ico_fx)

        _fit_icon_px = max(16, FEEDBACK_PANEL_ICON_PX - 2)
        _fit_side = max(28, _side_ctl - 2)
        self._btn_zoom_reset = QToolButton()
        self._btn_zoom_reset.setIcon(load_feedback_panel_icon("feedback_fit", _fit_icon_px))
        self._btn_zoom_reset.setIconSize(QSize(_fit_icon_px, _fit_icon_px))
        self._btn_zoom_reset.setAutoRaise(True)
        self._btn_zoom_reset.setFixedSize(_fit_side, _fit_side)
        self._btn_zoom_reset.setToolTip("확대/축소 초기화 (Ctrl+드래그로 조절)")
        self._btn_zoom_reset.clicked.connect(self._reset_view_zoom)
        _fit_fx = QGraphicsOpacityEffect(self._btn_zoom_reset)
        _fit_fx.setOpacity(0.8)
        self._btn_zoom_reset.setGraphicsEffect(_fit_fx)

        ctl.addWidget(self._clip_footer, 0)
        center_play = QHBoxLayout()
        center_play.setSpacing(10)
        center_play.addStretch(1)
        mid = QHBoxLayout()
        mid.setSpacing(10)
        mid.addWidget(self._play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        mid.addWidget(self._info_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        center_play.addLayout(mid)
        center_play.addStretch(1)
        ctl.addLayout(center_play, 1)
        ctl_right = QHBoxLayout()
        ctl_right.setSpacing(6)
        ctl_right.addWidget(self._btn_loop)
        ctl_right.addWidget(self._btn_zoom_reset)
        ctl.addLayout(ctl_right, 0)

        root.addLayout(ctl)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_feedback_project_selected(False)

    def set_feedback_project_selected(self, selected: bool) -> None:
        """프로젝트 미선택 시 슬라이더(얇은 트랙 선) 숨김 + 중앙 로고 표시."""
        self._feedback_project_selected = bool(selected)
        self._slider.setVisible(self._feedback_project_selected)
        show_logo = (not self._feedback_project_selected) and (
            not self._placeholder_logo_src.isNull()
        )
        self._placeholder_logo.setVisible(show_logo)
        if show_logo:
            self._placeholder_opacity_fx.setOpacity(1.0)
        self._apply_idle_display_message()
        if show_logo:
            self._update_placeholder_logo_scale()
        self._display.raise_()
        if show_logo:
            self._placeholder_logo.raise_()
        self._overlay.raise_()

    def _apply_idle_display_message(self) -> None:
        """경로 없을 때 플레이스홀더/문구 — 프로젝트 미선택이면 빈 영역(로고만)."""
        if self._path:
            return
        if self._preview_mode != _PreviewMode.NONE:
            return
        if not self._feedback_project_selected:
            self._display.clear()
            self._display.setText("")
        else:
            self._display.setText("영상 없음")

    def _update_placeholder_logo_scale(self) -> None:
        if self._placeholder_logo_src.isNull():
            return
        w = max(1, self._host.width())
        h = max(1, self._host.height())
        max_side_w = max(120, int(w * 0.5))
        max_side_h = max(100, int(h * 0.42))
        pm = self._placeholder_logo_src.scaled(
            max_side_w,
            max_side_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._placeholder_logo.setPixmap(pm)
        self._placeholder_logo.setGeometry(0, 0, w, h)

    @property
    def annotation_overlay(self) -> AnnotationOverlay:
        return self._overlay

    def set_feedback_frame_start(self, start: int) -> None:
        """MOV index 0 is shown as *start* (e.g. 1001)."""
        self._feedback_frame_start = max(0, int(start))

    def current_frame_index(self) -> int:
        """0-based frame index within the file (FFmpeg mode exact; media mode approximate)."""
        if self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            return int(self._displayed_frame)
        if self._preview_mode == _PreviewMode.MEDIA and self._path and self._total_frames > 0:
            pos_ms = int(self._player.position())
            fi = int(round((pos_ms / 1000.0) * self._fps))
            return max(0, min(fi, self._total_frames - 1))
        return 0

    def wait_for_frame_displayed(self, target_idx: int, timeout_ms: int = 45000) -> bool:
        """Block until frame *target_idx* is shown (FFmpeg or Qt media). Main thread only."""
        if not self._path or self._preview_mode not in (
            _PreviewMode.FFMPEG_FRAMES,
            _PreviewMode.MEDIA,
        ):
            return False
        t = max(0, min(int(target_idx), self._total_frames - 1))

        if self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            if (
                self._displayed_frame == t
                and self._raw_pixmap is not None
                and not self._raw_pixmap.isNull()
                and not self._decode_busy
            ):
                return True
            loop = QEventLoop(self)
            timer = QTimer(self)
            timer.setSingleShot(True)

            def on_done() -> None:
                loop.quit()

            def on_frame(fi: int) -> None:
                if fi == t and not self._decode_busy:
                    loop.quit()

            timer.timeout.connect(on_done)
            self.frame_index_changed.connect(on_frame)
            self._seek_frame(t, force=True)
            timer.start(timeout_ms)
            loop.exec()
            timer.stop()
            try:
                self.frame_index_changed.disconnect(on_frame)
            except TypeError:
                pass
            return (
                self._displayed_frame == t
                and self._raw_pixmap is not None
                and not self._raw_pixmap.isNull()
            )

        # MEDIA: seek to snapped time and wait until reported frame index matches.
        self._player.pause()
        pos_ms = self._position_ms_for_frame_index(t)
        if self.current_frame_index() == t and int(self._player.position()) == pos_ms:
            return self._raw_pixmap is not None and not self._raw_pixmap.isNull()
        loop = QEventLoop(self)
        timer = QTimer(self)
        timer.setSingleShot(True)

        def on_done() -> None:
            loop.quit()

        def on_frame(fi: int) -> None:
            if fi == t:
                loop.quit()

        timer.timeout.connect(on_done)
        self.frame_index_changed.connect(on_frame)
        self._slider_block_position = True
        self._player.setPosition(pos_ms)
        self._slider.blockSignals(True)
        self._slider.setValue(pos_ms)
        self._slider.blockSignals(False)
        self._slider_block_position = False
        self._info_lbl.setText(self._info_label_media(pos_ms))
        timer.start(timeout_ms)
        loop.exec()
        timer.stop()
        try:
            self.frame_index_changed.disconnect(on_frame)
        except TypeError:
            pass
        ok_idx = self.current_frame_index() == t
        ok_pix = self._raw_pixmap is not None and not self._raw_pixmap.isNull()
        return ok_idx and ok_pix

    def _position_ms_for_frame_index(self, idx: int) -> int:
        if self._preview_mode != _PreviewMode.MEDIA or self._fps <= 0.001:
            return 0
        raw_ms = int(round(float(idx) * 1000.0 / float(self._fps)))
        return self._snap_position_ms_to_frame(raw_ms)

    def _emit_frame_index_if_changed(self, idx: int) -> None:
        if self._last_emitted_frame_idx != idx:
            self._last_emitted_frame_idx = idx
            self.frame_index_changed.emit(int(idx))

    def _info_label_ffmpeg(self, result_fi: int) -> str:
        tc = self._frame_timecode(result_fi)
        df = self._feedback_frame_start + int(result_fi)
        dmax = self._feedback_frame_start + self._total_frames - 1
        return f"{tc}  ·  프레임 {df}/{dmax}"

    def _info_label_media(self, pos_ms: int) -> str:
        base = self._format_ms_label(pos_ms)
        if self._total_frames <= 0:
            return base
        fi = self.current_frame_index()
        df = self._feedback_frame_start + fi
        dmax = self._feedback_frame_start + self._total_frames - 1
        return f"{base}  ·  프레임 {df}/{dmax}"

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            me = event
            if not isinstance(me, QMouseEvent):
                return False
            if me.button() != Qt.MouseButton.LeftButton:
                return False
            if me.modifiers() & Qt.KeyboardModifier.AltModifier:
                if watched in (self._display, self._host, self._overlay):
                    return self._begin_alt_pan(me)
                return False
            if me.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if watched in (self._display, self._host, self._overlay):
                    self._begin_ctrl_zoom(float(me.globalPosition().y()))
                    return True
                return False
            if watched == self._display and self._overlay.tool == AnnotationTool.NONE:
                return self._begin_surface_gesture(me)
            return False
        return False

    def _begin_ctrl_zoom(self, global_y: float) -> None:
        self._end_gesture_only_release_grab()
        self._ctrl_zoom_drag = True
        self._gesture_last_global_y = global_y
        self.grabMouse()

    def _begin_alt_pan(self, me: QMouseEvent) -> bool:
        if not self._path or self._preview_mode == _PreviewMode.NONE:
            return False
        self._end_gesture_only_release_grab()
        self._alt_pan_active = True
        self._alt_pan_last_global = QPointF(me.globalPosition())
        self.grabMouse()
        return True

    def _begin_surface_gesture(self, me: QMouseEvent) -> bool:
        if not self._path or self._preview_mode == _PreviewMode.NONE:
            return False
        self._end_gesture_only_release_grab()
        self._scrub_coalesce_timer.stop()
        self._pending_media_scrub_ms = None
        self._pending_ffmpeg_scrub_idx = None
        self._video_gesture_mode = "undecided"
        self._video_gesture_press_global = QPointF(me.globalPosition())
        self._slider_scrub_origin_value = self._slider.value()
        self._was_playing_before_video_scrub = self._playing or (
            self._preview_mode == _PreviewMode.MEDIA
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.grabMouse()
        return True

    def _end_gesture_only_release_grab(self) -> None:
        self._ctrl_zoom_drag = False
        self._alt_pan_active = False
        self._video_gesture_mode = None
        self._video_gesture_press_global = None
        if QWidget.mouseGrabber() == self:
            self.releaseMouse()

    @staticmethod
    def _click_dist_qpf(a: QPointF, b: QPointF) -> float:
        return float(math.hypot(a.x() - b.x(), a.y() - b.y()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._alt_pan_active:
            g = QPointF(event.globalPosition())
            dx = float(g.x() - self._alt_pan_last_global.x())
            dy = float(g.y() - self._alt_pan_last_global.y())
            self._alt_pan_last_global = g
            self._view_pan_x += dx
            self._view_pan_y += dy
            self._apply_scaled_pixmap()
            return
        if self._ctrl_zoom_drag:
            dy = float(event.globalPosition().y()) - self._gesture_last_global_y
            self._gesture_last_global_y = float(event.globalPosition().y())
            self._bump_zoom_from_delta(dy)
            return
        if self._video_gesture_mode == "undecided" and self._video_gesture_press_global is not None:
            d = self._click_dist_qpf(self._video_gesture_press_global, event.globalPosition())
            if d > _GESTURE_CLICK_PX:
                self._video_gesture_mode = "scrub"
                lp = self._display.mapFrom(self, event.position().toPoint())
                self._video_scrub_anchor_x = float(lp.x())
                self._slider_scrub_origin_value = self._slider.value()
                if self._preview_mode == _PreviewMode.MEDIA:
                    self._player.pause()
                self._playing = False
                self._play_btn.setIcon(
                    make_media_play_icon(FEEDBACK_MEDIA_CTL_ICON_PX, QColor(theme.TEXT))
                )
            return
        if self._video_gesture_mode == "scrub":
            lp = self._display.mapFrom(self, event.position().toPoint())
            dx = float(lp.x()) - self._video_scrub_anchor_x
            self._apply_surface_scrub_dx(dx)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._alt_pan_active:
            self._alt_pan_active = False
            if QWidget.mouseGrabber() == self:
                self.releaseMouse()
            return
        if self._ctrl_zoom_drag:
            self._ctrl_zoom_drag = False
            if QWidget.mouseGrabber() == self:
                self.releaseMouse()
            return
        if self._video_gesture_mode == "undecided" and self._video_gesture_press_global is not None:
            d = self._click_dist_qpf(self._video_gesture_press_global, event.globalPosition())
            if d <= _GESTURE_CLICK_PX:
                self._toggle_play()
            self._video_gesture_mode = None
            self._video_gesture_press_global = None
            if QWidget.mouseGrabber() == self:
                self.releaseMouse()
            return
        if self._video_gesture_mode == "scrub":
            self._flush_scrub_coalesce()
            self._video_gesture_mode = None
            self._video_gesture_press_global = None
            if QWidget.mouseGrabber() == self:
                self.releaseMouse()
            if self._was_playing_before_video_scrub:
                if self._preview_mode == _PreviewMode.MEDIA:
                    self._player.play()
                elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
                    self._playing = True
                    self._play_btn.setIcon(
                        make_media_pause_icon(FEEDBACK_MEDIA_CTL_ICON_PX, QColor(theme.TEXT))
                    )
                    self._queue_next_play_frame()
            self._was_playing_before_video_scrub = False
            return
        super().mouseReleaseEvent(event)

    def _bump_zoom_from_delta(self, dy: float) -> None:
        factor = 1.0 + (-dy) * _ZOOM_DRAG_SENS
        factor = max(0.25, min(4.0, factor))
        self._view_zoom = max(0.25, min(4.0, self._view_zoom * factor))
        self._apply_scaled_pixmap()

    def _snap_position_ms_to_frame(self, ms: int) -> int:
        """Qt 미디어 스크럽 시 슬라이더·프레임이 어긋나 보이지 않도록 fps 기준으로 ms를 맞춘다."""
        if self._preview_mode != _PreviewMode.MEDIA or self._fps <= 0.001:
            return int(ms)
        dur = int(self._player.duration())
        if dur <= 0:
            return int(ms)
        fr_ms = 1000.0 / float(self._fps)
        snapped = int(round(float(ms) / fr_ms) * fr_ms)
        return max(0, min(dur, snapped))

    def _arm_scrub_coalesce(self) -> None:
        if not self._scrub_coalesce_timer.isActive():
            self._scrub_coalesce_timer.start()

    def _apply_coalesced_scrub(self) -> None:
        if self._preview_mode == _PreviewMode.MEDIA:
            if self._pending_media_scrub_ms is None:
                self._scrub_coalesce_timer.stop()
                return
            p = int(self._pending_media_scrub_ms)
            self._pending_media_scrub_ms = None
            self._player.setPosition(p)
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            if self._pending_ffmpeg_scrub_idx is None:
                self._scrub_coalesce_timer.stop()
                return
            idx = int(self._pending_ffmpeg_scrub_idx)
            self._pending_ffmpeg_scrub_idx = None
            self._seek_frame(idx, force=True)
        else:
            self._scrub_coalesce_timer.stop()

    def _flush_scrub_coalesce(self) -> None:
        self._scrub_coalesce_timer.stop()
        if self._preview_mode == _PreviewMode.MEDIA and self._pending_media_scrub_ms is not None:
            p = int(self._pending_media_scrub_ms)
            self._pending_media_scrub_ms = None
            self._player.setPosition(p)
        elif (
            self._preview_mode == _PreviewMode.FFMPEG_FRAMES
            and self._pending_ffmpeg_scrub_idx is not None
        ):
            idx = int(self._pending_ffmpeg_scrub_idx)
            self._pending_ffmpeg_scrub_idx = None
            self._seek_frame(idx, force=True)

    def _apply_surface_scrub_dx(self, dx: float) -> None:
        w = max(float(self._display.width()), 200.0)
        if self._preview_mode == _PreviewMode.MEDIA:
            dur = max(1, self._slider.maximum())
            delta = int(dx / w * dur)
            nv = max(0, min(dur, self._slider_scrub_origin_value + delta))
            nv = self._snap_position_ms_to_frame(nv)
            self._slider_block_position = True
            self._player.pause()
            self._slider.blockSignals(True)
            self._slider.setValue(nv)
            self._slider.blockSignals(False)
            self._slider_block_position = False
            self._info_lbl.setText(self._info_label_media(int(nv)))
            self._pending_media_scrub_ms = int(nv)
            self._arm_scrub_coalesce()
            fi = max(
                0,
                min(int(round((nv / 1000.0) * self._fps)), max(0, self._total_frames - 1)),
            )
            self._emit_frame_index_if_changed(fi)
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            tf = max(0, self._total_frames - 1)
            delta_f = int(dx / w * max(1, tf))
            nv = max(0, min(tf, self._slider_scrub_origin_value + delta_f))
            self._slider.blockSignals(True)
            self._slider.setValue(nv)
            self._slider.blockSignals(False)
            self._info_lbl.setText(self._info_label_ffmpeg(int(nv)))
            self._pending_ffmpeg_scrub_idx = int(nv)
            self._arm_scrub_coalesce()
            self._emit_frame_index_if_changed(int(nv))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = self._host.width()
        h = self._host.height()
        self._display.setGeometry(0, 0, w, h)
        self._overlay.setGeometry(0, 0, w, h)
        if self._placeholder_logo.isVisible():
            self._update_placeholder_logo_scale()
        self._display.raise_()
        if self._placeholder_logo.isVisible():
            self._placeholder_logo.raise_()
        self._overlay.raise_()
        if self._preview_mode in (_PreviewMode.FFMPEG_FRAMES, _PreviewMode.MEDIA):
            self._apply_scaled_pixmap()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        k = event.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._pause()
            self._seek_step(1)
            event.accept()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._pause()
            self._seek_step(-1)
            event.accept()
            return
        if k == Qt.Key.Key_Space:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def _seek_step(self, direction: int) -> None:
        if self._preview_mode == _PreviewMode.MEDIA:
            dur = max(1, int(self._player.duration()))
            delta = max(1, int(round(1000.0 / max(self._fps, 0.001))))
            p = int(self._player.position()) + direction * delta
            self._player.setPosition(max(0, min(p, dur)))
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            self._seek_frame(self._displayed_frame + direction, force=True)

    def load_mov(self, path: str) -> bool:
        self._pause()
        self._stop_media()
        self._path = normalize_path_str((path or "").strip())
        self._last_emitted_frame_idx = None
        self._overlay.clear_all()
        self._raw_pixmap = None
        self._display.clear()
        self._preview_mode = _PreviewMode.NONE
        self._slider_is_ms = False
        append_feedback_log("load_mov_start", path_len=len(self._path))
        self._view_zoom = 1.0
        self._view_pan_x = 0.0
        self._view_pan_y = 0.0
        if not self._path:
            self._display.setText("경로 없음")
            self._slider.setMaximum(0)
            append_feedback_log("load_mov_fail", reason="empty_path")
            return False
        if not Path(self._path).is_file():
            self._display.setText("파일 없음")
            append_feedback_log("load_mov_fail", reason="not_file")
            return False

        self._display.show()
        self._display.setText("로딩…")
        self._player.setVideoOutput(self._video_sink)
        url = QUrl.fromLocalFile(self._path)
        self._player.setSource(url)
        append_feedback_log("media_set_source")
        return True

    def _stop_media(self) -> None:
        self._player.stop()
        try:
            self._player.setVideoOutput(None)
        except Exception:
            pass
        self._player.setSource(QUrl())

    def _on_sink_video_frame(self, frame: QVideoFrame) -> None:
        if self._preview_mode != _PreviewMode.MEDIA:
            return
        if not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            return
        self._raw_pixmap = pm
        self._apply_scaled_pixmap()

    def _on_media_error(self, error: QMediaPlayer.Error, error_string: str = "") -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        append_feedback_log(
            "media_error",
            err=int(error),
            msg=(error_string or "")[:200],
        )
        if not self._path:
            return
        if self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            return
        self._enter_ffmpeg_mode()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            append_feedback_log("media_invalid")
            self._enter_ffmpeg_mode()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._loop_enabled and self._preview_mode == _PreviewMode.MEDIA:
                self._player.setPosition(0)
                self._player.play()
            elif self._preview_mode == _PreviewMode.MEDIA:
                dur = max(0, int(self._player.duration()))
                tail = max(0, dur - 50)
                self._player.setPosition(tail)
                self._player.pause()
        elif status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            if self._preview_mode != _PreviewMode.MEDIA and self._path:
                dur = int(self._player.duration())
                if dur > 0:
                    self._finalize_media_mode(dur)

    def _finalize_media_mode(self, duration_ms: int) -> None:
        if self._preview_mode == _PreviewMode.MEDIA:
            return
        self._preview_mode = _PreviewMode.MEDIA
        self._fps, tf, self._native_w, self._native_h = probe_video(self._path)
        self._total_frames = max(1, tf)
        self._slider_is_ms = True
        self._slider.blockSignals(True)
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(0, duration_ms))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._display.show()
        self._display.raise_()
        self._overlay.raise_()
        self._player.setVideoOutput(self._video_sink)
        self._info_lbl.setText("Qt 재생")
        append_feedback_log("mode_media", duration_ms=duration_ms)
        self._prime_first_frame_media()

    def _prime_first_frame_media(self) -> None:
        if self._preview_mode != _PreviewMode.MEDIA or not self._path:
            return
        self._player.setPosition(0)
        self._player.play()
        QTimer.singleShot(120, self._pause_after_prime)

    def _pause_after_prime(self) -> None:
        if self._preview_mode != _PreviewMode.MEDIA or not self._path:
            return
        self._player.pause()
        self._player.setPosition(0)

    def _on_media_duration_changed(self, duration_ms: int) -> None:
        if duration_ms > 0 and self._preview_mode == _PreviewMode.NONE and self._path:
            self._finalize_media_mode(int(duration_ms))

    def _on_media_position_changed(self, pos_ms: int) -> None:
        if not self._slider_is_ms or self._scrub_active or self._slider_block_position:
            return
        self._slider.blockSignals(True)
        self._slider.setValue(int(pos_ms))
        self._slider.blockSignals(False)
        self._info_lbl.setText(self._info_label_media(pos_ms))
        fi = self.current_frame_index()
        self._emit_frame_index_if_changed(fi)

    def _format_ms_label(self, pos_ms: int) -> str:
        s = pos_ms // 1000
        ms = pos_ms % 1000
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if self._preview_mode != _PreviewMode.MEDIA:
            return
        ic = QColor(theme.TEXT)
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setIcon(make_media_pause_icon(FEEDBACK_MEDIA_CTL_ICON_PX, ic))
        else:
            self._play_btn.setIcon(make_media_play_icon(FEEDBACK_MEDIA_CTL_ICON_PX, ic))

    def _on_loop_toggled(self, on: bool) -> None:
        self._loop_enabled = bool(on)

    def _reset_view_zoom(self) -> None:
        self._view_zoom = 1.0
        self._view_pan_x = 0.0
        self._view_pan_y = 0.0
        self._apply_scaled_pixmap()

    def set_clip_footer_text(self, text: str) -> None:
        self._clip_footer_text = (text or "").strip()
        self._clip_footer.setText(self._clip_footer_text)
        self._clip_footer.setToolTip(self._clip_footer_text)

    def _enter_ffmpeg_mode(self) -> None:
        if not resolve_ffmpeg() or not resolve_ffprobe():
            self._display.setText("FFmpeg 없음 — 재생 불가")
            append_feedback_log("ffmpeg_tools_missing")
            return
        self._stop_media()
        self._preview_mode = _PreviewMode.FFMPEG_FRAMES
        self._slider_is_ms = False
        self._display.show()
        self._display.raise_()
        self._overlay.raise_()
        append_feedback_log("mode_ffmpeg_frames")
        self._fps, self._total_frames, self._native_w, self._native_h = probe_video(self._path)
        self._slider.blockSignals(True)
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(0, self._total_frames - 1))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._info_lbl.setText("프레임 미리보기 모드")
        self._seek_frame(0, force=True)

    def clear(self) -> None:
        self._scrub_coalesce_timer.stop()
        self._pending_media_scrub_ms = None
        self._pending_ffmpeg_scrub_idx = None
        self._ctrl_zoom_drag = False
        self._alt_pan_active = False
        self._video_gesture_mode = None
        self._video_gesture_press_global = None
        if QWidget.mouseGrabber() == self:
            self.releaseMouse()
        self._pause()
        self._stop_media()
        self._path = ""
        self._raw_pixmap = None
        self._displayed_frame = 0
        self._preview_mode = _PreviewMode.NONE
        self._display.clear()
        self._apply_idle_display_message()
        self._display.show()
        self._slider.setMaximum(0)
        self._overlay.clear_all()
        self._view_zoom = 1.0
        self._view_pan_x = 0.0
        self._view_pan_y = 0.0
        self.set_clip_footer_text("")
        self._play_btn.setIcon(make_media_play_icon(FEEDBACK_MEDIA_CTL_ICON_PX, QColor(theme.TEXT)))
        self._last_emitted_frame_idx = None
        append_feedback_log("clear")

    def _extract_frame_png_bytes_async(self, frame_index: int) -> Optional[bytes]:
        """Run FFmpeg extract in a worker thread; keeps the GUI responsive."""
        th = _ExtractPngBytesThread(self._path, frame_index, self._fps)
        loop = QEventLoop(self)
        out: List[Optional[bytes]] = [None]

        def on_done(raw: object) -> None:
            out[0] = raw if raw is None or isinstance(raw, bytes) else None
            loop.quit()

        th.done.connect(on_done)
        th.start()
        loop.exec()
        if th.isRunning():
            th.wait(180000)
        return out[0]

    def capture_annotated_png_bytes(
        self,
        *,
        burn_in_text: Optional[str] = None,
        frame_index: Optional[int] = None,
    ) -> Optional[bytes]:
        """PNG screenshot with optional burn-in.

        If *frame_index* is set (0-based file frame), the base image is always taken
        from FFmpeg using that index (same source as ``extract_frame_png``), so the
        pixels match the per-frame annotation keys without seeking the player.
        """
        if not self._path or self._preview_mode == _PreviewMode.NONE:
            return None
        base_for_composite: Optional[QPixmap] = None
        if frame_index is not None:
            if self._preview_mode not in (_PreviewMode.MEDIA, _PreviewMode.FFMPEG_FRAMES):
                return None
            fi = max(0, min(int(frame_index), max(0, self._total_frames - 1)))
            if self._preview_mode == _PreviewMode.MEDIA:
                self._player.pause()
            data = self._extract_frame_png_bytes_async(fi)
            if not data:
                append_feedback_log("capture_fail_media_extract")
                return None
            pm = QPixmap()
            if not pm.loadFromData(data):
                return None
            base_for_composite = pm
        elif self._preview_mode == _PreviewMode.MEDIA:
            self._player.pause()
            pos_ms = int(self._player.position())
            t_sec = pos_ms / 1000.0
            data = extract_frame_png_at_time(self._path, t_sec)
            if not data:
                append_feedback_log("capture_fail_media_extract")
                return None
            pm = QPixmap()
            if not pm.loadFromData(data):
                return None
            self._raw_pixmap = pm
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            if self._raw_pixmap is None or self._raw_pixmap.isNull():
                return None
        else:
            return None

        w = self._host.width()
        h = self._host.height()
        if w < 2 or h < 2:
            w, h = max(320, self._native_w), max(180, self._native_h)
        base = self._composit_frame_for_host(
            w_override=w,
            h_override=h,
            base_pixmap=base_for_composite,
        )
        if base is None or base.isNull():
            append_feedback_log("capture_fail_composite")
            return None
        comp = QPixmap(base)
        painter = QPainter(comp)
        if self._overlay.has_content():
            ann = self._overlay.render_to_pixmap(QSize(w, h))
            painter.drawPixmap(0, 0, ann)
        if burn_in_text and str(burn_in_text).strip():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont()
            font.setPixelSize(14)
            painter.setFont(font)
            margin = 10
            r = QRect(0, 0, comp.width(), comp.height() - margin)
            txt = str(burn_in_text).strip()
            br = int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
            painter.setPen(QColor(20, 20, 20))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(r.adjusted(dx, dy, dx, dy), br, txt)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(r, br, txt)
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        comp.save(buf, "PNG")
        out = bytes(buf.data())
        append_feedback_log("capture_ok", bytes_len=len(out) if out else 0)
        return out if out else None

    def _pause(self) -> None:
        self._playing = False
        if self._preview_mode == _PreviewMode.MEDIA:
            self._player.pause()
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            self._play_btn.setIcon(
                make_media_play_icon(FEEDBACK_MEDIA_CTL_ICON_PX, QColor(theme.TEXT))
            )

    def _is_at_effective_end_media(self) -> bool:
        if self._preview_mode != _PreviewMode.MEDIA:
            return False
        dur = int(self._player.duration())
        if dur <= 0:
            return False
        pos = int(self._player.position())
        return pos >= dur - 250

    def _is_at_effective_end_ffmpeg(self) -> bool:
        if self._preview_mode != _PreviewMode.FFMPEG_FRAMES:
            return False
        return (not self._playing) and self._displayed_frame >= self._total_frames - 1

    def _toggle_play(self) -> None:
        if not self._path:
            return
        if self._preview_mode == _PreviewMode.MEDIA:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                if (not self._loop_enabled) and self._is_at_effective_end_media():
                    self._player.setPosition(0)
                self._player.play()
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            ic = QColor(theme.TEXT)
            if self._playing:
                self._playing = False
                self._play_btn.setIcon(make_media_play_icon(FEEDBACK_MEDIA_CTL_ICON_PX, ic))
            else:
                if (not self._loop_enabled) and self._is_at_effective_end_ffmpeg():
                    self._seek_frame(0, force=True)
                self._playing = True
                self._play_btn.setIcon(make_media_pause_icon(FEEDBACK_MEDIA_CTL_ICON_PX, ic))
                self._queue_next_play_frame()

    def _queue_next_play_frame(self) -> None:
        if not self._playing or not self._path:
            return
        if self._displayed_frame >= self._total_frames - 1:
            if self._loop_enabled:
                self._seek_frame(0, force=True)
                QTimer.singleShot(0, self._queue_next_play_frame)
            else:
                self._pause()
            return
        self._seek_frame(self._displayed_frame + 1, force=True)

    def _on_slider_pressed(self) -> None:
        self._scrub_coalesce_timer.stop()
        self._pending_media_scrub_ms = None
        self._pending_ffmpeg_scrub_idx = None
        self._scrub_active = True
        self._was_playing_before_scrub = self._playing or (
            self._preview_mode == _PreviewMode.MEDIA
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self._pause()
        if self._preview_mode == _PreviewMode.MEDIA:
            self._player.pause()

    def _on_slider_moved(self, value: int) -> None:
        if not self._scrub_active:
            return
        if self._preview_mode == _PreviewMode.MEDIA:
            pos = self._snap_position_ms_to_frame(int(value))
            self._slider_block_position = True
            self._slider.blockSignals(True)
            self._slider.setValue(pos)
            self._slider.blockSignals(False)
            self._slider_block_position = False
            self._info_lbl.setText(self._info_label_media(pos))
            self._pending_media_scrub_ms = int(pos)
            self._arm_scrub_coalesce()
            fi = max(
                0,
                min(int(round((pos / 1000.0) * self._fps)), max(0, self._total_frames - 1)),
            )
            self._emit_frame_index_if_changed(fi)
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            v = int(value)
            self._slider.blockSignals(True)
            self._slider.setValue(v)
            self._slider.blockSignals(False)
            self._info_lbl.setText(self._info_label_ffmpeg(v))
            self._pending_ffmpeg_scrub_idx = v
            self._arm_scrub_coalesce()
            self._emit_frame_index_if_changed(v)

    def _on_slider_released(self) -> None:
        self._flush_scrub_coalesce()
        self._scrub_active = False
        if self._was_playing_before_scrub:
            if self._preview_mode == _PreviewMode.MEDIA:
                self._player.play()
            else:
                self._toggle_play()
        self._was_playing_before_scrub = False

    def _on_slider_value_changed_user(self, value: int) -> None:
        if self._scrub_active:
            return
        if self._slider.signalsBlocked():
            return
        if self._preview_mode == _PreviewMode.MEDIA:
            pos = self._snap_position_ms_to_frame(int(value))
            self._slider_block_position = True
            self._player.setPosition(pos)
            if pos != int(value):
                self._slider.blockSignals(True)
                self._slider.setValue(pos)
                self._slider.blockSignals(False)
            self._slider_block_position = False
        elif self._preview_mode == _PreviewMode.FFMPEG_FRAMES:
            self._seek_frame(int(value), force=True)

    def _seek_frame(self, idx: int, *, force: bool = False) -> None:
        if not self._path:
            return
        idx = max(0, min(int(idx), self._total_frames - 1))
        if idx == self._displayed_frame and not force and self._raw_pixmap is not None:
            return
        self._decode_target = idx
        self._slider.blockSignals(True)
        self._slider.setValue(idx)
        self._slider.blockSignals(False)
        if self._decode_busy:
            return
        self._start_decode_worker()

    def _start_decode_worker(self) -> None:
        if not self._path:
            return
        path_snap = self._path
        fi = self._decode_target
        self._decode_busy = True
        th = _DecodeThread(path_snap, fi, self._fps)

        def _on_done(result_fi: int, pm: object) -> None:
            self._decode_busy = False
            if path_snap != self._path:
                self._start_decode_worker()
                return
            if result_fi != self._decode_target:
                self._start_decode_worker()
                return
            if pm is not None and isinstance(pm, QPixmap) and not pm.isNull():
                self._displayed_frame = result_fi
                self._raw_pixmap = pm
                self._apply_scaled_pixmap()
            else:
                self._display.setText("프레임 디코딩 실패")
            self._info_lbl.setText(self._info_label_ffmpeg(result_fi))
            self._emit_frame_index_if_changed(int(result_fi))
            if self._playing and pm is not None and isinstance(pm, QPixmap) and not pm.isNull():
                if self._displayed_frame >= self._total_frames - 1:
                    self._pause()
                else:
                    QTimer.singleShot(0, self._queue_next_play_frame)

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

    def _clamp_pan(self, sw: int, sh: int, w: int, h: int) -> None:
        ox0 = (w - sw) // 2
        oy0 = (h - sh) // 2
        lo_x = -ox0
        hi_x = w - sw - ox0
        lo_y = -oy0
        hi_y = h - sh - oy0
        ax, bx = (lo_x, hi_x) if lo_x <= hi_x else (hi_x, lo_x)
        ay, by = (lo_y, hi_y) if lo_y <= hi_y else (hi_y, lo_y)
        self._view_pan_x = max(ax, min(bx, self._view_pan_x))
        self._view_pan_y = max(ay, min(by, self._view_pan_y))

    def _composit_frame_for_host(
        self,
        w_override: Optional[int] = None,
        h_override: Optional[int] = None,
        base_pixmap: Optional[QPixmap] = None,
    ) -> Optional[QPixmap]:
        src = base_pixmap if base_pixmap is not None else self._raw_pixmap
        if src is None or src.isNull():
            return None
        w = w_override if w_override is not None else self._display.width()
        h = h_override if h_override is not None else self._display.height()
        w = max(1, int(w))
        h = max(1, int(h))
        if w < 2 or h < 2:
            return None
        zw = max(int(w * self._view_zoom), 2)
        zh = max(int(h * self._view_zoom), 2)
        scaled = src.scaled(
            zw,
            zh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        sw, sh = scaled.width(), scaled.height()
        self._clamp_pan(sw, sh, w, h)
        ox0 = (w - sw) // 2
        oy0 = (h - sh) // 2
        dx = ox0 + int(round(self._view_pan_x))
        dy = oy0 + int(round(self._view_pan_y))
        comp = QPixmap(w, h)
        comp.fill(QColor(theme.BORDER))
        painter = QPainter(comp)
        painter.drawPixmap(dx, dy, scaled)
        painter.end()
        return comp

    def _apply_scaled_pixmap(self) -> None:
        comp = self._composit_frame_for_host()
        if comp is None:
            return
        self._display.setPixmap(comp)
        self._display.setText("")
