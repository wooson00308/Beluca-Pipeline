"""ShotGrid HumanUser queries."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.users")


def search_human_users(
    sg: Any, query: str, limit: int = 15
) -> List[Dict[str, Any]]:
    """Search HumanUsers by name or login (for artist autocomplete)."""
    q = (query or "").strip()
    if not q:
        return []
    results = sg.find(
        "HumanUser",
        [["name", "contains", q]],
        ["id", "name", "login", "email"],
        limit=limit,
    )
    if not results:
        try:
            results = sg.find(
                "HumanUser",
                [["login", "contains", q]],
                ["id", "name", "login", "email"],
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
