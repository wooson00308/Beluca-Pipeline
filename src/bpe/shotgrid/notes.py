"""ShotGrid Note queries for shot-linked comments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.notes")

_NOTE_FIELDS = [
    "id",
    "subject",
    "content",
    "created_at",
    "created_by",
    "note_links",
    "project",
]


def list_notes_for_shots(
    sg: Any,
    shot_ids: List[int],
    *,
    limit: int = 300,
    days_back: int = 14,
) -> List[Dict[str, Any]]:
    """Return Notes linked to given Shot IDs, newest first.

    Parameters
    ----------
    days_back : int
        Only fetch notes created within this many days.  0 or negative
        means no date limit.
    """
    if not shot_ids:
        return []

    note_link_vals = [{"type": "Shot", "id": int(sid)} for sid in shot_ids]

    cutoff: Optional[datetime] = None
    if days_back > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))

    order = [{"field_name": "created_at", "direction": "desc"}]
    filters = _build_filters(
        ["note_links", "in", note_link_vals],
        cutoff,
    )

    try:
        raw = sg.find("Note", filters, _NOTE_FIELDS, limit=limit, order=order)
    except Exception:
        # Fallback: OR filter for older SG API versions (max 10 shots)
        logger.debug("note_links 'in' filter failed, falling back to OR filter")
        try:
            raw = _fallback_or_query(sg, shot_ids[:10], cutoff, limit, order)
        except Exception as exc:
            raise ShotGridError(f"노트 조회 실패: {exc}") from exc

    return [_format_note(n) for n in (raw or [])]


def _build_filters(
    link_clause: List[Any],
    cutoff: Optional[datetime],
) -> List[Any]:
    filters = [link_clause]
    if cutoff is not None:
        filters.append(["created_at", "greater_than", cutoff])
    return filters


def _fallback_or_query(
    sg: Any,
    shot_ids: List[int],
    cutoff: Optional[datetime],
    limit: int,
    order: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    or_filters = [["note_links", "is", {"type": "Shot", "id": int(sid)}] for sid in shot_ids]
    or_clause: Dict[str, Any] = {
        "filter_operator": "any",
        "filters": or_filters,
    }
    filters: List[Any] = [or_clause]
    if cutoff is not None:
        filters.append(["created_at", "greater_than", cutoff])
    return sg.find("Note", filters, _NOTE_FIELDS, limit=limit, order=order)


def _format_note(n: Dict[str, Any]) -> Dict[str, Any]:
    links = n.get("note_links") or []
    shot_names = [
        lk.get("name") or lk.get("code") or ""
        for lk in links
        if (lk.get("type") or "").lower() == "shot"
    ]
    context = ", ".join(s for s in shot_names if s) or "—"

    proj = n.get("project") or {}
    proj_name = (proj.get("name") or "").strip() or "—"

    author = n.get("created_by") or {}
    author_name = (author.get("name") or "").strip() or "—"

    created_at = n.get("created_at")
    if hasattr(created_at, "strftime"):
        ts_str = created_at.strftime("%Y-%m-%d %H:%M")
    else:
        ts_str = str(created_at or "—")

    return {
        "note_id": n.get("id"),
        "subject": (n.get("subject") or "").strip(),
        "content": (n.get("content") or "").strip(),
        "timestamp": ts_str,
        "author": author_name,
        "context": context,
        "project_name": proj_name,
    }
