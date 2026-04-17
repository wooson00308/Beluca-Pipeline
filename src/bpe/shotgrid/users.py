"""ShotGrid HumanUser queries."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.users")

# My Tasks 담당자 표시 문자열 "이름 로그인 (이메일)" 등에서 이메일 추출
_EMAIL_TOKEN_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)


def normalize_human_user_search_query(raw: str) -> str:
    """검색어가 UI 표시용 긴 문자열이면 이메일 등 짧은 토큰으로 줄인다 (My Tasks 자동완성).

    일반 이름/로그인 검색(짧은 문자열, 이메일 없음)은 그대로 둔다.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    emails = _EMAIL_TOKEN_RE.findall(s)
    if emails:
        return emails[0].strip()
    return s


def search_human_users(sg: Any, query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Search HumanUsers by name or login (for artist autocomplete)."""
    q = normalize_human_user_search_query((query or "").strip())
    if not q:
        return []
    fields = ["id", "name", "login", "email"]
    results = sg.find(
        "HumanUser",
        [["name", "contains", q]],
        fields,
        limit=limit,
    )
    if not results:
        try:
            results = sg.find(
                "HumanUser",
                [["login", "contains", q]],
                fields,
                limit=limit,
            )
        except Exception:
            pass
    if not results and "@" in q:
        try:
            results = sg.find(
                "HumanUser",
                [["email", "contains", q]],
                fields,
                limit=limit,
            )
        except Exception:
            pass
    return results


def guess_human_user_for_me(sg: Any, *, limit: int = 8) -> Optional[Dict[str, Any]]:
    """Guess the current OS user's HumanUser by login / USERNAME."""
    candidates: List[str] = []
    try:
        candidates.append(os.getlogin().strip().lower())
    except Exception:
        pass
    env_u = (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip().lower()
    if env_u:
        candidates.append(env_u)

    seen: set[str] = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            hits = sg.find(
                "HumanUser",
                [["login", "contains", c]],
                ["id", "name", "login", "email"],
                limit=int(limit),
            )
            if hits:
                return hits[0]
        except Exception:
            continue
        try:
            hits = sg.find(
                "HumanUser",
                [["email", "contains", c]],
                ["id", "name", "login", "email"],
                limit=int(limit),
            )
            if hits:
                return hits[0]
        except Exception:
            continue
    return None


def list_project_assignees(sg: Any, project_id: int) -> List[Dict[str, Any]]:
    """HumanUsers who have at least one Task on the given Project (deduped, name sort).

    Tries ShotGrid relation filter first; falls back to scanning Tasks if needed.
    """
    pid = int(project_id)
    proj_ref = {"type": "Project", "id": pid}
    fields = ["id", "name", "login", "email"]
    users: List[Dict[str, Any]] = []
    try:
        users = list(
            sg.find(
                "HumanUser",
                [["tasks.Task.project", "is", proj_ref]],
                fields,
                order=[{"field_name": "name", "direction": "asc"}],
                limit=500,
            )
            or []
        )
    except Exception as exc:
        logger.debug("list_project_assignees relation filter failed: %s", exc)
        users = []
    if users:
        return _dedupe_users_by_id(users)

    seen: Dict[int, Dict[str, Any]] = {}
    try:
        tasks = list(
            sg.find(
                "Task",
                [["project", "is", proj_ref]],
                ["task_assignees"],
                limit=2000,
            )
            or []
        )
    except Exception as exc:
        logger.warning("list_project_assignees task scan failed: %s", exc)
        return []

    for t in tasks:
        raw = t.get("task_assignees") or []
        if not isinstance(raw, list):
            continue
        for ent in raw:
            if not isinstance(ent, dict):
                continue
            if (ent.get("type") or "").lower() != "humanuser":
                continue
            uid = ent.get("id")
            if uid is None:
                continue
            try:
                iid = int(uid)
            except (TypeError, ValueError):
                continue
            if iid not in seen:
                seen[iid] = {
                    "id": iid,
                    "name": (ent.get("name") or "").strip(),
                    "login": (ent.get("login") or "").strip(),
                    "email": (ent.get("email") or "").strip(),
                }

    out = list(seen.values())
    out.sort(key=lambda u: ((u.get("name") or "").lower(), (u.get("login") or "").lower()))
    if not out:
        return []

    # Fill missing fields from SG
    try:
        ids = [u["id"] for u in out]
        chunk = ids[:100]
        rows = list(
            sg.find(
                "HumanUser",
                [["id", "in", chunk]],
                fields,
                limit=len(chunk),
            )
            or []
        )
        by_id = {int(r["id"]): r for r in rows if r.get("id") is not None}
        for u in out:
            rid = int(u["id"])
            row = by_id.get(rid)
            if row:
                u["name"] = (row.get("name") or u.get("name") or "").strip()
                u["login"] = (row.get("login") or u.get("login") or "").strip()
                u["email"] = (row.get("email") or u.get("email") or "").strip()
    except Exception as exc:
        logger.debug("list_project_assignees hydrate users failed: %s", exc)

    return out


def _dedupe_users_by_id(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[int, Dict[str, Any]] = {}
    for u in users:
        uid = u.get("id")
        if uid is None:
            continue
        try:
            iid = int(uid)
        except (TypeError, ValueError):
            continue
        if iid not in seen:
            seen[iid] = u
    out = list(seen.values())
    out.sort(key=lambda x: ((x.get("name") or "").lower(), (x.get("login") or "").lower()))
    return out
