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


def test_codec_label_reads_like_a_person_would_say_it() -> None:
    from bpe.core.confirm_probe import VideoInfo, codec_label

    def info(codec: str, profile: str) -> VideoInfo:
        return VideoInfo(1920, 1080, 24.0, 10, codec, profile, "yuv422p10le", "", "")

    assert codec_label(info("prores", "HQ")) == "ProRes 422 HQ"
    assert codec_label(info("prores", "Standard")) == "ProRes 422"
    assert codec_label(info("prores", "4444")) == "ProRes 4444"
    assert codec_label(info("prores", "")) == "ProRes"
    assert codec_label(info("h264", "High")) == "H.264 High"
    assert codec_label(info("dnxhd", "")) == "DNxHD"
    assert codec_label(info("", "")) == ""


# ── 2026-11-18 추가: 중간에 끊긴 MOV 알아채기 ──────────────────────────────


def _box(kind: bytes, body: bytes) -> bytes:
    import struct

    return struct.pack(">I4s", 8 + len(body), kind) + body


def _mov(mdat_declared: int, mdat_written: int) -> bytes:
    """목차(moov)가 앞에 있는 작은 MOV 흉내 — mdat 는 적힌 크기와 실제 쓴 크기를 따로 준다."""
    import struct

    head = _box(b"ftyp", b"qt  " + bytes(4)) + _box(b"moov", bytes(40)) + _box(b"wide", b"")
    return head + struct.pack(">I4s", 8 + mdat_declared, b"mdat") + bytes(mdat_written)


def test_whole_mov_has_no_shortfall(tmp_path: Path) -> None:
    f = tmp_path / "ok.mov"
    f.write_bytes(_mov(1000, 1000))
    assert cp.container_shortfall(str(f)) == 0
    # 목차가 뒤에 있는 파일도 멀쩡하면 0
    g = tmp_path / "tail.mov"
    g.write_bytes(_box(b"ftyp", b"qt  ") + _box(b"mdat", bytes(500)) + _box(b"moov", bytes(40)))
    assert cp.container_shortfall(str(g)) == 0


def test_cut_mov_reports_the_missing_bytes(tmp_path: Path) -> None:
    f = tmp_path / "cut.mov"
    f.write_bytes(_mov(1000, 160))  # 보내다 끊긴 파일: 그림 자료가 1000 중 160 만 있다
    assert cp.container_shortfall(str(f)) == 840


def test_big_box_and_run_to_end_box(tmp_path: Path) -> None:
    import struct

    head = _box(b"ftyp", b"qt  ")
    big = tmp_path / "big.mov"  # 크기를 8바이트로 적는 큰 덩어리
    big.write_bytes(head + struct.pack(">I4sQ", 1, b"mdat", 16 + 300) + bytes(100))
    assert cp.container_shortfall(str(big)) == 200
    rest = tmp_path / "rest.mov"  # 크기 0 = 파일 끝까지 → 모자란지 알 수 없다
    rest.write_bytes(head + struct.pack(">I4s", 0, b"mdat") + bytes(100))
    assert cp.container_shortfall(str(rest)) == 0


def test_other_files_are_unknown_not_cut(tmp_path: Path) -> None:
    exr = tmp_path / "a.exr"
    exr.write_bytes(bytes([0x76, 0x2F, 0x31, 0x01]) + bytes(64))
    assert cp.container_shortfall(str(exr)) == 0
    tiny = tmp_path / "tiny.mov"
    tiny.write_bytes(b"ftyp")
    assert cp.container_shortfall(str(tiny)) == 0
    assert cp.container_shortfall(str(tmp_path / "none.mov")) == 0


def test_probe_marks_a_cut_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "cut.mov"
    f.write_bytes(_mov(1000, 160))

    def _run(cmd: list, **kw: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_PRORES).encode(), stderr=b"")

    monkeypatch.setattr(cp.subprocess, "run", _run)
    info = probe_video(str(f), ffprobe="ffprobe")
    assert info is not None and info.is_cut
    assert info.bytes_missing == 840 and info.bytes_present == f.stat().st_size
    assert info.frame_count == 74  # 머리 글의 프레임 수는 끊긴 파일에서도 그대로 읽힌다
    # 멀쩡한 파일은 표시가 없다
    g = tmp_path / "ok.mov"
    g.write_bytes(_mov(1000, 1000))
    ok = probe_video(str(g), ffprobe="ffprobe")
    assert ok is not None and not ok.is_cut and ok.bytes_missing == 0
