"""추석 시즌 장식: 표시 기간·인사말·도트 그림 데이터."""

from __future__ import annotations

from datetime import date, datetime

from bpe.core import seasonal


def test_period_boundaries() -> None:
    assert not seasonal.is_chuseok_active(date(2026, 9, 21))
    assert seasonal.is_chuseok_active(date(2026, 9, 22))
    assert seasonal.is_chuseok_active(date(2026, 9, 25))
    assert seasonal.is_chuseok_active(date(2026, 9, 26))
    assert not seasonal.is_chuseok_active(date(2026, 9, 27))
    assert not seasonal.is_chuseok_active(date(2027, 9, 22))


def test_ms_until_next_midnight() -> None:
    assert seasonal.ms_until_next_midnight(datetime(2026, 9, 26, 23, 59, 59)) == 1000
    assert seasonal.ms_until_next_midnight(datetime(2026, 9, 26, 0, 0, 0)) == 86_400_000


def test_greetings_rotate_in_order() -> None:
    greets = seasonal.CHUSEOK_GREETINGS
    assert len(greets) == 13
    assert len(set(greets)) == 13
    idx = 0
    seen = []
    for _ in range(14):
        seen.append(greets[idx])
        idx = seasonal.next_index(idx, len(greets))
    assert seen[0] == seen[13] == "즐거운 추석 보내세요!"


def test_sprites_are_rectangular_and_use_known_colors() -> None:
    for name, rows in seasonal.CHUSEOK_SPRITES.items():
        assert len({len(r) for r in rows}) == 1, name
        for row in rows:
            for key in row:
                assert key == "." or key in seasonal.CHUSEOK_PALETTE, (name, key)
    for frame in ("up", "mid", "down"):
        rows = seasonal.CHUSEOK_SPRITES[frame]
        assert (len(rows[0]), len(rows)) == (30, 22)


def test_pound_sequence_uses_existing_frames() -> None:
    times = [t for t, _ in seasonal.POUND_SEQUENCE]
    assert times == sorted(times)
    for _, name in seasonal.POUND_SEQUENCE:
        assert name in seasonal.CHUSEOK_SPRITES
