"""Tests for bpe.core.confirm_checks — 프레임 수·fps·해상도 판정."""

from __future__ import annotations

from typing import Optional

from bpe.core.confirm_checks import (
    STATE_FAIL,
    STATE_PASS,
    STATE_UNKNOWN,
    check_work_against_reference,
    failure_lines,
    has_failure,
)
from bpe.core.confirm_probe import VideoInfo


def _info(
    w: int = 1920, h: int = 1080, fps: Optional[float] = 23.976, frames: Optional[int] = 74
) -> VideoInfo:
    return VideoInfo(w, h, fps, frames, "prores", "HQ", "yuv422p10le", "bt709", "")


def test_all_pass() -> None:
    res = check_work_against_reference(_info(), _info(), "편집본")
    assert [r.state for r in res] == [STATE_PASS] * 3
    assert res[0].message == "프레임 74/74 통과"
    assert not has_failure(res)


def test_frame_count_mismatch_is_fail_with_both_numbers() -> None:
    res = check_work_against_reference(_info(frames=73), _info(frames=74), "편집본")
    assert res[0].state == STATE_FAIL
    assert res[0].message == "프레임 수 다름: 편집본 74 / 작업본 73"
    assert failure_lines(res) == ["프레임 수 다름: 편집본 74 / 작업본 73"]


def test_fps_tolerance() -> None:
    ok = check_work_against_reference(_info(fps=23.976), _info(fps=23.9760239), "편집본")
    assert ok[1].state == STATE_PASS
    bad = check_work_against_reference(_info(fps=24.0), _info(fps=23.976), "편집본")
    assert bad[1].state == STATE_FAIL and "23.976" in bad[1].message


def test_resolution_mismatch() -> None:
    res = check_work_against_reference(_info(1920, 1080), _info(3840, 2160), "편집본")
    assert res[2].state == STATE_FAIL
    assert "3840×2160" in res[2].message and "1920×1080" in res[2].message


def test_resolution_not_judged_against_plate() -> None:
    res = check_work_against_reference(
        _info(1920, 1080), _info(3840, 2076), "원본", compare_resolution=False
    )
    assert res[2].state == STATE_UNKNOWN
    assert "원본 3840×2076" in res[2].message
    assert not has_failure(res)


def test_unreadable_work_is_unknown_not_pass() -> None:
    res = check_work_against_reference(None, _info(), "편집본")
    assert [r.state for r in res] == [STATE_UNKNOWN] * 3


def test_missing_reference_is_unknown() -> None:
    res = check_work_against_reference(_info(), None, "편집본")
    assert [r.state for r in res] == [STATE_UNKNOWN] * 3
    assert "편집본 없음" in res[0].message


def test_missing_frame_count_is_unknown() -> None:
    res = check_work_against_reference(_info(frames=None), _info(), "편집본")
    assert res[0].state == STATE_UNKNOWN
