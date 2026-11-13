"""컨펌 목록 조회 — 확인 대기 태스크에 "올린 쪽이 업체인지 사람인지"를 붙인다."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from bpe.core.logging import get_logger
from bpe.shotgrid.tasks import list_review_tasks_for_project

logger = get_logger("shotgrid.confirm_list")

DEFAULT_STATUSES = ("sv", "tm")
_CHUNK = 100


def version_uploaders(sg: Any, version_ids: Sequence[int]) -> Dict[int, Dict[str, str]]:
    """버전 id → ``{"type": "Group"|"HumanUser"|…, "name": 이름}``."""
    out: Dict[int, Dict[str, str]] = {}
    ids = sorted({int(v) for v in version_ids if v is not None})
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        rows = sg.find("Version", [["id", "in", chunk]], ["id", "user"])
        for r in rows or []:
            user = r.get("user") if isinstance(r.get("user"), dict) else {}
            out[int(r["id"])] = {
                "type": str(user.get("type") or ""),
                "name": str(user.get("name") or ""),
            }
    return out


def list_confirm_tasks(
    sg: Any,
    project_id: int,
    *,
    statuses: Optional[Sequence[str]] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """확인 대기 태스크 목록. 각 줄에 ``uploader_type``·``uploader_name`` 을 더한다."""
    rows = list_review_tasks_for_project(
        sg, int(project_id), statuses=list(statuses or DEFAULT_STATUSES), limit=limit
    )
    ids = [r.get("latest_version_id") for r in rows if r.get("latest_version_id") is not None]
    try:
        who = version_uploaders(sg, ids) if ids else {}
    except Exception as e:  # 올린 쪽을 못 읽어도 목록은 보여 준다(전부 내부로 보임)
        logger.warning("confirm list: uploader lookup failed: %s", e)
        who = {}
    for r in rows:
        info = (
            who.get(int(r["latest_version_id"])) if r.get("latest_version_id") is not None else None
        )
        r["uploader_type"] = (info or {}).get("type", "")
        r["uploader_name"] = (info or {}).get("name", "") or (r.get("version_uploader_name") or "")
    return rows
