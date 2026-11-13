"""컨펌 창의 Note 칸에 보일 샷의 지난 내용 — 노트 + 작업자가 버전을 올리며 적은 글."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.notes import list_notes_for_shots

logger = get_logger("shotgrid.confirm_context")

KIND_NOTE = "note"
KIND_VERSION = "version"
_VERSION_FIELDS = ["id", "code", "description", "user", "created_by", "created_at", "sg_task"]
_NEWEST_FIRST = [{"field_name": "created_at", "direction": "desc"}]


def _name(value: Any) -> str:
    return str(value.get("name") or "").strip() if isinstance(value, dict) else ""


def _stamp(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value or "")


def version_comments(
    sg: Any, shot_id: int, *, task_id: Optional[int] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    """샷에 올라온 버전들 중 설명(Description)이 적힌 것. *task_id* 가 있으면 그 태스크 것만

    (태스크가 안 걸린 버전은 함께 보여 준다).
    """
    rows = sg.find(
        "Version",
        [["entity", "is", {"type": "Shot", "id": int(shot_id)}]],
        _VERSION_FIELDS,
        order=_NEWEST_FIRST,
        limit=limit,
    )
    out: List[Dict[str, Any]] = []
    for v in rows or []:
        text = str(v.get("description") or "").strip()
        if not text:
            continue
        task = v.get("sg_task")
        if task_id is not None and isinstance(task, dict) and task.get("id") is not None:
            if int(task["id"]) != int(task_id):
                continue
        out.append(
            {
                "kind": KIND_VERSION,
                "version_id": v.get("id"),
                "version_code": str(v.get("code") or "").strip() or None,
                "timestamp": _stamp(v.get("created_at")),
                "author": _name(v.get("user")) or _name(v.get("created_by")) or "—",
                "subject": "",
                "content": text,
            }
        )
    return out


def list_shot_history(
    sg: Any, shot_id: int, *, task_id: Optional[int] = None, limit: int = 250
) -> List[Dict[str, Any]]:
    """노트와 버전 설명을 한 줄로 합쳐 최근 것부터. 버전 설명을 못 읽어도 노트는 돌려준다."""
    notes = list_notes_for_shots(sg, [int(shot_id)], days_back=0, limit=limit)
    for n in notes:
        n.setdefault("kind", KIND_NOTE)
    try:
        comments = version_comments(sg, shot_id, task_id=task_id)
    except Exception as e:
        logger.warning("confirm context: version comments failed: %s", e)
        comments = []
    merged = list(notes) + comments
    merged.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    return merged
