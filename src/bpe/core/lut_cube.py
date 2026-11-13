"""``.cube`` 3D 룩업 파일 읽기 — 표준 라이브러리만."""

from __future__ import annotations

from array import array
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

RGB = Tuple[float, float, float]
MAX_SIZE = 129


class CubeLut(NamedTuple):
    size: int
    data: array  # float32, r 가 가장 빨리 도는 순서(.cube 순서), 길이 size^3 * 3
    domain_min: RGB
    domain_max: RGB
    title: str

    def tobytes(self) -> bytes:
        return self.data.tobytes()


def identity_lut(size: int = 2) -> CubeLut:
    data = array("f")
    n = max(2, size)
    for b in range(n):
        for g in range(n):
            for r in range(n):
                data.extend((r / (n - 1), g / (n - 1), b / (n - 1)))
    return CubeLut(n, data, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), "identity")


def _triple(parts: List[str]) -> Optional[RGB]:
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except (IndexError, ValueError):
        return None


def parse_cube(text: str) -> Optional[CubeLut]:
    """``.cube`` 본문 → :class:`CubeLut`. 3D 가 아니거나 값 수가 안 맞으면 ``None``."""
    size = 0
    title = ""
    dmin: RGB = (0.0, 0.0, 0.0)
    dmax: RGB = (1.0, 1.0, 1.0)
    values = array("f")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0].upper()
        if key == "TITLE":
            title = line[5:].strip().strip('"')
        elif key == "LUT_3D_SIZE":
            try:
                size = int(parts[1])
            except (IndexError, ValueError):
                return None
        elif key == "LUT_1D_SIZE":
            return None
        elif key == "DOMAIN_MIN":
            dmin = _triple(parts[1:]) or dmin
        elif key == "DOMAIN_MAX":
            dmax = _triple(parts[1:]) or dmax
        elif key[0].isalpha():
            continue
        else:
            t = _triple(parts)
            if t is None:
                return None
            values.extend(t)
    if size < 2 or size > MAX_SIZE or len(values) != size**3 * 3:
        return None
    return CubeLut(size, values, dmin, dmax, title)


def load_cube(path: Path) -> Optional[CubeLut]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return parse_cube(text)


def sample_nearest(lut: CubeLut, rgb: RGB) -> RGB:
    """가장 가까운 격자점 값(테스트·픽셀 값 표시용 근사)."""
    n = lut.size
    idx = []
    for c, lo, hi in zip(rgb, lut.domain_min, lut.domain_max):
        span = (hi - lo) or 1.0
        t = min(1.0, max(0.0, (c - lo) / span))
        idx.append(int(round(t * (n - 1))))
    off = (idx[0] + idx[1] * n + idx[2] * n * n) * 3
    return (lut.data[off], lut.data[off + 1], lut.data[off + 2])
