"""Annotation 에서 샷의 글 칸(VFX work order · Description)에 적용할 글 다루기 (표준 라이브러리만).

칸에는 샷그리드에 지금 적혀 있는 글을 불러와 보여 주고, 고친 그대로 적용한다 — 지우고 새로
쓰면 새 글이, 그대로 두고 덧붙이면 덧붙인 글이 들어간다(2026-11-17 밤 결정. 그 전에는 늘 뒤에
덧붙이기만 했다).
"""

from __future__ import annotations

from typing import List, Tuple

KIND_WORK_ORDER = "work_order"
KIND_DESCRIPTION = "description"
KINDS: Tuple[str, ...] = (KIND_WORK_ORDER, KIND_DESCRIPTION)
KIND_LABELS = {KIND_WORK_ORDER: "워크오더", KIND_DESCRIPTION: "디스크립션"}
# 목록·열린 샷의 줄에서 그 칸의 글이 들어 있는 자리
KIND_ROW_KEYS = {KIND_WORK_ORDER: "vfx_work_order", KIND_DESCRIPTION: "shot_description"}

# 워크오더에 타이핑 없이 넣는 말 — 문무 샷그리드에서 실제로 많이 쓴 말에 COMP·FX 를 더했다.
# 모두 같은 목록을 쓴다(같은 말이 `2d 합성` / `2D 합성` 처럼 달리 적히지 않게).
WORK_ORDER_CHIPS: Tuple[str, ...] = (
    "리무브",
    "2D 합성",
    "2D 피추가",
    "2D 화살",
    "AI",
    "ENV",
    "CROWD",
    "MATTE",
    "SIM",
    "지도",
    "NOCG",
    "COMP",
    "FX",
)

_CR = chr(13)
_LF = chr(10)


def _lines(text: str) -> List[str]:
    return str(text or "").replace(_CR + _LF, _LF).replace(_CR, _LF).split(_LF)


def clean_text(text: str) -> str:
    """적용할 글 다듬기 — 줄 끝 빈칸을 떼고, 앞뒤의 빈 줄을 뺀다(가운데 빈 줄은 둔다)."""
    rows = [r.rstrip() for r in _lines(text)]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return _LF.join(rows)


def same_text(a: str, b: str) -> bool:
    """두 글이 같은 글인가 — 줄 바꿈 표기·줄 끝 빈칸·앞뒤 빈 줄만 다르면 같다고 본다."""
    return clean_text(a) == clean_text(b)


def has_line(text: str, line: str) -> bool:
    want = line.strip()
    return bool(want) and any(r.strip() == want for r in _lines(text))


def toggle_line(text: str, line: str) -> str:
    """단추를 눌렀을 때 — 그 말이 한 줄로 없으면 끝에 넣고, 있으면 그 줄을 뺀다."""
    want = line.strip()
    if not want:
        return str(text or "")
    rows = _lines(text)
    if any(r.strip() == want for r in rows):
        kept = [r for r in rows if r.strip() != want]
        return clean_text(_LF.join(kept))
    body = clean_text(str(text or ""))
    return (body + _LF if body else "") + want
