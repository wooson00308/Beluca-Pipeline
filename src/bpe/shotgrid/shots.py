"""ShotGrid Shot queries."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.shots")

# Shot entity field for tags / classification (detected once per process from Shot schema)
_SHOT_TAGS_FIELD_CACHE: Optional[str] = None


def find_shot(sg: Any, project_id: int, shot_code: str) -> Optional[Dict[str, Any]]:
    code = (shot_code or "").strip()
    if not code:
        return None
    return sg.find_one(
        "Shot",
        [
            ["project", "is", {"type": "Project", "id": int(project_id)}],
            ["code", "is", code],
        ],
        ["id", "code", "project"],
    )


def find_shot_any_project(sg: Any, shot_code: str) -> Optional[Dict[str, Any]]:
    """Find a shot across all projects.

    Case-insensitive: tries exact -> upper -> lower, then contains fallback.
    """
    code = (shot_code or "").strip()
    if not code:
        return None
    for candidate in dict.fromkeys([code, code.upper(), code.lower()]):
        shot = sg.find_one(
            "Shot",
            [["code", "is", candidate]],
            ["id", "code", "project"],
        )
        if shot:
            logger.debug("find_shot_any_project found: query=%s id=%s", candidate, shot.get("id"))
            return shot
    # contains fallback
    try:
        shots = sg.find(
            "Shot",
            [["code", "contains", code.split("_")[0]]],
            ["id", "code", "project"],
            limit=20,
        )
        for s in shots:
            if (s.get("code") or "").lower() == code.lower():
                return s
    except Exception:
        pass
    return None


def list_shots_for_project(sg: Any, project_id: int, limit: int = 800) -> List[Dict[str, Any]]:
    return sg.find(
        "Shot",
        [["project", "is", {"type": "Project", "id": int(project_id)}]],
        ["id", "code"],
        order=[{"field_name": "code", "direction": "asc"}],
        limit=limit,
    )


def detect_shot_tags_field(sg: Any) -> str:
    """Return Shot API field used for tags / labels, or '' if none.

    Cached per process. Heuristic: schema keys named tags / sg_tags / *tag* with list-like
    data_type.
    """
    global _SHOT_TAGS_FIELD_CACHE
    if _SHOT_TAGS_FIELD_CACHE is not None:
        return _SHOT_TAGS_FIELD_CACHE
    names: List[str] = []
    try:
        raw = sg.schema_field_read("Shot")
        if isinstance(raw, dict):
            names = list(raw.keys())
    except Exception as e:
        logger.debug("detect_shot_tags_field schema read failed: %s", e)
    priority: List[str] = []
    rest: List[str] = []
    for name in names:
        low = str(name).lower()
        if low in ("tags", "sg_tags", "shot_tags"):
            priority.append(str(name))
        elif "tag" in low:
            rest.append(str(name))
    candidates = priority + rest
    for name in candidates:
        sch: Dict[str, Any] = {}
        try:
            raw_s = sg.schema_field_read("Shot", name)
            sch = raw_s if isinstance(raw_s, dict) else {}
        except Exception:
            sch = {}
        dt = str(sch.get("data_type") or "").lower()
        if any(x in dt for x in ("multi", "list", "tag")) or dt in ("list", "tag_list"):
            _SHOT_TAGS_FIELD_CACHE = str(name)
            return _SHOT_TAGS_FIELD_CACHE
    if candidates:
        _SHOT_TAGS_FIELD_CACHE = candidates[0]
        return _SHOT_TAGS_FIELD_CACHE
    _SHOT_TAGS_FIELD_CACHE = ""
    return ""


def normalize_shot_tag_values(val: Any) -> List[str]:
    """Normalize ShotGrid tag field values to display/filter strings."""
    out: List[str] = []
    if val is None:
        return out
    if isinstance(val, str):
        s = val.strip()
        if s:
            out.append(s)
        return out
    if isinstance(val, list):
        for x in val:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)
            elif isinstance(x, dict):
                n = (x.get("name") or x.get("code") or x.get("value") or "").strip()
                if isinstance(n, str) and n:
                    out.append(n)
    return out


def shot_tag_strings_from_task_row(t: Dict[str, Any], field_name: str) -> List[str]:
    """Read tags from a Task row using ``entity.Shot.<field>`` or nested entity."""
    if not field_name:
        return []
    key = f"entity.Shot.{field_name}"
    val: Any = t.get(key)
    if val is None:
        ent = t.get("entity") or {}
        if isinstance(ent, dict):
            val = ent.get(field_name)
    return normalize_shot_tag_values(val)


def search_shots_by_code_prefix(
    sg: Any,
    project_id: int,
    prefix: str,
    *,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Autocomplete: Shots in *project_id* whose ``code`` starts with *prefix* (min 2 chars)."""
    p = (prefix or "").strip()
    if len(p) < 2:
        return []
    pid = int(project_id)
    lim = max(1, int(limit))
    try:
        return list(
            sg.find(
                "Shot",
                [
                    ["project", "is", {"type": "Project", "id": pid}],
                    ["code", "starts_with", p],
                ],
                ["id", "code"],
                order=[{"field_name": "code", "direction": "asc"}],
                limit=lim,
            )
            or []
        )
    except Exception as e:
        logger.debug("search_shots_by_code_prefix starts_with failed: %s", e)
        try:
            rows = list(
                sg.find(
                    "Shot",
                    [
                        ["project", "is", {"type": "Project", "id": pid}],
                        ["code", "contains", p],
                    ],
                    ["id", "code"],
                    order=[{"field_name": "code", "direction": "asc"}],
                    limit=lim,
                )
                or []
            )
        except Exception as e2:
            logger.warning("search_shots_by_code_prefix contains failed: %s", e2)
            return []
        pref_l = p.lower()
        rows.sort(
            key=lambda r: (
                0 if str(r.get("code") or "").lower().startswith(pref_l) else 1,
                str(r.get("code") or "").lower(),
            )
        )
        return rows[:lim]
