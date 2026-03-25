"""QThread-based worker for ShotGrid API calls off the UI thread."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal


class ShotGridWorker(QThread):
    """Run any callable in a background thread, emitting signals on completion."""

    finished = Signal(object)  # result value
    error = Signal(str)  # error message
    progress = Signal(float)  # 0.0 ~ 1.0

    def __init__(
        self,
        func: Callable[..., Any],
        *args: Any,
        progress_cb_arg: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._progress_cb_arg = progress_cb_arg

    def run(self) -> None:
        try:
            if self._progress_cb_arg:
                self._kwargs[self._progress_cb_arg] = self._emit_progress
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _emit_progress(self, value: float) -> None:
        self.progress.emit(max(0.0, min(1.0, float(value))))
