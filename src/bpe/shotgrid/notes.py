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
    shot_ids: List[int] = []
    shot_names: List[str] = []
    version_code: Optional[str] = None

    for lk in links:
        lk_type = (lk.get("type") or "").lower()
        name = lk.get("name") or lk.get("code") or ""
        if lk_type == "shot":
            sid = lk.get("id")
            if sid is not None:
                try:
                    shot_ids.append(int(sid))
                except (TypeError, ValueError):
                    pass
            if name:
                shot_names.append(str(name))
        elif lk_type == "version" and version_code is None:
            # Note에 연결된 첫 번째 Version 엔티티의 code를 사용
            if name:
                version_code = str(name).strip() or None

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
        "shot_ids": shot_ids,
        "shot_names": shot_names,
        "version_code": version_code,  # e.g. "S100_0140_comp_v007" — None이면 RV 버튼 비활성화
    }


_ATTACHMENT_FIELDS = ["id", "this_file", "filename", "image"]

_IMAGE_EXT = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})


def _guess_ext_from_name(name: str) -> str:
    if not name or "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _is_image_filename(filename: str) -> bool:
    ext = _guess_ext_from_name(filename)
    return ext in _IMAGE_EXT if ext else False


def _ext_from_url_path(path: str) -> str:
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1].lower().split("?")[0]


def _is_image_attachment(filename: str, url: str) -> bool:
    if _is_image_filename(filename):
        return True
    if url:
        from urllib.parse import urlparse

        p = urlparse(url).path
        ext = _ext_from_url_path(p)
        if ext in _IMAGE_EXT:
            return True
    return False


def _format_attachment_meta(att: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    att_id = att.get("id")
    if att_id is None:
        return None
    fname = (att.get("filename") or "").strip()
    if not fname:
        tf = att.get("this_file") or {}
        if isinstance(tf, dict):
            fname = (tf.get("name") or tf.get("display_name") or "").strip()
    url = ""
    tf = att.get("this_file") or {}
    if isinstance(tf, dict):
        url = (tf.get("url") or "").strip()
    img = att.get("image")
    if not url and isinstance(img, dict):
        url = (img.get("url") or "").strip()
    return {
        "att_id": int(att_id),
        "filename": fname,
        "url": url,
    }


def get_note_attachments(sg: Any, note_id: int) -> List[Dict[str, Any]]:
    """Return image Attachment metadata for a Note (newest API filter first)."""
    nid = int(note_id)
    primary = [
        ["attachment_links", "is", {"type": "Note", "id": nid}],
    ]
    fallback = [
        ["note", "is", {"type": "Note", "id": nid}],
    ]
    raw: List[Dict[str, Any]] = []
    try:
        raw = list(sg.find("Attachment", primary, _ATTACHMENT_FIELDS) or [])
    except Exception as exc:
        logger.debug("get_note_attachments primary filter failed: %s", exc)
        raw = []
    if not raw:
        try:
            raw = list(sg.find("Attachment", fallback, _ATTACHMENT_FIELDS) or [])
        except Exception as exc2:
            logger.warning("get_note_attachments failed: %s", exc2)
            return []
    out: List[Dict[str, Any]] = []
    for att in raw:
        meta = _format_attachment_meta(att)
        if meta is None:
            continue
        if not _is_image_attachment(meta.get("filename") or "", meta.get("url") or ""):
            continue
        out.append(meta)
    return out


def download_attachment_bytes(sg: Any, meta: Dict[str, Any]) -> Optional[bytes]:
    """Download bytes for one attachment (URL, then SG API fallbacks)."""
    import urllib.request

    url = (meta.get("url") or "").strip()
    att_id = meta.get("att_id")
    if not url and att_id is not None:
        try:
            url = str(sg.get_attachment_download_url(int(att_id))).strip()
        except Exception as exc:
            logger.debug("get_attachment_download_url failed: %s", exc)
            url = ""
    if url:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read()
        except Exception as exc:
            logger.debug("attachment url download failed: %s", exc)
    if att_id is not None:
        try:
            data = sg.download_attachment(attachment_id=int(att_id))
            if isinstance(data, bytes):
                return data
        except Exception as exc:
            logger.debug("download_attachment failed: %s", exc)
    return None
