"""Tests for bpe.core.confirm_look — 영상에 룩이 입혀졌는지를 그림으로 가르기."""

from __future__ import annotations

import struct
from array import array
from typing import List, Tuple

from bpe.core.confirm_look import judge_look, sample_grid, sample_trilinear
from bpe.core.lut_cube import CubeLut, identity_lut

RGB = Tuple[float, float, float]


def _contrast_lut(size: int = 9) -> CubeLut:
    """로그 그림을 진하게 만드는 룩업 흉내 — 대비를 키우고 채도를 올린다."""
    data = array("f")
    for b in range(size):
        for g in range(size):
            for r in range(size):
                v = [r / (size - 1), g / (size - 1), b / (size - 1)]
                mean = sum(v) / 3.0
                out = [min(1.0, max(0.0, (mean + (c - mean) * 1.8 - 0.35) * 2.2)) for c in v]
                data.extend(out)
    return CubeLut(size, data, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), "contrast")


def _log_plate(n: int = 200) -> List[RGB]:
    """로그 영상처럼 가운데 밝기에 몰려 있고 색이 옅은 점들."""
    out: List[RGB] = []
    for i in range(n):
        base = 0.30 + 0.35 * ((i * 37) % 100) / 100.0
        out.append(
            (base + 0.03 * ((i * 7) % 5 - 2) / 2, base, base - 0.02 * ((i * 11) % 5 - 2) / 2)
        )
    return out


def _frame(samples: List[RGB], width: int, height: int) -> bytes:
    px = [samples[i % len(samples)] for i in range(width * height)]
    return b"".join(struct.pack("<3H", *(int(round(c * 65535)) for c in p)) for p in px)


def test_log_work_is_told_apart_from_baked_work() -> None:
    lut = _contrast_lut()
    plate = _log_plate()
    baked = [sample_trilinear(lut, p) for p in plate]
    # 합성으로 일부가 바뀌고 그레인이 조금 달라도 가를 수 있다
    log_work = [(r + 0.004, g - 0.003, b) for r, g, b in plate]
    log_work[:20] = [(0.9, 0.2, 0.2)] * 20
    assert judge_look(log_work, plate, lut).baked is False
    baked_work = [(min(1.0, r + 0.004), g, b) for r, g, b in baked]
    baked_work[:20] = [(0.9, 0.2, 0.2)] * 20
    assert judge_look(baked_work, plate, lut).baked is True


def test_undecided_when_lut_changes_nothing_or_picture_is_unrelated() -> None:
    plate = _log_plate()
    assert judge_look(plate, plate, identity_lut(2)).baked is None  # 룩업이 아무것도 안 바꿈
    lut = _contrast_lut()
    unrelated = [(0.98, 0.02, 0.98)] * len(plate)  # 전혀 다른 그림
    assert judge_look(unrelated, plate, lut).baked is None
    assert judge_look([], plate, lut).baked is None


def test_trilinear_matches_grid_points_and_blends_between() -> None:
    lut = identity_lut(3)
    assert sample_trilinear(lut, (0.5, 0.0, 1.0)) == (0.5, 0.0, 1.0)
    got = sample_trilinear(lut, (0.25, 0.6, 0.9))
    assert all(abs(a - b) < 1e-6 for a, b in zip(got, (0.25, 0.6, 0.9)))
    assert sample_trilinear(lut, (-1.0, 2.0, 0.5)) == (0.0, 1.0, 0.5)  # 범위 밖은 끝값


def test_sample_grid_reads_16bit_rgb() -> None:
    w, h = 8, 4
    data = _frame([(0.25, 0.5, 0.75)], w, h)
    pts = sample_grid(data, w, h, cols=4, rows=2)
    assert len(pts) == 8
    assert all(abs(p[0] - 0.25) < 1e-4 and abs(p[2] - 0.75) < 1e-4 for p in pts)
    assert sample_grid(data[:10], w, h) == []  # 모자란 바이트
    assert sample_grid(data, 0, 4) == []
