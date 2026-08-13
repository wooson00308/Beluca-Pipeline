"""공유 소스 라이브러리 인덱스 동기(pull)를 백그라운드에서 수행하는 워커.

``source_library_publish.try_pull_index_with_status()``가 네트워크 드라이브의
sqlite 파일을 ``shutil.copy2``로 복사하는데, 이걸 메인(GUI) 스레드에서 그대로
부르면 서버가 느리거나 끊겼을 때 창 전체가 멈춘 것처럼 보인다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

from bpe.core import source_library_publish as publish
from bpe.core.logging import get_logger

logger = get_logger("gui.workers.index_sync_worker")


class IndexSyncWorker(QThread):
    """``try_pull_index_with_status()`` 한 번을 백그라운드 스레드에서 실행한다."""

    sync_done = Signal(object)  # Optional[Dict[str, Any]] meta — pull 없었으면 None
    sync_error = Signal(str)

    def run(self) -> None:
        try:
            meta: Optional[Dict[str, Any]]
            err: Optional[str]
            meta, err = publish.try_pull_index_with_status()
        except Exception as exc:
            logger.warning("인덱스 동기 실패: %s", exc)
            self.sync_error.emit(str(exc))
            return
        if err:
            self.sync_error.emit(err)
            return
        self.sync_done.emit(meta)
