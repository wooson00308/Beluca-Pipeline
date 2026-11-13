"""컨펌 목록의 갈래 나누기·찾기·정렬 (표준 라이브러리만).

갈래 이름은 샷그리드 Versions 화면에 만들어 둔 분류 이름을 그대로 쓴다.
vendor = 버전을 올린 쪽(샷그리드 Version 의 Artist)이 업체 그룹. 내부 = 사람.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

GROUP_VENDOR = "SV_Confirm (vendor)"
GROUP_INTERNAL = "SV_Confirm (내부)"
GROUP_TM = "TM_Confirm"
GROUP_ALL = "total"
GROUPS: Tuple[str, ...] = (GROUP_VENDOR, GROUP_INTERNAL, GROUP_TM, GROUP_ALL)
STATUS_SV = "sv"
STATUS_TM = "tm"

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


def row_subtitle(row: Row) -> str:
    """목록 한 줄의 둘째 줄: 버전 · 올린 쪽 · 올린 날."""
    code = str(row.get("latest_version_code") or "")
    ver = code[code.lower().rfind("_v") + 1 :] if "_v" in code.lower() else code
    who = (row.get("uploader_name") or row.get("version_uploader_name") or "").strip()
    when = str(row.get("latest_version_created_at") or "")[:10]
    return " · ".join(x for x in (ver, who, when) if x)
