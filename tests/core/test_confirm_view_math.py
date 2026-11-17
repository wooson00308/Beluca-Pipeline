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
    # 차이는 선형 빛에서 뺀 뒤 게인을 곱하고, 다시 곡선을 입혀 보여 준다(누크 뷰어 순서)
    from bpe.core.confirm_view_math import from_linear, to_linear

    la, lb = to_linear(A), to_linear(B)
    want = from_linear((abs(la[0] - lb[0]) * 4.0,) * 3)[0]
    got = view_pixel(A, B, mode=VIEW_MODE_DIFF, gain=4.0, gamma=1.0, channel=CHANNEL_R)
    assert got == pytest.approx((want, want, want))
    assert view_pixel(A, A, mode=VIEW_MODE_DIFF, gain=64.0, gamma=4.0) == (0.0, 0.0, 0.0)


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


def test_difference_matches_looks_before_subtracting() -> None:
    from bpe.core.confirm_view_math import VIEW_MODE_DIFF, view_pixel

    def look(c: tuple) -> tuple:
        return (c[0] * 2.0, c[1] * 2.0, c[2] * 2.0)

    log_plate = (0.2, 0.2, 0.2)
    baked_work = (0.4, 0.4, 0.4)  # 같은 그림에 룩이 입혀진 것
    # 로그 판에만 룩업을 씌운 뒤 빼면 차이가 0 이다
    assert view_pixel(log_plate, baked_work, mode=VIEW_MODE_DIFF, lut=look) == (0.0, 0.0, 0.0)
    assert view_pixel(baked_work, log_plate, mode=VIEW_MODE_DIFF, lut_b=look) == (0.0, 0.0, 0.0)
    # 아무것도 안 맞추면 색 차이가 그대로 남는다
    raw = view_pixel(log_plate, baked_work, mode=VIEW_MODE_DIFF)
    assert all(c > 0.1 for c in raw)


def test_curves_round_trip_and_match_known_points() -> None:
    from bpe.core.confirm_view_math import CURVE_GAMMA22, CURVE_REC709, from_linear, to_linear

    for curve in (CURVE_REC709, CURVE_GAMMA22):
        for v in (0.0, 0.02, 0.081, 0.18, 0.5, 1.0):
            back = from_linear(to_linear((v, v, v), curve), curve)
            assert back[0] == pytest.approx(v, abs=5e-4)  # 곧은 구간과 굽은 구간이 만나는 곳의 틈
    assert to_linear((0.045, 0.5, 1.0), CURVE_REC709)[0] == pytest.approx(0.01)  # 곧은 구간
    assert to_linear((0.5, 0.5, 0.5), CURVE_GAMMA22)[0] == pytest.approx(0.5**2.2)
    assert to_linear((-0.2, 0.0, 0.0), CURVE_REC709)[0] == 0.0  # 음수는 0


def test_tiny_difference_vanishes_under_the_viewer_lut_like_in_nuke() -> None:
    from bpe.core.confirm_view_math import VIEW_MODE_DIFF, view_pixel

    def log_look(c: tuple) -> tuple:
        # 로그용 룩업 흉내: 0.09 아래는 검정, 그 위로 대비를 키운다
        return tuple(max(0.0, (x - 0.09) * 2.0) for x in c)

    a = (0.400, 0.400, 0.400)
    b = (0.4004, 0.4004, 0.4004)  # 다시 압축해서 생기는 정도의 아주 작은 차이
    # 뷰어 룩업 없이 게인을 크게 주면 회색으로 보인다
    assert view_pixel(a, b, mode=VIEW_MODE_DIFF, gain=16.0)[0] > 0.01
    # 누크처럼 뷰어 룩업을 켠 채 보면 룩업의 검은 쪽에 묻혀 안 보인다
    assert view_pixel(a, b, mode=VIEW_MODE_DIFF, gain=16.0, lut_post=log_look) == (0.0, 0.0, 0.0)
    # 진짜로 다른 곳은 그대로 보인다
    c = (0.55, 0.55, 0.55)
    assert view_pixel(a, c, mode=VIEW_MODE_DIFF, gain=4.0, lut_post=log_look)[0] > 0.5
