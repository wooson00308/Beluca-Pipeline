"""ShotGrid Shot queries."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.shots")


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


def list_shots_for_project(
    sg: Any, project_id: int, limit: int = 800
) -> List[Dict[str, Any]]:
    return sg.find(
        "Shot",
        [["project", "is", {"type": "Project", "id": int(project_id)}]],
        ["id", "code"],
        order=[{"field_name": "code", "direction": "asc"}],
        limit=limit,
    )
