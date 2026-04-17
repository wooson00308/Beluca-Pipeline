"""Tests for bpe.core.shotgun_upload_trace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bpe.core import shotgun_upload_trace as sut


def test_upload_source_path_meta(tmp_path: Path) -> None:
    f = tmp_path / "a.mov"
    f.write_bytes(b"12")
    m = sut.upload_source_path_meta(str(f))
    assert m["path_basename"] == "a.mov"
    assert m["exists"] is True
    assert m["size_bytes"] == 2


def test_exception_trace_preview() -> None:
    try:
        raise ValueError("x") from OSError("y")
    except ValueError as e:
        s = sut.exception_trace_preview(e, max_len=5000)
    assert "ValueError" in s
    assert "x" in s


def test_ensure_trace_idempotent_when_disabled() -> None:
    os.environ.pop("BPE_SHOTGUN_UPLOAD_TRACE", None)
    assert sut.is_shotgun_upload_trace_enabled() is False
    sut.ensure_shotgun_upload_trace_logging_configured()
    sut.ensure_shotgun_upload_trace_logging_configured()


def test_upload_trace_explicit_off_overrides_bpe_dev(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BPE_SHOTGUN_UPLOAD_TRACE", "0")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "BPE_dev.exe"))
    assert sut.is_shotgun_upload_trace_enabled() is False


def test_upload_trace_auto_on_bpe_dev_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BPE_SHOTGUN_UPLOAD_TRACE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "BPE_dev.exe"))
    assert sut.is_shotgun_upload_trace_enabled() is True
