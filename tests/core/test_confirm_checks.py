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
from bpe.core.confirm_standard import ProjectStandard


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


# ── 프리셋 기준 ──────────────────────────────────────────────────


def _standard(**kw: object) -> ProjectStandard:
    base = dict(
        preset="PROJ_001",
        fps=23.976,
        mov_size=(1920, 1080),
        plate_size=(3840, 2076),
        codec="prores",
        look="ACES / Rec.709",
        color_tags=("bt709",),
        viewer="Rec.709 (ACES)",
    )
    base.update(kw)
    return ProjectStandard(**base)  # type: ignore[arg-type]


def test_preset_adds_codec_and_color_checks() -> None:
    res = check_work_against_reference(_info(), _info(), "편집본", standard=_standard())
    assert [r.name for r in res] == ["프레임", "fps", "해상도", "코덱", "색 표시"]
    assert [r.state for r in res] == [STATE_PASS] * 5
    assert res[3].message == "코덱 ProRes 422 HQ 통과" and res[4].message == "색 표시 bt709 통과"


def test_preset_fps_and_size_win_over_the_edit() -> None:
    # 편집본이 24fps·4K 여도 기준은 프리셋(23.976·1920×1080)이다
    res = check_work_against_reference(
        _info(), _info(3840, 2160, fps=24.0), "편집본", standard=_standard()
    )
    assert res[1].state == STATE_PASS and res[2].state == STATE_PASS
    bad = check_work_against_reference(
        _info(2048, 1080, fps=24.0), _info(), "편집본", standard=_standard()
    )
    assert bad[1].message == "fps 다름: 프리셋 23.976 / 작업본 24.000"
    assert bad[2].message == "해상도 다름: 프리셋 1920×1080 / 작업본 2048×1080"


def test_preset_judges_size_even_when_only_the_plate_exists() -> None:
    res = check_work_against_reference(
        _info(), _info(3840, 2076), "원본", compare_resolution=False, standard=_standard()
    )
    assert res[2].state == STATE_PASS


def test_preset_checks_run_without_any_reference_movie() -> None:
    res = check_work_against_reference(_info(), None, "편집본", standard=_standard())
    assert res[0].state == STATE_UNKNOWN and "편집본 없음" in res[0].message
    assert [r.state for r in res[1:]] == [STATE_PASS] * 4


def test_preset_codec_and_color_mismatch() -> None:
    work = VideoInfo(1920, 1080, 23.976, 74, "h264", "High", "yuv420p", "bt2020nc", "")
    res = check_work_against_reference(work, _info(), "편집본", standard=_standard())
    assert res[3].message == "코덱 다름: 프리셋 ProRes / 작업본 H.264 High"
    assert res[4].message == "색 표시 다름: 프리셋 ACES / Rec.709 / 작업본 bt2020nc"
    assert has_failure(res)


def test_missing_color_tag_is_unknown_not_fail() -> None:
    work = VideoInfo(1920, 1080, 23.976, 74, "prores", "HQ", "yuv422p10le", "", "")
    res = check_work_against_reference(work, _info(), "편집본", standard=_standard())
    assert res[4].state == STATE_UNKNOWN and "눈으로 확인" in res[4].message


def test_preset_without_values_falls_back_to_the_reference() -> None:
    empty = _standard(fps=None, mov_size=None, codec="", color_tags=())
    res = check_work_against_reference(_info(fps=24.0), _info(), "편집본", standard=empty)
    assert len(res) == 3
    assert res[1].message == "fps 다름: 편집본 23.976 / 작업본 24.000"


def test_basis_text() -> None:
    from bpe.core.confirm_checks import basis_text

    assert basis_text("편집본", True, None) == "편집본 기준"
    assert basis_text("편집본", True, _standard()) == "프리셋 PROJ_001 · 프레임 수는 편집본"
    assert basis_text("원본", False, _standard()) == "프리셋 PROJ_001 · 프레임 수는 원본 없음"
