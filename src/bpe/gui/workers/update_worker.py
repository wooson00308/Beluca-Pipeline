"""QThread workers for update check and download."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from bpe.core import update_checker
from bpe.core.logging import get_logger

logger = get_logger("update_worker")


class UpdateCheckWorker(QThread):
    """백그라운드에서 최신 릴리즈를 확인한다."""

    update_available = Signal(object)  # UpdateInfo
    up_to_date = Signal()
    error = Signal(str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self._current_version = current_version

    def run(self) -> None:
        try:
            info = update_checker.check_latest_release(self._current_version)
            if info is not None:
                self.update_available.emit(info)
            else:
                self.up_to_date.emit()
        except Exception as e:
            logger.warning("Update check failed: %s", e)
            self.error.emit(str(e))


class UpdateDownloadWorker(QThread):
    """릴리즈 에셋을 다운로드한다."""

    progress = Signal(float)  # 0.0 ~ 1.0
    finished = Signal(str)  # download path
    error = Signal(str)

    def __init__(self, url: str, dest_path: str) -> None:
        super().__init__()
        self._url = url
        self._dest_path = dest_path

    def run(self) -> None:
        try:
            result = update_checker.download_release_asset(
                self._url,
                Path(self._dest_path),
                progress_cb=self._emit_progress,
            )
            self.finished.emit(str(result))
        except Exception as e:
            logger.warning("Download failed: %s", e)
            self.error.emit(str(e))

    def _emit_progress(self, value: float) -> None:
        self.progress.emit(max(0.0, min(1.0, float(value))))
