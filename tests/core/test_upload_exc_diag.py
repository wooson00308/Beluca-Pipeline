"""Tests for bpe.core.upload_exc_diag."""

from __future__ import annotations

from urllib.error import URLError

from bpe.core.upload_exc_diag import sg_upload_exception_diag


def test_plain_exception() -> None:
    d = sg_upload_exception_diag(RuntimeError("boom"))
    assert d["exc_type"] == "RuntimeError"
    assert "boom" in d["exc_msg"]
    assert "chain_type" not in d


def test_urllib_error_with_reason() -> None:
    e = URLError(OSError(22, "errno message"))
    d = sg_upload_exception_diag(e)
    assert d["exc_type"] == "URLError"
    assert d["reason_type"] == "OSError"
    assert "errno message" in d["reason_msg"] or "22" in d["reason_msg"]


def test_chain_from_cause() -> None:
    inner = ValueError("inner detail")
    try:
        raise RuntimeError("outer") from inner
    except RuntimeError as outer:
        d = sg_upload_exception_diag(outer)
    assert d["exc_type"] == "RuntimeError"
    assert d.get("chain_type") == "ValueError"
    assert "inner detail" in d.get("chain_msg", "")


def test_clip_long_message() -> None:
    long_msg = "x" * 600
    d = sg_upload_exception_diag(ValueError(long_msg), msg_max=100)
    assert len(d["exc_msg"]) == 100
