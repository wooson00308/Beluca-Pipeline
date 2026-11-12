"""컨펌 창 — 영상 파일의 프레임을 뒤에서 풀어 오는 워커."""

from __future__ import annotations

import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from bpe.core.confirm_decode import build_decode_command, fit_decode_size, frame_byte_size
from bpe.core.confirm_probe import probe_video
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs

logger = get_logger("gui.workers.confirm_decode")

_MAX_W, _MAX_H = 1920, 1080
_DECODE_TIMEOUT_SECS = 120


class FirstFrameDecodeWorker(QThread):
    """파일 하나의 프레임 한 장(16비트 RGB)을 풀어 돌려준다."""

    decoded = Signal(bytes, int, int, str)  # data, width, height, 설명
    failed = Signal(str)

    def __init__(self, path: str, frame_index: int = 0) -> None:
        super().__init__()
        self._path = path
        self._frame_index = max(0, int(frame_index))
        self._proc: Optional[subprocess.Popen] = None
        self._stopped = False

    def stop(self) -> None:
        """창을 닫을 때 — 돌고 있는 ffmpeg 를 끝낸다."""
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def run(self) -> None:
        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            self.failed.emit("ffmpeg 를 찾지 못했습니다")
            return
        info = probe_video(self._path)
        if info is None:
            self.failed.emit("영상 규격을 읽지 못했습니다 (ffprobe)")
            return
        w, h = fit_decode_size(info.width, info.height, _MAX_W, _MAX_H)
        cmd = build_decode_command(
            ffmpeg, self._path, width=w, height=h, start_index=self._frame_index, frame_count=1
        )
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **no_console_subprocess_kwargs(),
            )
            out, err = self._proc.communicate(timeout=_DECODE_TIMEOUT_SECS)
        except subprocess.TimeoutExpired:
            self.stop()
            self.failed.emit("영상을 푸는 데 너무 오래 걸려 멈췄습니다")
            return
        except OSError as e:
            self.failed.emit(f"ffmpeg 를 실행하지 못했습니다: {e}")
            return
        if self._stopped:
            return
        size = frame_byte_size(w, h)
        if len(out) < size:
            msg = err.decode("utf-8", errors="replace").strip().splitlines()[-1:] or [""]
            logger.warning("confirm decode: short output %s/%s %s", len(out), size, msg[0])
            self.failed.emit(f"프레임을 풀지 못했습니다. {msg[0]}".strip())
            return
        fps = f"{info.fps:.3f}" if info.fps else "?"
        frames = str(info.frame_count) if info.frame_count else "?"
        desc = (
            f"{info.width}×{info.height} · {info.codec} {info.profile} · {info.pix_fmt} · "
            f"{fps} fps · {frames} 프레임"
        )
        if (w, h) != (info.width, info.height):
            desc += f" · 화면용으로 {w}×{h} 로 줄여 올림"
        self.decoded.emit(out[:size], w, h, desc)
