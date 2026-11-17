"""컨펌 창 「이어 재생」 — 여러 컷을 한 줄로 이어 볼 때의 순서·위치·그림 크기 계산 (GUI 없음).

이어 재생은 컷마다 줄인 그림을 메모리에 풀어 두고 한 줄로 재생한다. 여기서는
그 한 줄 위의 자리(전체에서 몇 번째 프레임인가)와 컷·프레임 사이를 오가는 계산,
메모리 한도에 맞는 그림 크기 고르기만 한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from bpe.core.confirm_decode import fit_decode_size, frame_byte_size

SEQ_MIN_CUTS = 2
SEQ_MAX_CUTS = 8
# 재생용 그림의 한도(큰 것부터) — 메모리에 다 들어가는 가장 큰 것을 쓴다
SEQ_SIZE_STEPS: Tuple[Tuple[int, int], ...] = ((1280, 720), (960, 540), (640, 360))
# 프레임 메모리 한도 중 이어 재생이 쓰는 몫(나머지는 멈췄을 때 여는 컷의 몫)
SEQ_BUDGET_SHARE = 0.6

Row = Dict[str, Any]


def order_rows(rows: Sequence[Row]) -> List[Row]:
    """이어 볼 컷의 순서 — 샷 이름 순."""
    return sorted(rows, key=lambda r: str(r.get("shot_code") or "").lower())


def toggle_pick(
    picked: Sequence[Any], key: Any, limit: int = SEQ_MAX_CUTS
) -> Tuple[List[Any], bool]:
    """고른 컷 목록에서 *key* 를 넣거나 뺀다. 한도를 넘겨 못 넣었으면 둘째 값이 ``False``."""
    out = list(picked)
    if key in out:
        out.remove(key)
        return out, True
    if len(out) >= limit:
        return out, False
    out.append(key)
    return out, True


def total_frames(counts: Sequence[int]) -> int:
    return sum(max(0, int(c)) for c in counts)


def cut_starts(counts: Sequence[int]) -> List[int]:
    """컷마다 한 줄 위에서 시작하는 자리."""
    out: List[int] = []
    at = 0
    for c in counts:
        out.append(at)
        at += max(0, int(c))
    return out


def position(counts: Sequence[int], cut: int, frame: int) -> int:
    """컷 *cut* 의 *frame* 번째(0부터)가 한 줄 위에서 몇 번째인가."""
    if not counts:
        return 0
    cut = max(0, min(len(counts) - 1, int(cut)))
    last = max(0, int(counts[cut]) - 1)
    return cut_starts(counts)[cut] + max(0, min(last, int(frame)))


def locate(counts: Sequence[int], pos: int) -> Tuple[int, int]:
    """한 줄 위의 자리 → (컷 번호, 그 컷 안의 프레임 번호). 범위를 벗어나면 끝으로 맞춘다."""
    total = total_frames(counts)
    if total <= 0:
        return (0, 0)
    pos = max(0, min(total - 1, int(pos)))
    for cut, start in enumerate(cut_starts(counts)):
        n = max(0, int(counts[cut]))
        if n and pos < start + n:
            return (cut, pos - start)
    return (len(counts) - 1, max(0, int(counts[-1]) - 1))


def next_position(counts: Sequence[int], pos: int, loop: bool) -> Optional[int]:
    """재생에서 다음 자리. 끝에서 *loop* 면 처음으로, 아니면 ``None``(멈춤)."""
    total = total_frames(counts)
    if total <= 0:
        return None
    nxt = int(pos) + 1
    if nxt >= total:
        return 0 if loop else None
    return nxt


def sequence_bytes(sizes: Sequence[Tuple[int, int]], counts: Sequence[int]) -> int:
    """컷마다 그 크기로 전부 풀었을 때 드는 메모리(바이트)."""
    return sum(frame_byte_size(w, h) * max(0, int(c)) for (w, h), c in zip(sizes, counts))


def pick_sizes(
    sources: Sequence[Tuple[int, int]],
    counts: Sequence[int],
    budget_bytes: int,
    steps: Sequence[Tuple[int, int]] = SEQ_SIZE_STEPS,
) -> Optional[List[Tuple[int, int]]]:
    """컷마다 재생용 그림 크기 — 전부가 *budget_bytes* 안에 들어가는 가장 큰 단계.

    *sources* 는 컷마다 영상의 원래 크기. 가장 작은 단계로도 안 들어가면 ``None``.
    """
    for max_w, max_h in steps:
        sizes = [fit_decode_size(w, h, max_w, max_h) for w, h in sources]
        if sequence_bytes(sizes, counts) <= budget_bytes:
            return sizes
    return None
