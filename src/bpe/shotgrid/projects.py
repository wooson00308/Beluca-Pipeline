"""ShotGrid Project queries."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.projects")


def list_projects(sg: Any, limit: int = 500) -> List[Dict[str, Any]]:
    return sg.find(
        "Project",
        [],
        ["id", "name", "code"],
        order=[{"field_name": "name", "direction": "asc"}],
        limit=limit,
    )


def find_project_by_code(sg: Any, code: str) -> Optional[Dict[str, Any]]:
    """Find a Project by its code field."""
    code = (code or "").strip()
    if not code:
        return None
    return sg.find_one(
        "Project",
        [["code", "is", code]],
        ["id", "name", "code"],
    )


def list_active_projects(sg: Any, limit: int = 300) -> List[Dict[str, Any]]:
    """Return active projects; falls back to all projects if sg_status is absent."""
    try:
        return sg.find(
            "Project",
            [["sg_status", "is", "Active"]],
            ["id", "name", "code"],
            limit=limit,
        )
    except Exception:
        try:
            return sg.find("Project", [], ["id", "name", "code"], limit=limit)
        except Exception:
            return []
