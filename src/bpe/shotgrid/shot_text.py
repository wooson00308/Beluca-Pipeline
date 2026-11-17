"""샷의 글 칸(VFX work order · Description)에 글을 적용한다.

화면의 칸에는 샷그리드의 글을 불러와 두고, 고친 그대로 적용한다. 저장 직전에 샷그리드의
지금 글을 다시 읽어, 화면에 불러와 있던 글과 다르면(그 사이 다른 사람이 고쳤다) 바꾸지 않는다
— 못 본 글을 덮어써 지우지 않는다.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from bpe.core.confirm_shot_text import (
    KIND_DESCRIPTION,
    KIND_LABELS,
    KIND_WORK_ORDER,
    clean_text,
    same_text,
)
from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.tasks import _detect_shot_vfx_field

logger = get_logger("shotgrid.shot_text")

DESCRIPTION_FIELD = "description"


def shot_text_field(sg: Any, kind: str) -> str:
    """*kind* 가 가리키는 샷의 칸 이름. 워크오더 칸은 사이트마다 이름이 달라 스키마에서 찾는다."""
    if kind == KIND_DESCRIPTION:
        return DESCRIPTION_FIELD
    if kind == KIND_WORK_ORDER:
        field = _detect_shot_vfx_field(sg)
        if not field:
            raise ShotGridError("이 샷그리드에서 VFX work order 칸을 찾지 못했습니다")
        return field
    raise ShotGridError(f"알 수 없는 칸입니다: {kind}")


def _read(sg: Any, shot_id: int, field: str) -> str:
    try:
        row = sg.find_one("Shot", [["id", "is", int(shot_id)]], [field])
    except Exception as exc:
        raise ShotGridError(f"샷 정보를 읽지 못했습니다: {exc}") from exc
    if not isinstance(row, dict):
        raise ShotGridError("샷그리드에서 이 샷을 찾지 못했습니다")
    return str(row.get(field) or "")


def read_shot_text(sg: Any, shot_id: int, kind: str) -> str:
    """샷그리드에 지금 적혀 있는 글."""
    return _read(sg, shot_id, shot_text_field(sg, kind))


def apply_shot_text(
    sg: Any, shot_id: int, kind: str, text: str, *, expected: Optional[str] = None
) -> Tuple[bool, str]:
    """샷의 그 칸을 *text* 로 바꾼다 → ``(바꿨나, 샷그리드에 있는 글)``.

    *expected* 는 화면에 불러와 있던 글이다. 저장 직전에 다시 읽은 글이 그것과 다르면 바꾸지
    않고 ``(False, 지금 글)`` 을 돌려준다 — 부른 쪽이 그 글을 다시 보여 주고 확인받는다.
    빈 글을 주면 칸을 비운다.
    """
    field = shot_text_field(sg, kind)
    current = _read(sg, shot_id, field)
    if expected is not None and not same_text(current, expected):
        logger.info("shot text not applied (changed meanwhile): shot=%s field=%s", shot_id, field)
        return False, current
    value = clean_text(text)
    if same_text(current, value):
        return True, current
    try:
        sg.update("Shot", int(shot_id), {field: value})
    except Exception as exc:
        label = KIND_LABELS.get(kind, kind)
        raise ShotGridError(f"{label}를 저장하지 못했습니다: {exc}") from exc
    logger.info(
        "shot text applied: shot=%s field=%s %d자 → %d자", shot_id, field, len(current), len(value)
    )
    return True, value
