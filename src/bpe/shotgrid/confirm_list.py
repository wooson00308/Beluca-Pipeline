"""컨펌 목록 조회 — 확인 대기 태스크에 "가장 최근에 올라온 버전"과 "올린 쪽"을 붙인다.

태스크의 「최신 버전」 칸(sg_latest_version)은 비어 있는 일이 많다. 그래서 버전 기록
(Version)을 직접 읽어, 태스크에 걸린 것 중 가장 최근 것을(없으면 그 샷의 가장 최근 것을)
쓴다. 올린 쪽이 그룹(업체)이면 외주, 사람이면 내부다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from bpe.core.confirm_list import (
    ANNOTATION_STATUSES,
    LIST_STATUSES,
    MATERIAL_TASKS,
    group_rows_by_shot,
)
from bpe.core.logging import get_logger
from bpe.shotgrid.tasks import (
    _detect_shot_vfx_field,
    detect_task_status_field,
    list_review_tasks_for_project,
)

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


def list_shots_for_annotation(
    sg: Any, project_id: int, shot_ids: Sequence[int]
) -> List[Dict[str, Any]]:
    """고른 샷들을 Annotation 목록의 줄로 — 태스크 상태와 상관없이, 샷마다 한 줄(샷 이름 순).

    줄 모양은 :func:`list_annotation_shots` 와 같다. ``tasks`` 에는 작업 태스크만 담고
    (edit·org·guide 같은 재료 태스크는 뺀다), 담당은 그 태스크들의 담당을 모두 합친다.
    ``task_id`` 는 첫 작업 태스크의 것 — 작업 태스크가 없는 샷은 아무 태스크나,
    그것도 없으면 ``None``.
    """
    ids = sorted({int(i) for i in shot_ids if i is not None})
    if not ids:
        return []
    vfx_field = _detect_shot_vfx_field(sg)
    status_fn = detect_task_status_field(sg) or "sg_status_list"
    shot_fields = [
        "id", "code", "description", "image", "sg_status_list",
        "project", "project.Project.code", "project.Project.name",
    ]  # fmt: skip
    if vfx_field:
        shot_fields.append(vfx_field)
    shots: Dict[int, Dict[str, Any]] = {}
    tasks: Dict[int, List[Dict[str, Any]]] = {}
    for i in range(0, len(ids), _CHUNK):
        part = ids[i : i + _CHUNK]
        for s in sg.find("Shot", [["id", "in", part]], shot_fields) or []:
            if s.get("id") is not None:
                shots[int(s["id"])] = s
        links = [_link("Shot", x) for x in part]
        task_fields = ["id", "content", "task_assignees", status_fn, "entity"]
        for t in sg.find("Task", [["entity", "in", links]], task_fields) or []:
            sid = _link_id(t.get("entity"))
            if sid is not None:
                tasks.setdefault(sid, []).append(t)
    out: List[Dict[str, Any]] = []
    for sid in ids:
        s = shots.get(sid)
        if s is None:
            continue
        proj = s.get("project") if isinstance(s.get("project"), dict) else {}
        proj_code = str(s.get("project.Project.code") or proj.get("code") or "").strip()
        proj_name = str(s.get("project.Project.name") or proj.get("name") or "").strip()
        every = sorted(
            tasks.get(sid, []),
            key=lambda t: (str(t.get("content") or "").lower(), t.get("id") or 0),
        )
        work = [
            t for t in every if str(t.get("content") or "").strip().lower() not in MATERIAL_TASKS
        ]
        first = (work or every or [{}])[0]
        people: List[Dict[str, Any]] = []
        seen: set = set()
        for t in work:
            for a in t.get("task_assignees") or []:
                key = (str(a.get("type") or ""), a.get("id")) if isinstance(a, dict) else None
                if key is not None and key not in seen:
                    seen.add(key)
                    people.append(a)
        statuses: List[str] = []
        for t in work:
            st = str(t.get(status_fn) or "").strip()
            if st and st not in statuses:
                statuses.append(st)
        order = s.get(vfx_field) if vfx_field else ""
        if isinstance(order, dict):
            order = order.get("name") or order.get("value")
        pid = proj.get("id")
        out.append(
            {
                "shot_id": sid,
                "shot_code": str(s.get("code") or "").strip(),
                "shot_description": str(s.get("description") or "").strip(),
                "shot_image": s.get("image") or "",
                "shot_status": str(s.get("sg_status_list") or "").strip(),
                "vfx_work_order": str(order or "").strip(),
                "project_id": pid if pid is not None else int(project_id),
                "project_code": proj_code,
                "project_name": proj_name,
                "project_folder": (proj_code or proj_name).strip(),
                "status_field": status_fn,
                "task_id": first.get("id"),
                "task_content": str(first.get("content") or "").strip(),
                "task_status": str(first.get(status_fn) or "").strip(),
                "task_assignees": people,
                "task_statuses": statuses,
                "tasks": [
                    {
                        "task_id": t.get("id"),
                        "task_content": str(t.get("content") or "").strip(),
                        "task_status": str(t.get(status_fn) or "").strip(),
                        "task_assignees": list(t.get("task_assignees") or []),
                    }
                    for t in work
                ],
            }
        )
    return sorted(out, key=lambda r: str(r.get("shot_code") or "").lower())


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
