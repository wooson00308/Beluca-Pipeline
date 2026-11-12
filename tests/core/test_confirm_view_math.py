"""Tests for bpe.core.confirm_view_math — 컨펌 뷰어 보기 계산의 기준식."""

from __future__ import annotations

import pytest

from bpe.core.confirm_view_math import (
    CHANNEL_B,
    CHANNEL_G,
    CHANNEL_LUMA,
    CHANNEL_R,
    CHANNEL_RGB,
    VIEW_MODE_A,
    VIEW_MODE_B,
    VIEW_MODE_DIFF,
    apply_gain_gamma,
    channel_index,
    difference,
    fit_rect,
    select_channel,
    view_pixel,
)

A = (0.25, 0.25, 0.25)
B = (0.5, 0.3, 0.1)


def test_difference_is_absolute_per_channel() -> None:
    assert difference(A, B) == pytest.approx((0.25, 0.05, 0.15))
    assert difference(B, A) == pytest.approx(difference(A, B))


def test_gain_then_gamma() -> None:
    assert apply_gain_gamma(A, gain=2.0) == pytest.approx((0.5, 0.5, 0.5))
    assert apply_gain_gamma(A, gamma=2.0) == pytest.approx((0.5, 0.5, 0.5))
    # 게인이 먼저, 감마가 나중: (0.25*4) ** (1/2.2) == 1
    assert apply_gain_gamma(A, gain=4.0, gamma=2.2) == pytest.approx((1.0, 1.0, 1.0))


def test_negative_values_clamp_to_zero() -> None:
    assert apply_gain_gamma((-0.5, 0.0, 0.1), gain=1.0, gamma=2.0)[0] == 0.0


def test_gamma_zero_does_not_raise() -> None:
    out = apply_gain_gamma((0.5, 0.5, 0.5), gamma=0.0)
    assert all(v >= 0.0 for v in out)


def test_select_channel() -> None:
    assert select_channel(B, CHANNEL_RGB) == B
    assert select_channel(B, CHANNEL_R) == (0.5, 0.5, 0.5)
    assert select_channel(B, CHANNEL_G) == (0.3, 0.3, 0.3)
    assert select_channel(B, CHANNEL_B) == (0.1, 0.1, 0.1)
    y = 0.5 * 0.2126 + 0.3 * 0.7152 + 0.1 * 0.0722
    assert select_channel(B, CHANNEL_LUMA) == pytest.approx((y, y, y))


def test_view_pixel_order_mode_gain_gamma_channel() -> None:
    assert view_pixel(A, B, mode=VIEW_MODE_A) == A
    assert view_pixel(A, B, mode=VIEW_MODE_B) == B
    got = view_pixel(A, B, mode=VIEW_MODE_DIFF, gain=4.0, gamma=1.0, channel=CHANNEL_R)
    assert got == pytest.approx((1.0, 1.0, 1.0))


def test_channel_index_matches_shader_uniform() -> None:
    assert [channel_index(c) for c in ("RGB", "R", "G", "B", "L")] == [0, 1, 2, 3, 4]
    assert channel_index("없는 채널") == 0


def test_fit_rect_letterbox_and_pillarbox() -> None:
    # 1.85:1 영상을 16:9 창에 → 위아래가 남는다
    x, y, w, h = fit_rect(3840, 2076, 1920, 1080)
    assert (x, w) == (0, 1920)
    assert h == 1038 and y == 21
    # 16:9 영상을 좁고 긴 창에 → 폭에 맞춘다
    assert fit_rect(1920, 1080, 960, 1080) == (0, 270, 960, 540)
    # 16:9 영상을 넓은 창에 → 좌우가 남는다
    assert fit_rect(1920, 1080, 3000, 1080) == (540, 0, 1920, 1080)


def test_fit_rect_bad_sizes() -> None:
    assert fit_rect(0, 0, 100, 50) == (0, 0, 100, 50)
