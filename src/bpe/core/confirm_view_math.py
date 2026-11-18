"""컨펌 뷰어 보기 계산의 기준식 — GLSL 셰이더(``gui/confirm/viewer_gl.py``)와 같은 식.

화면 없이 도는 테스트의 기준값이고, GL 자가 점검이 기대값을 여기서 구한다.
셰이더 식을 바꾸면 이 모듈도 같이 바꿔야 한다.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

RGB = Tuple[float, float, float]

VIEW_MODE_A = 0
VIEW_MODE_DIFF = 1
VIEW_MODE_B = 2

CHANNEL_RGB = "RGB"
CHANNEL_R = "R"
CHANNEL_G = "G"
CHANNEL_B = "B"
CHANNEL_LUMA = "L"
CHANNELS: Tuple[str, ...] = (CHANNEL_RGB, CHANNEL_R, CHANNEL_G, CHANNEL_B, CHANNEL_LUMA)

LUMA_709: RGB = (0.2126, 0.7152, 0.0722)

_MIN_GAMMA = 1e-6

# 영상에 저장된 값 ↔ 선형 빛. 누크가 MOV 를 읽을 때 쓰는 곡선과 같다.
CURVE_REC709 = "rec709"
CURVE_GAMMA22 = "gamma22"
CURVES: Tuple[str, ...] = (CURVE_REC709, CURVE_GAMMA22)


def curve_index(curve: str) -> int:
    """셰이더 ``curve`` 유니폼 값 (0 Rec.709, 1 Gamma 2.2)."""
    return 1 if curve == CURVE_GAMMA22 else 0


def _to_linear_1(v: float, curve: str) -> float:
    v = max(v, 0.0)
    if curve == CURVE_GAMMA22:
        return v**2.2
    return v / 4.5 if v < 0.081 else ((v + 0.099) / 1.099) ** (1.0 / 0.45)


def _from_linear_1(x: float, curve: str) -> float:
    x = max(x, 0.0)
    if curve == CURVE_GAMMA22:
        return x ** (1.0 / 2.2)
    return x * 4.5 if x < 0.018 else 1.099 * (x**0.45) - 0.099


def to_linear(rgb: RGB, curve: str = CURVE_REC709) -> RGB:
    """저장된 값 → 선형 빛."""
    return (_to_linear_1(rgb[0], curve), _to_linear_1(rgb[1], curve), _to_linear_1(rgb[2], curve))


def from_linear(rgb: RGB, curve: str = CURVE_REC709) -> RGB:
    """선형 빛 → 저장된 값(화면에 내보내는 값)."""
    return (
        _from_linear_1(rgb[0], curve),
        _from_linear_1(rgb[1], curve),
        _from_linear_1(rgb[2], curve),
    )


def channel_index(channel: str) -> int:
    """셰이더 ``channel`` 유니폼 값 (0 RGB, 1 R, 2 G, 3 B, 4 밝기)."""
    try:
        return CHANNELS.index(channel)
    except ValueError:
        return 0


def difference(a: RGB, b: RGB) -> RGB:
    return (abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def apply_gain_gamma(rgb: RGB, gain: float = 1.0, gamma: float = 1.0) -> RGB:
    """게인을 곱한 뒤 감마(1/gamma 제곱). 음수는 0 으로 자른다."""
    inv = 1.0 / max(float(gamma), _MIN_GAMMA)
    return (
        max(rgb[0] * gain, 0.0) ** inv,
        max(rgb[1] * gain, 0.0) ** inv,
        max(rgb[2] * gain, 0.0) ** inv,
    )


def select_channel(rgb: RGB, channel: str) -> RGB:
    if channel == CHANNEL_R:
        return (rgb[0], rgb[0], rgb[0])
    if channel == CHANNEL_G:
        return (rgb[1], rgb[1], rgb[1])
    if channel == CHANNEL_B:
        return (rgb[2], rgb[2], rgb[2])
    if channel == CHANNEL_LUMA:
        y = rgb[0] * LUMA_709[0] + rgb[1] * LUMA_709[1] + rgb[2] * LUMA_709[2]
        return (y, y, y)
    return rgb


def view_pixel(
    a: RGB,
    b: RGB,
    *,
    mode: int = VIEW_MODE_A,
    gain: float = 1.0,
    gamma: float = 1.0,
    channel: str = CHANNEL_RGB,
    lut: Optional[Callable[[RGB], RGB]] = None,
    lut_b: Optional[Callable[[RGB], RGB]] = None,
    lut_post: Optional[Callable[[RGB], RGB]] = None,
    curve: str = CURVE_REC709,
) -> RGB:
    """한 픽셀의 화면 값: 보기 판 고르기 → 게인 → 룩업 → 감마 → 채널.

    차이 보기는 누크 뷰어와 같은 순서로 계산한다:
    (판마다 색 상태를 맞춤: *lut* 는 A 판, *lut_b* 는 B 판에 먼저 씌우는 룩업)
    → 선형 빛으로 바꿔 뺀다 → 게인 → 감마 → 다시 곡선을 입힌다 → 뷰어 룩업(*lut_post*).
    두 판이 다 로그면 먼저 씌우는 룩업 없이 빼고 마지막에 뷰어 룩업만 씌운다(누크에서 룩업을
    켠 채 Difference 를 보는 것과 같다 — 아주 작은 차이는 룩업의 검은 쪽에 묻혀 안 보인다).
    """
    if mode == VIEW_MODE_DIFF:
        la = to_linear(lut(a) if lut is not None else a, curve)
        lb = to_linear(lut_b(b) if lut_b is not None else b, curve)
        d = apply_gain_gamma(difference(la, lb), gain, gamma)
        out = from_linear(d, curve)
        if lut_post is not None:
            out = lut_post(out)
        return select_channel(out, channel)
    elif mode == VIEW_MODE_B:
        c = b
    else:
        c = a
    c = (c[0] * gain, c[1] * gain, c[2] * gain)
    if lut is not None and mode != VIEW_MODE_DIFF:
        c = lut(c)
    return select_channel(apply_gain_gamma(c, 1.0, gamma), channel)


def fit_rect(src_w: int, src_h: int, dst_w: int, dst_h: int) -> Tuple[int, int, int, int]:
    """*src* 를 비율을 지켜 *dst* 안에 맞춘 사각형 ``(x, y, w, h)`` — 가운데 정렬."""
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return (0, 0, max(dst_w, 0), max(dst_h, 0))
    scale = min(dst_w / src_w, dst_h / src_h)
    w = max(1, int(round(src_w * scale)))
    h = max(1, int(round(src_h * scale)))
    return ((dst_w - w) // 2, (dst_h - h) // 2, w, h)


# 문무 편집본(edit)의 슬레이트 — 위아래 띠 안쪽 그림이 2:1 (1080 줄이면 위아래 60줄씩)
SLATE_ASPECT = 2.0


def slate_bar(width: int, height: int, aspect: float = SLATE_ASPECT) -> float:
    """슬레이트 띠 하나(위 또는 아래)가 그림 높이에서 차지하는 몫(0 ~ 0.5).

    안쪽 그림이 *aspect* 비율이 되게 위아래를 같은 높이로 가린다. 그림이 이미 그보다
    납작하면 가릴 것이 없어 0.
    """
    if width <= 0 or height <= 0 or aspect <= 0:
        return 0.0
    inner = width / aspect
    return max(0.0, min(0.5, (height - inner) / 2.0 / height))
