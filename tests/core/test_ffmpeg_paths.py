"""Tests for bpe.core.ffmpeg_paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import bpe.core.ffmpeg_paths as ffmpeg_paths
from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe


def _patch_no_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_paths.shutil, "which", lambda *_a, **_k: None)


def _ffmpeg_name() -> str:
    return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def _ffprobe_name() -> str:
    return "ffprobe.exe" if sys.platform == "win32" else "ffprobe"


def test_resolve_explicit_ffmpeg_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_no_which(monkeypatch)
    p = tmp_path / _ffmpeg_name()
    p.write_bytes(b"\0")
    monkeypatch.setenv("FFMPEG_PATH", str(p))
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    assert resolve_ffmpeg() == str(p.resolve())
    assert resolve_ffprobe() is None


def test_resolve_bpe_ffmpeg_bin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_no_which(monkeypatch)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ff = bindir / _ffmpeg_name()
    fp = bindir / _ffprobe_name()
    ff.write_bytes(b"\0")
    fp.write_bytes(b"\0")
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    monkeypatch.setenv("BPE_FFMPEG_BIN", str(bindir))
    assert resolve_ffmpeg() == str(ff.resolve())
    assert resolve_ffprobe() == str(fp.resolve())


def test_resolve_meipass_when_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_no_which(monkeypatch)
    meipass = tmp_path / "m"
    meipass.mkdir()
    ff = meipass / _ffmpeg_name()
    fp = meipass / _ffprobe_name()
    ff.write_bytes(b"\0")
    fp.write_bytes(b"\0")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    monkeypatch.delenv("BPE_FFMPEG_BIN", raising=False)
    assert resolve_ffmpeg() == str(ff.resolve())
    assert resolve_ffprobe() == str(fp.resolve())
