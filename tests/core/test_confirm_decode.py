"""Tests for bpe.core.confirm_decode — 프레임 풀기 명령·바이트 계산·프레임 번호."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from bpe.core.confirm_decode import (
    build_decode_command,
    estimate_cache_bytes,
    fit_decode_size,
    frame_byte_size,
    frame_to_index,
    index_to_frame,
    read_exact_frames,
)
from bpe.core.ffmpeg_paths import resolve_ffmpeg

_REPO_FFMPEG = Path(__file__).resolve().parents[2] / "installer" / "ffmpeg-bin" / "ffmpeg.exe"


def _ffmpeg() -> Optional[str]:
    found = resolve_ffmpeg()
    if found:
        return found
    return str(_REPO_FFMPEG) if _REPO_FFMPEG.is_file() else None


def test_frame_byte_size() -> None:
    assert frame_byte_size(1920, 1080) == 1920 * 1080 * 6
    assert frame_byte_size(1920, 1080, alpha=True) == 1920 * 1080 * 8
    assert frame_byte_size(0, 1080) == 0


def test_estimate_cache_bytes_matches_measured_clip() -> None:
    # 2026-11-13 실측: 1080p 74프레임 16비트 = 921 MB
    assert estimate_cache_bytes(1920, 1080, 74) == 920_678_400


def test_fit_decode_size_keeps_small_and_shrinks_big() -> None:
    assert fit_decode_size(1920, 1080, 1920, 1080) == (1920, 1080)
    w, h = fit_decode_size(3840, 2076, 1920, 1080)
    assert (w, h) == (1920, 1038)
    assert w % 2 == 0 and h % 2 == 0
    assert fit_decode_size(0, 0, 1920, 1080) == (0, 0)


def test_build_decode_command_always_names_color_matrix() -> None:
    cmd = build_decode_command("ffmpeg", "a.mov")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "scale=iw:ih:in_color_matrix=bt709"
    assert cmd[-4:] == ["rawvideo", "-pix_fmt", "rgb48le", "-"]
    assert "-frames:v" not in cmd
    assert cmd[cmd.index("-fps_mode") + 1] == "passthrough"


def test_build_decode_command_size_start_count_alpha() -> None:
    cmd = build_decode_command(
        "ffmpeg", "a.mov", width=960, height=540, start_index=40, frame_count=1, alpha=True
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "select=gte(n\\,40),scale=960:540:in_color_matrix=bt709"
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgba64le"


def test_read_exact_frames_splits_and_drops_partial_tail() -> None:
    stream = io.BytesIO(b"aaaabbbbcc")
    assert list(read_exact_frames(stream, 4)) == [b"aaaa", b"bbbb"]
    assert list(read_exact_frames(io.BytesIO(b"abc"), 0)) == []


def test_read_exact_frames_handles_short_reads() -> None:
    class Drip(io.RawIOBase):
        def __init__(self, data: bytes) -> None:
            self._data = data

        def readable(self) -> bool:
            return True

        def read(self, n: int = -1) -> bytes:
            out, self._data = self._data[:1], self._data[1:]
            return out

    assert list(read_exact_frames(Drip(b"abcdef"), 3)) == [b"abc", b"def"]  # type: ignore[arg-type]


def test_frame_number_conversion() -> None:
    assert frame_to_index(1015, 1001) == 14
    assert index_to_frame(14, 1001) == 1015
    assert index_to_frame(frame_to_index(1001, 1001), 1001) == 1001


def test_real_ffmpeg_start_index_is_frame_accurate(tmp_path: Path) -> None:
    """실제 ffmpeg: start_index·frame_count 로 뽑은 프레임이 전체에서 자른 것과 같다."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg 가 없는 환경")
    src = tmp_path / "numbered.mov"
    made = subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc=size=64x48:rate=24:duration=0.5",
            "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", str(src),
        ],
        capture_output=True,
    )  # fmt: skip
    if made.returncode != 0 or not src.is_file():
        pytest.skip("시험 영상을 만들 수 없는 ffmpeg")

    size = frame_byte_size(64, 48)
    full = subprocess.run(build_decode_command(ffmpeg, str(src)), capture_output=True).stdout
    frames = list(read_exact_frames(io.BytesIO(full), size))
    assert len(frames) == 12
    assert len({bytes(f) for f in frames}) == 12  # 프레임마다 그림이 달라야 번호 검증이 된다

    part = subprocess.run(
        build_decode_command(ffmpeg, str(src), start_index=3, frame_count=4), capture_output=True
    ).stdout
    got = list(read_exact_frames(io.BytesIO(part), size))
    assert got == frames[3:7]
