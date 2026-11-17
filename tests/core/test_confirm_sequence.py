"""이어 재생의 순서·위치·크기 계산."""

from __future__ import annotations

from bpe.core.confirm_decode import frame_byte_size
from bpe.core.confirm_sequence import (
    SEQ_MAX_CUTS,
    cut_starts,
    locate,
    next_position,
    order_rows,
    pick_sizes,
    position,
    sequence_bytes,
    toggle_pick,
    total_frames,
)


def test_rows_play_in_shot_name_order() -> None:
    rows = [{"shot_code": "ep02_s010_0030"}, {"shot_code": "EP01_s020_0010"}, {"shot_code": ""}]
    assert [r["shot_code"] for r in order_rows(rows)] == ["", "EP01_s020_0010", "ep02_s010_0030"]


def test_toggle_pick_adds_removes_and_stops_at_the_limit() -> None:
    picked, ok = toggle_pick([], 1)
    assert (picked, ok) == ([1], True)
    picked, ok = toggle_pick(picked, 2)
    assert picked == [1, 2] and ok
    picked, ok = toggle_pick(picked, 1)
    assert picked == [2] and ok
    full = list(range(SEQ_MAX_CUTS))
    assert toggle_pick(full, 99) == (full, False)  # 한도를 넘으면 안 넣는다
    assert toggle_pick(full, 0) == (full[1:], True)  # 빼는 것은 된다


def test_positions_map_between_the_line_and_cuts() -> None:
    counts = [3, 0, 2]  # 가운데 컷은 프레임이 없다(못 읽은 컷)
    assert total_frames(counts) == 5 and cut_starts(counts) == [0, 3, 3]
    assert [locate(counts, p) for p in range(5)] == [(0, 0), (0, 1), (0, 2), (2, 0), (2, 1)]
    assert locate(counts, -4) == (0, 0) and locate(counts, 99) == (2, 1)
    assert position(counts, 2, 1) == 4 and position(counts, 0, 9) == 2
    assert position(counts, 9, 0) == 3  # 없는 컷 번호는 마지막 컷으로
    assert locate([], 3) == (0, 0) and position([], 1, 1) == 0


def test_next_position_loops_or_stops_at_the_end() -> None:
    counts = [2, 2]
    assert next_position(counts, 0, loop=False) == 1
    assert next_position(counts, 3, loop=True) == 0
    assert next_position(counts, 3, loop=False) is None
    assert next_position([], 0, loop=True) is None


def test_picture_size_is_the_largest_step_that_fits_memory() -> None:
    sources = [(3840, 2160), (1920, 1080)]
    counts = [100, 50]
    big = [(1280, 720), (1280, 720)]
    assert sequence_bytes(big, counts) == frame_byte_size(1280, 720) * 150
    assert pick_sizes(sources, counts, sequence_bytes(big, counts)) == big
    mid = pick_sizes(sources, counts, sequence_bytes(big, counts) - 1)
    assert mid == [(960, 540), (960, 540)]
    assert pick_sizes(sources, counts, 1000) is None  # 가장 작게 해도 안 들어간다
    # 원래 작은 영상은 키우지 않는다
    assert pick_sizes([(640, 360)], [10], 10**12) == [(640, 360)]
