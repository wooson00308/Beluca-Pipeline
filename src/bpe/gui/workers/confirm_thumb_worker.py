"""컨펌 창 샷 목록의 썸네일 받기 — 줄 세운 주소를 차례로 내려받는다."""

from __future__ import annotations

import queue
import urllib.request
from typing import Any, Tuple

from PySide6.QtCore import QThread, Signal

from bpe.core.logging import get_logger

logger = get_logger("gui.workers.confirm_thumb")

_TIMEOUT_SECS = 12
_MAX_BYTES = 4 * 1024 * 1024


class ThumbFetchWorker(QThread):
    """*jobs* 에서 ``(key, url)`` 을 꺼내 받은 그림 바이트를 알린다. 줄이 비면 끝난다."""

    thumb_ready = Signal(object, object)  # key, bytes

    def __init__(self, jobs: "queue.Queue[Tuple[Any, str]]") -> None:
        super().__init__()
        self._jobs = jobs
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D401
        while not self._stop:
            try:
                key, url = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                with urllib.request.urlopen(url, timeout=_TIMEOUT_SECS) as resp:
                    data = resp.read(_MAX_BYTES + 1)
            except Exception as e:  # 썸네일은 없어도 되는 것 — 조용히 넘어간다
                logger.debug("thumb fetch failed: %s", e)
                continue
            if data and len(data) <= _MAX_BYTES and not self._stop:
                self.thumb_ready.emit(key, data)
