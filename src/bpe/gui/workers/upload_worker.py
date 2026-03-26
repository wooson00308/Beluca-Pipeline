"""QThread worker specifically for MOV upload with progress reporting."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Signal


class UploadWorker(QThread):
    """Upload a movie file to a ShotGrid Version in a background thread."""

    finished = Signal()
    error = Signal(str)
    progress = Signal(float)
    status = Signal(str)  # status text updates

    def __init__(
        self,
        version_id: int,
        movie_path: str,
        *,
        image_path: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._version_id = version_id
        self._movie_path = movie_path
        self._image_path = image_path

    def run(self) -> None:
        from bpe.shotgrid.client import get_default_sg
        from bpe.shotgrid.versions import upload_movie_to_version, upload_thumbnail_to_version

        try:
            sg = get_default_sg()

            self.status.emit("Uploading movie...")
            upload_movie_to_version(
                sg,
                self._version_id,
                self._movie_path,
                progress_cb=self._on_progress,
            )

            self.status.emit("Uploading thumbnail...")
            upload_thumbnail_to_version(
                sg,
                self._version_id,
                image_path=self._image_path,
                movie_path=self._movie_path,
            )

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, value: float) -> None:
        self.progress.emit(max(0.0, min(1.0, float(value))))
