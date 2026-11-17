"""컨펌 창이 프레임을 메모리에 올리는 한도를 PC 메모리에 맞춰 정한다 (표준 라이브러리만).

한도가 작으면 긴 샷에서 원본·전 버전이 메모리에 다 못 들어가 한 장씩 풀게 되고(재생이 끊긴다),
PC 메모리보다 크면 PC 가 느려진다. 그래서 설정에 값을 적지 않은 PC 는 메모리의 절반을 쓰되
최대 32GB, 최소 4GB(예전 기본값 — 어느 PC 도 전보다 줄지 않는다)로 한다.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

CACHE_MIN_MB = 4096  # 예전 기본값. 메모리를 못 읽었을 때도 이 값
CACHE_MAX_MB = 32768
CACHE_SHARE = 0.5  # PC 메모리 가운데 컨펌 창이 쓸 수 있는 몫

_total_mb: Optional[int] = None
_total_read = False


def _read_total_memory_mb() -> Optional[int]:
    if sys.platform == "win32":
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        total = int(status.ullTotalPhys)
    else:
        total = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    return total // (1024 * 1024) if total > 0 else None


def total_memory_mb() -> Optional[int]:
    """이 PC 의 메모리(MB). 읽지 못하면 ``None``. 한 번 읽은 값은 기억한다."""
    global _total_mb, _total_read
    if not _total_read:
        try:
            _total_mb = _read_total_memory_mb()
        except Exception:  # 메모리를 못 읽어도 창은 떠야 한다
            _total_mb = None
        _total_read = True
    return _total_mb


def auto_cache_mb(total_mb: Optional[int]) -> int:
    """PC 메모리(*total_mb*)에 맞는 한도(MB) — 절반, 최대 32GB · 최소 4GB."""
    if not total_mb or total_mb <= 0:
        return CACHE_MIN_MB
    return max(CACHE_MIN_MB, min(CACHE_MAX_MB, int(total_mb * CACHE_SHARE)))
