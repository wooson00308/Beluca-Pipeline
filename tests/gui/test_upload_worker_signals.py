# @cursor-change: 2026-08-06, 0.2.x, UploadWorker.done 시그널 회귀 테스트
"""UploadWorker must not shadow QThread.finished with a no-arg Signal."""

from __future__ import annotations

from bpe.gui.workers.upload_worker import UploadWorker


def test_upload_worker_does_not_redefine_finished() -> None:
    """QThread.finished() 와 이름·시그니처가 겹치면 완료 콜백이 두 번 호출됨."""
    assert "finished" not in UploadWorker.__dict__


def test_upload_worker_has_done_signal() -> None:
    assert "done" in UploadWorker.__dict__
    assert hasattr(UploadWorker, "done")
    assert hasattr(UploadWorker, "error")
    assert hasattr(UploadWorker, "progress")
    assert hasattr(UploadWorker, "status")
