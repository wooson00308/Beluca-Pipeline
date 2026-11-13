"""Tests for bpe.core.lut_cube — .cube 룩업 읽기."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.core.lut_cube import identity_lut, load_cube, parse_cube, sample_nearest

_CUBE_2 = """# comment
TITLE "half"
LUT_3D_SIZE 2
DOMAIN_MIN 0 0 0
DOMAIN_MAX 1 1 1
0 0 0
0.5 0 0
0 0.5 0
0.5 0.5 0
0 0 0.5
0.5 0 0.5
0 0.5 0.5
0.5 0.5 0.5
"""


def test_parse_basic_cube() -> None:
    lut = parse_cube(_CUBE_2)
    assert lut is not None
    assert lut.size == 2 and lut.title == "half"
    assert len(lut.data) == 24
    assert len(lut.tobytes()) == 24 * 4
    # r 이 가장 빨리 도는 순서
    assert sample_nearest(lut, (1.0, 0.0, 0.0)) == pytest.approx((0.5, 0.0, 0.0))
    assert sample_nearest(lut, (1.0, 1.0, 1.0)) == pytest.approx((0.5, 0.5, 0.5))


def test_identity() -> None:
    lut = identity_lut(3)
    assert lut.size == 3
    assert sample_nearest(lut, (0.5, 1.0, 0.0)) == pytest.approx((0.5, 1.0, 0.0))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "LUT_1D_SIZE 4\n0 0 0\n",
        "LUT_3D_SIZE 2\n0 0 0\n",  # 값이 모자람
        "LUT_3D_SIZE 2\n0 0 x\n",
        "LUT_3D_SIZE 999\n",
    ],
)
def test_bad_cube_is_none(text: str) -> None:
    assert parse_cube(text) is None


def test_load_cube_file_and_missing(tmp_path: Path) -> None:
    p = tmp_path / "a.cube"
    p.write_text(_CUBE_2, encoding="utf-8")
    assert load_cube(p) is not None
    assert load_cube(tmp_path / "none.cube") is None


def test_unknown_keywords_are_skipped() -> None:
    lut = parse_cube(_CUBE_2.replace("DOMAIN_MAX 1 1 1", "DOMAIN_MAX 1 1 1\nLUT_IN_VIDEO_RANGE"))
    assert lut is not None
