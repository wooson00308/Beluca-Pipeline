"""Tests for bpe.core.confirm_test_pattern — 시험용 16비트 그림."""

from __future__ import annotations

import struct

from bpe.core.confirm_decode import frame_byte_size
from bpe.core.confirm_test_pattern import (
    BLOCK_DELTA,
    block_rect,
    make_test_pattern,
    ramp_value,
    solid_frame,
)

W, H = 64, 36


def _pixel(data: bytes, x: int, y: int) -> tuple:
    off = (y * W + x) * 6
    return struct.unpack_from("<HHH", data, off)


def test_sizes() -> None:
    assert len(make_test_pattern(W, H)) == frame_byte_size(W, H)
    assert len(make_test_pattern(W, H, with_block=True)) == frame_byte_size(W, H)
    assert len(solid_frame(W, H, 0.5)) == frame_byte_size(W, H)


def test_ramp_runs_black_to_white() -> None:
    a = make_test_pattern(W, H)
    assert _pixel(a, 0, 0) == (0, 0, 0)
    assert _pixel(a, W - 1, 0) == (65535, 65535, 65535)


def test_block_differs_only_inside_rect() -> None:
    a = make_test_pattern(W, H)
    b = make_test_pattern(W, H, with_block=True)
    x0, y0, x1, y1 = block_rect(W, H)
    inside = _pixel(b, (x0 + x1) // 2, (y0 + y1) // 2)
    base = _pixel(a, (x0 + x1) // 2, (y0 + y1) // 2)
    want = round((ramp_value((x0 + x1) // 2, W) + BLOCK_DELTA) * 65535)
    assert inside[0] == want and inside[0] > base[0]
    assert _pixel(b, 0, 0) == _pixel(a, 0, 0)
    assert _pixel(b, x0 - 1, y0) == _pixel(a, x0 - 1, y0)
    assert _pixel(b, x0, y1) == _pixel(a, x0, y1)
    # 색 막대 구간은 A·B 가 같다
    assert a[-W * 6 :] == b[-W * 6 :]


def test_solid_frame_value() -> None:
    assert _pixel(solid_frame(W, H, 0.25), 10, 10) == (16384, 16384, 16384)
