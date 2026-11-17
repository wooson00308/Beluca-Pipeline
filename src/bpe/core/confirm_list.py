"""컨펌 목록의 갈래 나누기·찾기·정렬 (표준 라이브러리만).

갈래 이름은 샷그리드 Versions 화면에 만들어 둔 분류 이름을 그대로 쓴다.
vendor = 버전을 올린 쪽(샷그리드 Version 의 Artist)이 업체 그룹. 내부 = 사람.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

GROUP_VENDOR = "SV_Confirm (vendor)"
GROUP_INTERNAL = "SV_Confirm (내부)"
GROUP_CGI = "CGI_Confirm"
GROUP_TM = "TM_Confirm"
GROUP_ALL = "total"
# 목록에 보이는 순서 — 내부를 맨 위에 둔다
GROUPS: Tuple[str, ...] = (GROUP_INTERNAL, GROUP_VENDOR, GROUP_CGI, GROUP_TM, GROUP_ALL)
STATUS_SV = "sv"
STATUS_TM = "tm"
STATUS_CGI = "cgi"  # 샷그리드 상태 「CGI Confirm」
# 컨펌 목록에 올리는 태스크 상태들
LIST_STATUSES: Tuple[str, ...] = (STATUS_SV, STATUS_TM, STATUS_CGI)

SORT_OLD = "오래된 순"
SORT_NEW = "새 것부터"
SORT_SHOT = "샷 이름 순"
SORTS: Tuple[str, ...] = (SORT_OLD, SORT_NEW, SORT_SHOT)

UPLOADER_GROUP = "Group"

Row = Dict[str, Any]


def is_vendor(row: Row) -> bool:
    return (row.get("uploader_type") or "") == UPLOADER_GROUP


def in_group(row: Row, group: str) -> bool:
    status = (row.get("task_status") or "").strip().lower()
    if group == GROUP_VENDOR:
        return status == STATUS_SV and is_vendor(row)
    if group == GROUP_INTERNAL:
        return status == STATUS_SV and not is_vendor(row)
    if group == GROUP_CGI:
        return status == STATUS_CGI
    if group == GROUP_TM:
        return status == STATUS_TM
    return True


def vendor_names(rows: List[Row]) -> List[str]:
    """목록에 있는 외주 업체 이름들(가나다순)."""
    return sorted({(r.get("uploader_name") or "").strip() for r in rows if is_vendor(r)} - {""})


def filter_rows(rows: List[Row], group: str, *, vendor: str = "", search: str = "") -> List[Row]:
    needle = (search or "").strip().lower()
    out: List[Row] = []
    for r in rows:
        if not in_group(r, group):
            continue
        if vendor and (r.get("uploader_name") or "").strip() != vendor:
            continue
        if needle:
            hay = " ".join(
                str(r.get(k) or "")
                for k in (
                    "shot_code",
                    "uploader_name",
                    "version_uploader_name",
                    "latest_version_code",
                )
            ).lower()
            if needle not in hay:
                continue
        out.append(r)
    return out


def sort_rows(rows: List[Row], mode: str) -> List[Row]:
    if mode == SORT_SHOT:
        return sorted(rows, key=lambda r: str(r.get("shot_code") or "").lower())
    keyed = sorted(rows, key=lambda r: str(r.get("latest_version_created_at") or "9999"))
    return list(reversed(keyed)) if mode == SORT_NEW else keyed


# ── Annotation 모드: 작업을 나눠 주기 전(wtg·assign)의 샷 ─────────────────────────

ANNOTATION_STATUSES: Tuple[str, ...] = ("wtg", "assign")


def _assignee_key(a: Any) -> Tuple[str, int]:
    if isinstance(a, dict) and a.get("id") is not None:
        try:
            return (str(a.get("type") or ""), int(a["id"]))
        except (TypeError, ValueError):
            return ("", 0)
    return ("", 0)


def group_rows_by_shot(rows: List[Row]) -> List[Row]:
    """태스크마다 한 줄인 목록을 샷마다 한 줄로 묶는다(샷 이름 순).

    한 샷에 wtg·assign 태스크가 여럿이어도 목록에는 한 번만 보인다. 묶인 줄에는
    ``tasks``(그 샷의 태스크들), ``task_statuses``(상태들), 담당을 모두 합친
    ``task_assignees`` 가 들어간다. ``task_id``·``task_status`` 는 첫 태스크의 것.
    """
    by_shot: Dict[Any, Row] = {}
    for r in sorted(
        rows, key=lambda x: (str(x.get("shot_code") or "").lower(), x.get("task_id") or 0)
    ):
        key = r.get("shot_id")
        if key is None:
            continue
        task = {
            "task_id": r.get("task_id"),
            "task_content": (r.get("task_content") or "").strip(),
            "task_status": (r.get("task_status") or "").strip(),
            "task_assignees": list(r.get("task_assignees") or []),
        }
        cur = by_shot.get(key)
        if cur is None:
            cur = dict(r)
            cur["tasks"] = [task]
            cur["task_statuses"] = [task["task_status"]] if task["task_status"] else []
            cur["task_assignees"] = list(task["task_assignees"])
            by_shot[key] = cur
            continue
        cur["tasks"].append(task)
        if task["task_status"] and task["task_status"] not in cur["task_statuses"]:
            cur["task_statuses"].append(task["task_status"])
        have = {_assignee_key(a) for a in cur["task_assignees"]}
        for a in task["task_assignees"]:
            if _assignee_key(a) not in have:
                cur["task_assignees"].append(a)
                have.add(_assignee_key(a))
    return list(by_shot.values())


MODE_CONFIRM = "Confirm"
MODE_ANNOTATION = "Annotation"
MODES: Tuple[str, ...] = (MODE_CONFIRM, MODE_ANNOTATION)


def filter_annotation_rows(
    rows: List[Row], *, search: str = "", shot_ids: Optional[Set[int]] = None
) -> List[Row]:
    """Annotation 목록 거르기 — 찾는 말(샷·태스크·담당 이름)과 필터로 남은 샷(*shot_ids*)."""
    needle = (search or "").strip().lower()
    out: List[Row] = []
    for r in rows:
        if shot_ids is not None and r.get("shot_id") not in shot_ids:
            continue
        if needle:
            names = [str(a.get("name") or "") for a in r.get("task_assignees") or []]
            tasks = [str(t.get("task_content") or "") for t in r.get("tasks") or []]
            hay = " ".join([str(r.get("shot_code") or "")] + tasks + names).lower()
            if needle not in hay:
                continue
        out.append(r)
    return sorted(out, key=lambda r: str(r.get("shot_code") or "").lower())


def annotation_status_text(row: Row) -> str:
    """Annotation 목록 한 줄의 상태 글 — 그 샷 태스크들의 상태(겹치지 않게)."""
    return " · ".join(str(s) for s in row.get("task_statuses") or [] if s)


def annotation_subtitle(row: Row) -> str:
    """Annotation 목록 한 줄의 둘째 줄: 태스크 이름(상태) 들."""
    parts = [
        f"{t.get('task_content') or '태스크'} {t.get('task_status') or ''}".strip()
        for t in row.get("tasks") or []
    ]
    return " · ".join(parts)


def row_subtitle(row: Row) -> str:
    """목록 한 줄의 둘째 줄: 버전 · 올린 쪽 · 올린 날."""
    code = str(row.get("latest_version_code") or "")
    ver = code[code.lower().rfind("_v") + 1 :] if "_v" in code.lower() else code
    who = (row.get("uploader_name") or row.get("version_uploader_name") or "").strip()
    when = str(row.get("latest_version_created_at") or "")[:10]
    return " · ".join(x for x in (ver, who, when) if x)
