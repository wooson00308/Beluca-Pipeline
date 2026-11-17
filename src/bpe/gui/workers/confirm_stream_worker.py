"""컨펌 창 — 영상의 프레임들을 뒤에서 차례로 풀어 메모리에 올리는 워커."""

from __future__ import annotations

import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from bpe.core.confirm_decode import build_decode_command, frame_byte_size, read_exact_frames
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs

logger = get_logger("gui.workers.confirm_stream")


class StreamDecodeWorker(QThread):
    """``start_index`` 부터 ``frame_count`` 장(없으면 끝까지)을 16비트 RGB 로 풀어 보낸다."""

    frame_ready = Signal(str, int, object)  # 판 이름, 0부터 세는 번호, bytes
    finished_ok = Signal(str, int)  # 판 이름, 보낸 장 수
    failed = Signal(str, str)

    def __init__(
        self,
        key: str,
        path: str,
        width: int,
        height: int,
        *,
        start_index: int = 0,
        frame_count: Optional[int] = None,
        resample: str = "plain",
    ) -> None:
        super().__init__()
        self._resample = resample
        self.key = key
        self._path = path
        self._w, self._h = width, height
        self._start = max(0, int(start_index))
        self._count = frame_count
        self._proc: Optional[subprocess.Popen] = None
        self._stopped = False

    def stop(self) -> None:
        """창을 닫거나 샷을 바꿀 때 — 돌고 있는 ffmpeg 를 끝낸다."""
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
            self.failed.emit(self.key, "ffmpeg 를 찾지 못했습니다")
            return
        cmd = build_decode_command(
            ffmpeg,
            self._path,
            width=self._w,
            height=self._h,
            start_index=self._start,
            frame_count=self._count,
            resample=self._resample,
        )
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **no_console_subprocess_kwargs(),
            )
        except OSError as e:
            self.failed.emit(self.key, f"ffmpeg 를 실행하지 못했습니다: {e}")
            return
        sent = 0
        try:
            assert self._proc.stdout is not None
            for data in read_exact_frames(self._proc.stdout, frame_byte_size(self._w, self._h)):
                if self._stopped:
                    break
                self.frame_ready.emit(self.key, self._start + sent, data)
                sent += 1
        except OSError as e:
            logger.warning("confirm stream decode read error: %s", e)
        finally:
            self.stop_process_quietly()
        if self._stopped:
            return
        if sent == 0:
            self.failed.emit(self.key, "프레임을 풀지 못했습니다")
        else:
            self.finished_ok.emit(self.key, sent)

    def stop_process_quietly(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
