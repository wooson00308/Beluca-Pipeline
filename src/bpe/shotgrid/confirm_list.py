"""컨펌 목록 조회 — 확인 대기 태스크에 "가장 최근에 올라온 버전"과 "올린 쪽"을 붙인다.

태스크의 「최신 버전」 칸(sg_latest_version)은 비어 있는 일이 많다. 그래서 버전 기록
(Version)을 직접 읽어, 태스크에 걸린 것 중 가장 최근 것을(없으면 그 샷의 가장 최근 것을)
쓴다. 올린 쪽이 그룹(업체)이면 외주, 사람이면 내부다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from bpe.core.confirm_list import ANNOTATION_STATUSES, LIST_STATUSES, group_rows_by_shot
from bpe.core.logging import get_logger
from bpe.shotgrid.tasks import list_review_tasks_for_project

logger = get_logger("shotgrid.confirm_list")

DEFAULT_STATUSES = LIST_STATUSES  # sv · tm · cgi
_CHUNK = 100
_VERSION_FIELDS = [
    "id",
    "code",
    "user",
    "created_by",
    "created_at",
    "sg_path_to_movie",
    "sg_task",
    "entity",
    "image",
]
_NEWEST_FIRST = [{"field_name": "created_at", "direction": "desc"}]


def _link(entity_type: str, entity_id: Any) -> Dict[str, Any]:
    return {"type": entity_type, "id": int(entity_id)}


def _link_id(value: Any) -> Optional[int]:
    if isinstance(value, dict) and value.get("id") is not None:
        try:
            return int(value["id"])
        except (TypeError, ValueError):
            return None
    return None


def _latest_by(sg: Any, field: str, links: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """*field*(sg_task / entity)가 *links* 중 하나인 버전들에서, 연결 대상마다 가장 최근 것."""
    out: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(links), _CHUNK):
        chunk = links[i : i + _CHUNK]
        rows = sg.find("Version", [[field, "in", chunk]], _VERSION_FIELDS, order=_NEWEST_FIRST)
        for v in rows or []:
            key = _link_id(v.get(field))
            if key is not None and key not in out:  # 최근 것부터 오므로 처음 본 것이 최신
                out[key] = v
    return out


def latest_versions(
    sg: Any, task_ids: Sequence[Any], shot_ids_by_task: Dict[int, int]
) -> Dict[int, Dict[str, Any]]:
    """태스크 id → 그 태스크의 가장 최근 버전. 태스크에 걸린 버전이 없으면 샷의 최근 버전."""
    ids = sorted({int(t) for t in task_ids if t is not None})
    found = _latest_by(sg, "sg_task", [_link("Task", t) for t in ids])
    missing = [t for t in ids if t not in found and shot_ids_by_task.get(t) is not None]
    if missing:
        shots = sorted({int(shot_ids_by_task[t]) for t in missing})
        by_shot = _latest_by(sg, "entity", [_link("Shot", s) for s in shots])
        for t in missing:
            v = by_shot.get(int(shot_ids_by_task[t]))
            if v is not None:
                found[t] = v
    return found


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


def _apply_version(row: Dict[str, Any], v: Dict[str, Any]) -> None:
    user = v.get("user") if isinstance(v.get("user"), dict) else {}
    maker = v.get("created_by") if isinstance(v.get("created_by"), dict) else {}
    row["latest_version_id"] = int(v["id"])
    row["latest_version_code"] = str(v.get("code") or "").strip()
    row["latest_version_sg_path"] = str(v.get("sg_path_to_movie") or "").strip()
    row["latest_version_created_at"] = v.get("created_at")
    row["latest_version_image"] = v.get("image") or ""
    row["uploader_type"] = str(user.get("type") or "")
    row["uploader_name"] = str(user.get("name") or maker.get("name") or "").strip()
    row["version_uploader_name"] = row["uploader_name"]


def list_annotation_shots(
    sg: Any,
    project_id: int,
    *,
    statuses: Optional[Sequence[str]] = None,
    limit: int = 3000,
) -> List[Dict[str, Any]]:
    """Annotation 모드 목록 — 어느 태스크든 상태가 wtg·assign 인 샷을 샷마다 한 줄로.

    아직 작업본이 없는 샷들이라 버전은 찾지 않는다.
    """
    rows = list_review_tasks_for_project(
        sg,
        int(project_id),
        statuses=list(statuses or ANNOTATION_STATUSES),
        task_content="",
        limit=limit,
    )
    return group_rows_by_shot(rows)


def list_confirm_tasks(
    sg: Any,
    project_id: int,
    *,
    statuses: Optional[Sequence[str]] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """확인 대기 태스크 목록. 각 줄에 최근 버전(``latest_version_*``)과 올린 쪽을 채운다."""
    rows = list_review_tasks_for_project(
        sg, int(project_id), statuses=list(statuses or DEFAULT_STATUSES), limit=limit
    )
    for r in rows:
        r.setdefault("uploader_type", "")
        r.setdefault("uploader_name", r.get("version_uploader_name") or "")
        r.setdefault("latest_version_image", "")
    shot_of = {
        int(r["task_id"]): int(r["shot_id"])
        for r in rows
        if r.get("task_id") is not None and r.get("shot_id") is not None
    }
    try:
        latest = latest_versions(sg, [r.get("task_id") for r in rows], shot_of)
    except Exception as e:  # 버전을 못 읽어도 목록은 보여 준다(전부 내부로 보임)
        logger.warning("confirm list: version lookup failed: %s", e)
        latest = {}
    for r in rows:
        v = latest.get(int(r["task_id"])) if r.get("task_id") is not None else None
        if v is not None:
            _apply_version(r, v)
    # 태스크의 「최신 버전」 칸만 채워져 있고 위에서 못 찾은 줄 — 그 버전의 올린 쪽을 따로 읽는다
    left = [
        r for r in rows if not r.get("uploader_type") and r.get("latest_version_id") is not None
    ]
    if left:
        try:
            who = version_uploaders(sg, [r["latest_version_id"] for r in left])
        except Exception as e:
            logger.warning("confirm list: uploader lookup failed: %s", e)
            who = {}
        for r in left:
            info = who.get(int(r["latest_version_id"])) or {}
            r["uploader_type"] = info.get("type", "")
            r["uploader_name"] = info.get("name", "") or r["uploader_name"]
    return rows
