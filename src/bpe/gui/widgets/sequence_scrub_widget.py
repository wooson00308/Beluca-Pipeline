# @cursor-change: 2026-08-13, 0.12.x, 프리뷰 2배속(1x/2x) 토글 — 항목 전환 시 1x 리셋
"""소스 라이브러리 프리뷰 패널.

동영상은 ``QVideoWidget`` 으로 GPU 직통 재생한다 (프레임을 파이썬으로 복사하지 않음).
EXR/DPX 시퀀스는 ffmpeg 로 작은 JPEG 를 한 장씩 디코드해 보여준다.

레이아웃이 흔들리지 않도록:

* 이미지 표시는 ``sizeHint`` 가 상수인 ``_FixedCanvas`` (paintEvent) 로 그린다.
* 동영상/이미지는 ``QStackedLayout`` 으로 같은 자리를 차지한다.
* 정보 라벨은 고정 높이 + ``Ignored`` 정책이라 글자 수가 바뀌어도 밀리지 않는다.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core import media_thumbs
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.source_library_scan import KIND_MOVIE, KIND_SEQUENCE, expand_frame_pattern, join_path
from bpe.gui import theme

logger = get_logger("gui.widgets.sequence_scrub_widget")

# 프리뷰용 디코드 크기 — 캔버스(~672px) +20% 에 맞춤, 여전히 브라우징용
PREVIEW_PX = 768
_PREVIEW_TAG = "pv{}".format(PREVIEW_PX)
_PRECISE_DELAY_MS = 130
_FRAME_CACHE_MAX = 48
_SEQ_PLAY_INTERVAL_MS = 90
# 캔버스 권장 크기 — 그림이 바뀌어도 레이아웃이 재계산되지 않게 상수로 고정
_CANVAS_HINT = QSize(672, 408)


class _FixedCanvas(QWidget):
    """이미지를 paintEvent 로 그린다. sizeHint 가 상수라 레이아웃이 흔들리지 않는다."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._raw: Optional[QPixmap] = None
        self._scaled: Optional[QPixmap] = None
        self._scaled_for: QSize = QSize()
        self._placeholder = "항목을 선택하세요"
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "background-color: #101012; border: 1px solid {bd}; border-radius: 4px;".format(
                bd=theme.BORDER
            )
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return _CANVAS_HINT

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 120)

    def set_placeholder(self, text: str) -> None:
        self._raw = None
        self._scaled = None
        self._scaled_for = QSize()
        self._placeholder = text or ""
        self.update()

    def set_pixmap(self, pm: Optional[QPixmap]) -> None:
        if pm is None or pm.isNull():
            self.set_placeholder(self._placeholder or "항목을 선택하세요")
            return
        self._raw = pm
        self._scaled = None
        self._scaled_for = QSize()
        self._placeholder = ""
        self._rebuild_scaled()
        self.update()

    def _rebuild_scaled(self) -> None:
        if self._raw is None or self._raw.isNull():
            self._scaled = None
            return
        area = self.size()
        if area.width() < 4 or area.height() < 4:
            return
        if self._scaled is not None and self._scaled_for == area:
            return
        self._scaled = self._raw.scaled(
            area,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._scaled_for = QSize(area)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101012"))
        if self._raw is not None and not self._raw.isNull():
            self._rebuild_scaled()
            pm = self._scaled
            if pm is not None and not pm.isNull():
                x = (self.width() - pm.width()) // 2
                y = (self.height() - pm.height()) // 2
                painter.drawPixmap(x, y, pm)
        elif self._placeholder:
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._placeholder)
        painter.end()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 크기만 바뀌면 캐시된 축소본을 버리고 다시 그린다 (레이아웃 재계산은 유발하지 않음).
        self._scaled = None
        self._scaled_for = QSize()
        self.update()


class _FrameDecodeThread(QThread):
    """프레임 하나를 ffmpeg 로 디코드해 캐시 경로를 돌려준다 (UI 블로킹 방지)."""

    decoded = Signal(int, object)  # frame, Optional[str] 캐시 파일 경로

    def __init__(self, frame: int, frame_path: str) -> None:
        super().__init__()
        self._frame = int(frame)
        self._frame_path = frame_path

    def run(self) -> None:
        path: Optional[str] = None
        try:
            size_bytes, mtime = 0, 0.0
            try:
                st = os.stat(self._frame_path)
                size_bytes, mtime = int(st.st_size), float(st.st_mtime)
            except OSError:
                pass
            key = media_thumbs.make_key(self._frame_path, size_bytes, mtime, tag=_PREVIEW_TAG)
            out = media_thumbs.ensure_preview_frame(self._frame_path, key, PREVIEW_PX)
            path = str(out) if out is not None else None
        except Exception as exc:
            logger.debug("프레임 디코드 실패: %s", exc)
        self.decoded.emit(self._frame, path)


class MediaPreviewWidget(QWidget):
    """라이브러리 항목 하나를 미리보는 패널 (동영상 재생 / 시퀀스 스크럽 / 스틸)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "none"  # none | movie | frames
        self._dir_path = ""
        self._row: Dict[str, Any] = {}
        self._frames: List[int] = []
        self._frame_pixmaps: "OrderedDict[int, QPixmap]" = OrderedDict()
        self._decode_thread: Optional[_FrameDecodeThread] = None
        self._decode_busy = False
        self._decode_target: Optional[int] = None
        self._current_frame = 0
        self._playing = False
        self._muted = True
        self._playback_rate = 1.0
        self._player: Optional[QMediaPlayer] = None
        self._audio: Optional[QAudioOutput] = None
        self._pending_thumb: Optional[QPixmap] = None

        self._precise_timer = QTimer(self)
        self._precise_timer.setSingleShot(True)
        self._precise_timer.setInterval(_PRECISE_DELAY_MS)
        self._precise_timer.timeout.connect(self._request_precise_frame)

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(_SEQ_PLAY_INTERVAL_MS)
        self._play_timer.timeout.connect(self._on_play_tick)

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        stage = QWidget()
        stage.setMinimumHeight(200)
        stage.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._stack = QStackedLayout(stage)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackOne)

        self._canvas = _FixedCanvas()
        self._stack.addWidget(self._canvas)  # index 0 = 이미지

        self._video = QVideoWidget()
        self._video.setMinimumHeight(200)
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video.setStyleSheet("background-color: #101012;")
        self._stack.addWidget(self._video)  # index 1 = 동영상 (GPU 직통)

        self._stack.setCurrentIndex(0)
        root.addWidget(stage, 1)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setTracking(True)
        self._slider.setFixedHeight(18)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal {{ background: {ibg}; height: 4px; border-radius: 2px; }}"
            "QSlider::sub-page:horizontal {{ background: {acc}; height: 4px; border-radius: 2px; }}"
            "QSlider::handle:horizontal {{ background: {acc}; width: 12px; height: 12px;"
            " margin: -5px 0; border-radius: 6px; }}".format(ibg=theme.INPUT_BG, acc=theme.ACCENT)
        )
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_released)
        root.addWidget(self._slider)

        ctl = QHBoxLayout()
        ctl.setSpacing(8)
        btn_style = (
            "QToolButton {{ background: transparent; border: none; color: {}; font-size: 13px; }}"
            "QToolButton:hover {{ color: {}; }}".format(theme.TEXT, theme.ACCENT_TEXT)
        )
        self._play_btn = QToolButton()
        self._play_btn.setText("\u25b6")
        self._play_btn.setToolTip("재생 / 일시정지")
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setFixedSize(QSize(28, 24))
        self._play_btn.setStyleSheet(btn_style)
        self._play_btn.clicked.connect(self.toggle_play)
        ctl.addWidget(self._play_btn, 0)

        self._mute_btn = QToolButton()
        self._mute_btn.setText("\U0001f507")
        self._mute_btn.setToolTip("소리 켜기 / 끄기")
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setFixedSize(QSize(28, 24))
        self._mute_btn.setStyleSheet(btn_style)
        self._mute_btn.clicked.connect(self._toggle_mute)
        ctl.addWidget(self._mute_btn, 0)

        self._rate_btn = QToolButton()
        self._rate_btn.setText("1x")
        self._rate_btn.setToolTip("재생 속도 (1배속 / 2배속)")
        self._rate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rate_btn.setFixedSize(QSize(28, 24))
        self._rate_btn.setStyleSheet(btn_style)
        self._rate_btn.clicked.connect(self._toggle_playback_rate)
        ctl.addWidget(self._rate_btn, 0)

        self._info = QLabel("")
        self._info.setFixedHeight(20)
        self._info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._info.setStyleSheet(
            "color: {}; font-size: {}px; border: none;".format(
                theme.TEXT_LABEL, theme.FONT_SIZE_SMALL
            )
        )
        ctl.addWidget(self._info, 1)
        root.addLayout(ctl)

    # ── 공개 API ────────────────────────────────────────────────────

    def set_item(
        self,
        dir_path: str,
        row: Dict[str, Any],
        thumb: Optional[QPixmap] = None,
    ) -> None:
        """항목 하나를 프리뷰에 올린다. ``thumb`` 이 있으면 즉시 띄워 검은 화면을 피한다.

        팩(``preview_file``)이면 MOV 를 재생하고, Nuke/경로는 ``seq_pattern``(image/) 을 쓴다.
        """
        self.clear()
        if not row:
            return
        self._pending_thumb = thumb if thumb is not None and not thumb.isNull() else None
        self._dir_path = normalize_path_str(dir_path)
        self._row = dict(row)
        kind = str(row.get("kind") or "")
        preview = str(row.get("preview_file") or "").strip()
        if preview or kind == KIND_MOVIE:
            self._setup_movie(filename=preview or None)
        else:
            self._setup_frames(is_sequence=kind == KIND_SEQUENCE)

    def play_movie_file(self, path: str) -> None:
        """절대경로 MOV 를 바로 재생 (기본 인트로 프리뷰용)."""
        self.clear()
        path_n = normalize_path_str(path)
        if not path_n or not os.path.isfile(path_n):
            self._canvas.set_placeholder("프리뷰를 찾을 수 없습니다")
            return
        self._dir_path = os.path.dirname(path_n).replace("\\", "/")
        self._row = {"kind": KIND_MOVIE, "seq_pattern": os.path.basename(path_n)}
        self._setup_movie(filename=os.path.basename(path_n))

    def clear(self) -> None:
        """재생/디코드를 멈추고 화면을 비운다."""
        self._playing = False
        self._play_timer.stop()
        self._precise_timer.stop()
        self._stop_movie()
        self._mode = "none"
        self._row = {}
        self._dir_path = ""
        self._frames = []
        self._frame_pixmaps.clear()
        self._decode_target = None
        self._current_frame = 0
        self._pending_thumb = None
        self._slider.blockSignals(True)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._slider.setEnabled(False)
        self._play_btn.setText("\u25b6")
        self._play_btn.setEnabled(False)
        # 항목이 바뀌면 배속은 항상 1x 로 되돌린다. 변수만 바꾸면 안 되고
        # 타이머 간격·살아있는 플레이어의 rate 까지 전부 복원해야 한다
        # (플레이어는 한 번 만들면 재사용되고 setSource 가 rate 를 리셋해 주지 않음).
        self._playback_rate = 1.0
        self._rate_btn.setText("1x")
        self._play_timer.setInterval(_SEQ_PLAY_INTERVAL_MS)
        if self._player is not None:
            self._player.setPlaybackRate(1.0)
        self._info.setText("")
        self._stack.setCurrentIndex(0)
        self._canvas.set_placeholder("항목을 선택하세요")

    def shutdown(self) -> None:
        """팝업이 닫힐 때 스레드/플레이어를 확실히 정리한다."""
        self.clear()
        th = self._decode_thread
        if th is not None and th.isRunning():
            th.wait(3000)
        self._decode_thread = None

    def toggle_play(self) -> None:
        if self._mode == "movie" and self._player is not None:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
            return
        if self._mode != "frames" or len(self._frames) <= 1:
            return
        self._playing = not self._playing
        self._play_btn.setText("\u25a0" if self._playing else "\u25b6")
        if self._playing:
            self._play_timer.start()
        else:
            self._play_timer.stop()

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        if self._audio is not None:
            self._audio.setMuted(self._muted)
        self._mute_btn.setText("\U0001f507" if self._muted else "\U0001f50a")

    def _toggle_playback_rate(self) -> None:
        """1x ↔ 2x 토글. 분기 없이 타이머·플레이어 양쪽에 항상 적용한다.

        플레이어는 MOV 를 한 번이라도 재생하면 영구 재사용되므로 존재 여부로
        모드를 가르면 안 된다 (시퀀스 배속이 죽는다). 타이머 간격 조정은
        movie 모드에서 무해하고(틱 콜백이 frames 모드 아니면 즉시 반환),
        쉬고 있는 플레이어의 rate 설정도 무해하다.
        """
        rates = [1.0, 2.0]
        idx = rates.index(self._playback_rate) if self._playback_rate in rates else 0
        self._playback_rate = rates[(idx + 1) % len(rates)]
        self._rate_btn.setText("2x" if self._playback_rate == 2.0 else "1x")
        self._play_timer.setInterval(int(_SEQ_PLAY_INTERVAL_MS / self._playback_rate))
        if self._player is not None:
            self._player.setPlaybackRate(self._playback_rate)

    # ── 동영상 ──────────────────────────────────────────────────────

    def _setup_movie(self, filename: Optional[str] = None) -> None:
        name = (filename or "").strip() or str(self._row.get("seq_pattern") or "")
        path = join_path(self._dir_path, name)
        path = normalize_path_str(path)
        self._mode = "movie"
        # 첫 프레임이 준비되기 전까지 썸네일로 자리를 채워 검은 화면/레이아웃 흔들림을 막는다.
        self._stack.setCurrentIndex(0)
        if self._pending_thumb is not None:
            self._canvas.set_pixmap(self._pending_thumb)
        else:
            self._canvas.set_placeholder("로딩…")
        self._ensure_player()
        assert self._player is not None
        self._slider.setEnabled(True)
        self._play_btn.setEnabled(True)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.6)
        self._audio.setMuted(self._muted)
        self._player.setAudioOutput(self._audio)
        # GPU 직통 — 파이썬이 프레임을 만지지 않는다.
        self._player.setVideoOutput(self._video)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

    def _stop_movie(self) -> None:
        if self._player is None:
            return
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass

    def _on_duration_changed(self, duration_ms: int) -> None:
        if self._mode != "movie":
            return
        self._slider.blockSignals(True)
        self._slider.setMaximum(max(0, int(duration_ms)))
        self._slider.blockSignals(False)

    def _on_position_changed(self, pos_ms: int) -> None:
        if self._mode != "movie" or self._slider.isSliderDown():
            return
        self._slider.blockSignals(True)
        self._slider.setValue(int(pos_ms))
        self._slider.blockSignals(False)
        self._info.setText(self._movie_info_text(int(pos_ms)))

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("\u25a0" if playing else "\u25b6")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._mode != "movie":
            return
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
        ):
            # 첫 프레임이 준비되면 영상 위젯으로 전환 (같은 자리라 레이아웃 불변).
            if self._stack.currentIndex() != 1:
                self._stack.setCurrentIndex(1)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia and self._player is not None:
            self._player.setPosition(0)
            self._player.play()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            logger.info("QtMultimedia 재생 불가 — 썸네일로 대체")
            self._stop_movie()
            self._mode = "frames"
            self._stack.setCurrentIndex(0)
            self._slider.setEnabled(False)
            self._play_btn.setEnabled(False)
            if self._pending_thumb is not None:
                self._canvas.set_pixmap(self._pending_thumb)
                self._info.setText("미리보기 (재생 불가 코덱)")
            else:
                self._canvas.set_placeholder("이 코덱은 미리보기를 만들 수 없습니다")

    def _movie_info_text(self, pos_ms: int) -> str:
        total = max(0, self._slider.maximum())
        return "{} / {}".format(_ms_label(pos_ms), _ms_label(total))

    # ── 이미지 시퀀스 / 스틸 ────────────────────────────────────────

    def _setup_frames(self, is_sequence: bool) -> None:
        self._mode = "frames"
        self._stack.setCurrentIndex(0)
        first = int(self._row.get("frame_first") or 0)
        last = int(self._row.get("frame_last") or 0)
        if is_sequence and last >= first:
            self._frames = list(range(first, last + 1))
        else:
            self._frames = [0]
        multi = len(self._frames) > 1
        self._slider.blockSignals(True)
        self._slider.setMaximum(max(0, len(self._frames) - 1))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._slider.setEnabled(multi)
        self._play_btn.setEnabled(multi)
        if self._pending_thumb is not None:
            self._canvas.set_pixmap(self._pending_thumb)
        else:
            self._canvas.set_placeholder("로딩…")
        self._show_frame_index(0, precise=True)

    def _frame_path(self, frame: int) -> str:
        pattern = str(self._row.get("seq_pattern") or "")
        if str(self._row.get("kind") or "") != KIND_SEQUENCE:
            return normalize_path_str(join_path(self._dir_path, pattern))
        return normalize_path_str(join_path(self._dir_path, expand_frame_pattern(pattern, frame)))

    def _show_frame_index(self, index: int, precise: bool) -> None:
        if not self._frames:
            return
        idx = max(0, min(int(index), len(self._frames) - 1))
        frame = self._frames[idx]
        self._current_frame = frame
        self._info.setText(self._frames_info_text(frame))

        cached = self._frame_pixmaps.get(frame)
        if cached is not None:
            self._canvas.set_pixmap(cached)
            return
        if precise:
            self._decode_target = frame
            self._start_decode()
        else:
            self._decode_target = frame
            self._precise_timer.start()

    def _request_precise_frame(self) -> None:
        if self._decode_target is not None:
            self._start_decode()

    def _start_decode(self) -> None:
        if self._decode_busy or self._decode_target is None or self._mode != "frames":
            return
        frame = self._decode_target
        if frame in self._frame_pixmaps:
            self._decode_target = None
            return
        self._decode_busy = True
        th = _FrameDecodeThread(frame, self._frame_path(frame))
        th.decoded.connect(self._on_frame_decoded)
        th.finished.connect(th.deleteLater)
        self._decode_thread = th
        th.start()

    def _on_frame_decoded(self, frame: int, path: object) -> None:
        self._decode_busy = False
        if self._mode != "frames":
            return
        if isinstance(path, str) and path:
            pm = QPixmap(path)
            if not pm.isNull():
                self._frame_pixmaps[frame] = pm
                while len(self._frame_pixmaps) > _FRAME_CACHE_MAX:
                    self._frame_pixmaps.popitem(last=False)
                if frame == self._current_frame:
                    self._canvas.set_pixmap(pm)
        elif self._pending_thumb is None:
            self._canvas.set_placeholder("미리보기를 만들 수 없습니다")
        if self._decode_target is not None and self._decode_target != frame:
            self._start_decode()
        else:
            self._decode_target = None
        if self._playing:
            self._play_timer.start()

    def _frames_info_text(self, frame: int) -> str:
        if len(self._frames) <= 1:
            return str(self._row.get("name") or "")
        return "프레임 {} / {}-{}  ({}장)".format(
            frame, self._frames[0], self._frames[-1], len(self._frames)
        )

    def _on_play_tick(self) -> None:
        if not self._playing or self._mode != "frames" or len(self._frames) <= 1:
            return
        if self._decode_busy:
            return
        next_idx = self._slider.value() + 1
        if next_idx > self._slider.maximum():
            next_idx = 0
        self._slider.blockSignals(True)
        self._slider.setValue(next_idx)
        self._slider.blockSignals(False)
        self._show_frame_index(next_idx, precise=True)

    # ── 슬라이더 ────────────────────────────────────────────────────

    def _on_slider_pressed(self) -> None:
        self._precise_timer.stop()
        if self._mode == "movie" and self._player is not None:
            self._player.pause()

    def _on_slider_moved(self, value: int) -> None:
        if self._mode == "movie":
            self._info.setText(self._movie_info_text(int(value)))
            return
        # 드래그 중에는 이미 캐시된 프레임만 보여주고 디코드는 미룬다.
        idx = int(value)
        if 0 <= idx < len(self._frames):
            frame = self._frames[idx]
            self._current_frame = frame
            self._info.setText(self._frames_info_text(frame))
            cached = self._frame_pixmaps.get(frame)
            if cached is not None:
                self._canvas.set_pixmap(cached)
            self._decode_target = frame
            self._precise_timer.start()

    def _on_slider_released(self) -> None:
        if self._mode == "movie" and self._player is not None:
            self._player.setPosition(int(self._slider.value()))
            self._player.play()
            return
        self._show_frame_index(int(self._slider.value()), precise=True)


def _ms_label(ms: int) -> str:
    total_s = max(0, int(ms)) // 1000
    return "{:02d}:{:02d}".format(total_s // 60, total_s % 60)
