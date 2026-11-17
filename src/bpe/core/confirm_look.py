"""컨펌 창 — 영상에 룩(룩업)이 이미 입혀졌는지를 그림으로 가른다 (표준 라이브러리만).

프리셋이나 파일 이름(``_lut``)만으로는 틀릴 때가 있다: 같은 프로젝트에서도 로그 그대로 온
납품본과 룩을 입혀 온 납품본이 섞여 있다. 그래서 같은 샷의 원본(ORG plate, 늘 로그)과
견줘 본다 — 그 영상이 "원본 그대로"에 가까우면 로그, "원본에 룩업을 씌운 것"에 가까우면
룩이 입혀진 것이다. 그림 한 장의 듬성듬성한 점들에서 밝기·대비·채도만 비교하므로,
프레임이 조금 어긋나거나 합성으로 일부가 바뀌어도 가를 수 있다.
"""

from __future__ import annotations

from typing import Any, List, NamedTuple, Optional, Sequence, Tuple

from bpe.core.lut_cube import CubeLut

RGB = Tuple[float, float, float]

_COLS, _ROWS = 24, 14
_MAX16 = 65535.0
_LUMA = (0.2126, 0.7152, 0.0722)
# 두 후보까지의 거리가 이만큼 비슷하면(작은 쪽 / 큰 쪽) 가르지 않는다
_UNSURE_RATIO = 0.75
# 가까운 쪽조차 이보다 멀면 같은 그림이 아니라고 보고 가르지 않는다
_TOO_FAR = 0.60


class LookVerdict(NamedTuple):
    baked: Optional[bool]  # True 룩 입혀짐 · False 로그 그대로 · None 가를 수 없음
    to_plain: float  # "원본 그대로"까지의 거리
    to_lut: float  # "원본 + 룩업"까지의 거리


def sample_grid(
    data: Any, width: int, height: int, *, cols: int = _COLS, rows: int = _ROWS
) -> List[RGB]:
    """16비트 RGB 바이트(``width*height*6``, little-endian)에서 격자 점들의 값(0~1)을 뽑는다."""
    if width <= 0 or height <= 0:
        return []
    view = memoryview(data)
    if len(view) < width * height * 6:
        return []
    out: List[RGB] = []
    for j in range(rows):
        y = min(height - 1, int((j + 0.5) * height / rows))
        for i in range(cols):
            x = min(width - 1, int((i + 0.5) * width / cols))
            o = (y * width + x) * 6
            out.append(
                (
                    (view[o] | (view[o + 1] << 8)) / _MAX16,
                    (view[o + 2] | (view[o + 3] << 8)) / _MAX16,
                    (view[o + 4] | (view[o + 5] << 8)) / _MAX16,
                )
            )
    return out


def sample_trilinear(lut: CubeLut, rgb: RGB) -> RGB:
    """룩업 값 — 둘레 여덟 격자점을 섞은 값(화면의 룩업과 같은 계산)."""
    n = lut.size
    pos: List[Tuple[int, int, float]] = []
    for c, lo, hi in zip(rgb, lut.domain_min, lut.domain_max):
        span = (hi - lo) or 1.0
        t = min(1.0, max(0.0, (c - lo) / span)) * (n - 1)
        i0 = min(n - 2, int(t)) if n > 1 else 0
        pos.append((i0, min(n - 1, i0 + 1), t - i0))
    (r0, r1, fr), (g0, g1, fg), (b0, b1, fb) = pos
    data = lut.data
    acc = [0.0, 0.0, 0.0]
    for bi, wb in ((b0, 1.0 - fb), (b1, fb)):
        for gi, wg in ((g0, 1.0 - fg), (g1, fg)):
            for ri, wr in ((r0, 1.0 - fr), (r1, fr)):
                w = wb * wg * wr
                if w <= 0.0:
                    continue
                off = (ri + gi * n + bi * n * n) * 3
                acc[0] += data[off] * w
                acc[1] += data[off + 1] * w
                acc[2] += data[off + 2] * w
    return (acc[0], acc[1], acc[2])


def _stats(samples: Sequence[RGB]) -> Tuple[float, ...]:
    """밝기·대비·채도를 나타내는 숫자 묶음: 채널 평균 셋, 밝기의 어두운 쪽·밝은 쪽, 채도."""
    n = len(samples)
    if n == 0:
        return ()
    mean = [sum(s[c] for s in samples) / n for c in range(3)]
    luma = sorted(_LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b for r, g, b in samples)
    low = luma[int(0.10 * (n - 1))]
    high = luma[int(0.90 * (n - 1))]
    sat = sum(max(s) - min(s) for s in samples) / n
    return (mean[0], mean[1], mean[2], low, high, high - low, sat)


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def judge_look(work: Sequence[RGB], plate: Sequence[RGB], lut: CubeLut) -> LookVerdict:
    """*work* 가 "원본 그대로"와 "원본 + 룩업" 중 어느 쪽에 가까운가.

    둘 다 비슷하게 가깝거나(룩업이 거의 아무것도 안 바꿈) 둘 다 멀면 ``baked=None``.
    """
    if not work or not plate:
        return LookVerdict(None, 0.0, 0.0)
    w = _stats(work)
    to_plain = _distance(w, _stats(plate))
    to_lut = _distance(w, _stats([sample_trilinear(lut, p) for p in plate]))
    near, far = min(to_plain, to_lut), max(to_plain, to_lut)
    if far <= 1e-9 or near > _TOO_FAR or near / far > _UNSURE_RATIO:
        return LookVerdict(None, to_plain, to_lut)
    return LookVerdict(to_lut < to_plain, to_plain, to_lut)
