"""컨펌 창 시험용 그림 — 16비트 RGB 바이트(``rgb48le`` 와 같은 모양).

A: 위쪽은 회색 단계, 아래쪽은 색 막대.
B: A 와 같지만 가운데 네모만 아주 조금 밝다 — 맨눈으로는 안 보이고, 차이 보기를 켜고
   게인을 올려야 보인다(컨펌에서 실제로 쓰는 방식 그대로).
"""

from __future__ import annotations

import sys
from array import array
from typing import List, Tuple

_MAX = 65535
_BARS: Tuple[Tuple[float, float, float], ...] = (
    (0.75, 0.75, 0.75),
    (0.75, 0.75, 0.0),
    (0.0, 0.75, 0.75),
    (0.0, 0.75, 0.0),
    (0.75, 0.0, 0.75),
    (0.75, 0.0, 0.0),
    (0.0, 0.0, 0.75),
    (0.1, 0.1, 0.1),
)
BLOCK_DELTA = 0.02


def _u16(v: float) -> int:
    return max(0, min(_MAX, int(round(v * _MAX))))


def _to_bytes(row: array) -> bytes:
    if sys.byteorder != "little":
        row = array("H", row)
        row.byteswap()
    return row.tobytes()


def block_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """B 에서 밝기가 다른 네모 ``(x0, y0, x1, y1)`` (끝 미포함)."""
    return (width * 3 // 8, height // 6, width * 5 // 8, height // 2)


def ramp_value(x: int, width: int) -> float:
    """회색 단계 구간의 (x) 값 0..1."""
    return x / max(1, width - 1)


def make_test_pattern(width: int, height: int, *, with_block: bool = False) -> bytes:
    """``width*height*6`` 바이트. *with_block* 이면 가운데 네모가 ``BLOCK_DELTA`` 만큼 밝다."""
    ramp = array("H")
    for x in range(width):
        v = _u16(ramp_value(x, width))
        ramp.extend((v, v, v))
    bars = array("H")
    n = len(_BARS)
    for x in range(width):
        r, g, b = _BARS[min(n - 1, x * n // max(1, width))]
        bars.extend((_u16(r), _u16(g), _u16(b)))

    x0, y0, x1, y1 = block_rect(width, height)
    ramp_block = array("H", ramp)
    if with_block:
        for x in range(x0, x1):
            v = _u16(ramp_value(x, width) + BLOCK_DELTA)
            ramp_block[x * 3] = v
            ramp_block[x * 3 + 1] = v
            ramp_block[x * 3 + 2] = v

    ramp_b, bars_b, block_b = _to_bytes(ramp), _to_bytes(bars), _to_bytes(ramp_block)
    split = height * 2 // 3
    rows: List[bytes] = []
    for y in range(height):
        if y >= split:
            rows.append(bars_b)
        elif with_block and y0 <= y < y1:
            rows.append(block_b)
        else:
            rows.append(ramp_b)
    return b"".join(rows)


def solid_frame(width: int, height: int, value: float) -> bytes:
    """한 가지 회색으로 채운 프레임."""
    v = _u16(value)
    return _to_bytes(array("H", (v, v, v) * width)) * height
