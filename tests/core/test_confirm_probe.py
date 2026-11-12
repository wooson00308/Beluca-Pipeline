"""Tests for bpe.core.confirm_probe — 영상 규격 읽기(실패는 None, 가짜 값 금지)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import bpe.core.confirm_probe as cp
from bpe.core.confirm_probe import parse_ffprobe_json, parse_rate, probe_video

_PRORES = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "prores",
            "profile": "HQ",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv422p10le",
            "r_frame_rate": "24000/1001",
            "avg_frame_rate": "24000/1001",
            "nb_frames": "74",
            "color_space": "bt709",
            "tags": {"timecode": "22:31:47:17"},
        }
    ]
}


def test_parse_rate() -> None:
    assert parse_rate("24000/1001") == pytest.approx(23.976, abs=0.001)
    assert parse_rate("24") == 24.0
    assert parse_rate("0/0") is None
    assert parse_rate("") is None
    assert parse_rate("abc") is None


def test_parse_prores_stream() -> None:
    info = parse_ffprobe_json(json.dumps(_PRORES))
    assert info is not None
    assert (info.width, info.height, info.frame_count) == (1920, 1080, 74)
    assert info.fps == pytest.approx(23.976, abs=0.001)
    assert (info.codec, info.profile, info.pix_fmt) == ("prores", "HQ", "yuv422p10le")
    assert info.color_space == "bt709"
    assert info.timecode == "22:31:47:17"
    assert info.has_alpha is False


def test_missing_frame_count_is_none_not_a_guess() -> None:
    payload = {"streams": [dict(_PRORES["streams"][0], nb_frames="N/A")]}
    info = parse_ffprobe_json(json.dumps(payload))
    assert info is not None
    assert info.frame_count is None


def test_alpha_pix_fmt() -> None:
    payload = {"streams": [dict(_PRORES["streams"][0], pix_fmt="yuva444p12le")]}
    info = parse_ffprobe_json(json.dumps(payload))
    assert info is not None and info.has_alpha is True


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", '{"streams": []}', '{"streams": [{"width": 0, "height": 0}]}'],
)
def test_unreadable_output_is_none(text: str) -> None:
    assert parse_ffprobe_json(text) is None


def test_probe_without_ffprobe_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "resolve_ffprobe", lambda: None)
    assert probe_video("x.mov") is None


def test_probe_failure_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run(*_a: object, **_k: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(cp.subprocess, "run", _run)
    assert probe_video("x.mov", ffprobe="ffprobe") is None


def test_probe_success_parses_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}

    def _run(cmd: list, **_k: object) -> subprocess.CompletedProcess:
        seen["cmd"] = cmd
        out = json.dumps(_PRORES).encode("utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr=b"")

    monkeypatch.setattr(cp.subprocess, "run", _run)
    info = probe_video(str(tmp_path / "a.mov"), ffprobe="ffprobe")
    assert info is not None and info.frame_count == 74
    assert seen["cmd"][0] == "ffprobe" and seen["cmd"][-1].endswith("a.mov")
