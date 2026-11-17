"""Annotation 노트를 샷그리드의 guide 봇이 집어 갈 수 있는 꼴로 맞추는 규칙 (표준 라이브러리만).

샷그리드에서 직접 그림을 그려 올린 노트는 edit·org 버전에 붙고, 그림 이름이
``annot_version_<버전 번호>.<프레임 순번>.png`` 이다. 봇(beluca_feedback_bot)은 그런 노트의 그림을
guide 태스크의 버전으로 옮겨 샷 목록의 guide 칸에 보이게 한다(2026-11-17 조회로 추정한 조건).
우리 창이 보내는 노트도 같은 자리에 붙이고 같은 이름으로 올린다.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bpe.core.confirm_annotations import SOURCE_EDIT, SOURCE_PLATE

TASK_EDIT = "edit"
TASK_PLATE = "org"
SOURCE_TASKS: Dict[str, str] = {SOURCE_EDIT: TASK_EDIT, SOURCE_PLATE: TASK_PLATE}

Version = Dict[str, Any]


def annot_file_name(version_id: int, index: int) -> str:
    """샷그리드가 그림에 붙이는 이름 꼴 — 프레임 순번은 그 영상의 0부터 센 자리."""
    return f"annot_version_{int(version_id)}.{max(0, int(index))}.png"


def annot_file_names(version_id: int, indexes: Sequence[int]) -> List[str]:
    """그림 여러 장의 이름. 순번이 겹치면(edit 과 원본의 같은 자리) 뒤 것을 다음 빈 번호로 민다."""
    used: set = set()
    out: List[str] = []
    for raw in indexes:
        i = max(0, int(raw))
        while i in used:
            i += 1
        used.add(i)
        out.append(annot_file_name(version_id, i))
    return out


def _code_key(text: Any) -> str:
    return str(text or "").strip().lower()


def match_version(versions: Iterable[Version], task: str, code: str = "") -> Optional[Version]:
    """*task*(edit / org) 태스크의 버전 가운데 이 영상 파일의 것을 고른다.

    파일 이름(*code*)과 같은 이름의 버전이 있으면 그것, 없으면 그 태스크의 가장 최근 버전.
    *versions* 는 최근 것이 앞에 오게 정렬돼 있다고 본다. 하나도 없으면 ``None``.
    """
    rows = [v for v in versions if _code_key(v.get("task")) == _code_key(task)]
    want = _code_key(code)
    if want:
        for v in rows:
            if _code_key(v.get("code")) == want:
                return v
    return rows[0] if rows else None


def pick_note_version(
    drawn: Iterable[str],
    shown: str,
    found: Dict[str, Optional[Version]],
) -> Tuple[str, Optional[Version]]:
    """노트를 붙일 버전 → ``(영상, 버전)``.

    - edit 에 그린 그림이 하나라도 있으면 edit 버전(원본에도 같이 그렸어도 노트는 하나).
    - 원본에만 그렸으면 org 버전, 샷그리드에 org 버전이 없으면 edit 버전.
    - 그림 없이 글만 보내면 지금 보고 있는 영상을 그린 영상으로 친다.
    - 붙일 버전이 하나도 없으면 ``("", None)``.
    """
    sources = {s for s in drawn if s}
    if not sources:
        sources = {shown or SOURCE_PLATE}
    edit = found.get(SOURCE_EDIT)
    plate = found.get(SOURCE_PLATE)
    if SOURCE_EDIT in sources and edit is not None:
        return SOURCE_EDIT, edit
    if SOURCE_PLATE in sources and plate is not None and SOURCE_EDIT not in sources:
        return SOURCE_PLATE, plate
    if edit is not None:
        return SOURCE_EDIT, edit
    if plate is not None:
        return SOURCE_PLATE, plate
    return "", None


def stage_annot_files(items: Sequence[Tuple[str, int]], version_id: int, folder: Path) -> List[str]:
    """그림 파일들을 *folder* 에 샷그리드 그림 이름으로 복사한다 → 새 경로들(순서 그대로).

    *items* 는 ``(그림 파일, 그 영상에서의 프레임 순번)``. 올릴 때 파일 이름이 곧 첨부 이름이
    되므로 이름을 파일에서 맞춘다. 원래 파일은 건드리지 않는다.
    """
    folder.mkdir(parents=True, exist_ok=True)
    names = annot_file_names(version_id, [index for _path, index in items])
    out: List[str] = []
    for (src, _index), name in zip(items, names):
        dst = folder / name
        shutil.copyfile(src, dst)
        out.append(str(dst))
    return out
