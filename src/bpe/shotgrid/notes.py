"""ShotGrid Note queries for shot-linked comments."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from bpe.core.feedback_file_log import append_feedback_log_verbose
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.shotgun_upload_trace import (
    ensure_shotgun_upload_trace_logging_configured,
    exception_trace_preview,
    is_shotgun_upload_trace_enabled,
    upload_source_path_meta,
)
from bpe.core.upload_exc_diag import sg_upload_exception_diag
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.notes")

_NOTE_UPLOAD_RETRIES = 4
# 먼저 표준 attachments 필드, 실패 시 field 없이 클래식 업로드
# (S3 직접 업로드와 경로가 달라질 수 있음).
_NOTE_UPLOAD_FIELD_STRATEGIES: Tuple[Optional[str], ...] = ("attachments", None)


def build_native_style_note_subject(
    author_display_name: str,
    version_code: Optional[str],
    shot_code: str,
) -> str:
    """ShotGrid 웹과 유사한 Note subject (예: Name's Note on Version and Shot).

    버전이 없으면 한 절만 사용한다.
    """
    name = (author_display_name or "").strip() or "User"
    shot = (shot_code or "").strip() or "—"
    ver = (version_code or "").strip()
    if ver:
        return f"{name}'s Note on {ver} and {shot}"
    return f"{name}'s Note on {shot}"


_NOTE_UPLOAD_RETRY_SLEEP_BASE = 2.0


def _absolute_attachment_path_for_upload(raw: str) -> str:
    """업로드용 절대 경로(UNC는 normalize_path_str로 드라이브 형태로)."""
    p = Path((raw or "").strip())
    try:
        base = p.resolve()
    except OSError:
        base = p
    return normalize_path_str(str(base))


def _upload_note_file_with_strategies(
    sg: Any,
    note: Dict[str, Any],
    attachment_path: str,
    nid: int,
) -> Tuple[bool, Optional[str]]:
    """attachments 필드 업로드 실패 시 field 없이 재시도. 성공 시 (True, None)."""
    abs_path = _absolute_attachment_path_for_upload(attachment_path)
    try:
        n = int(note["id"])
    except (TypeError, ValueError, KeyError):
        return False, "invalid note id"
    last_err: Optional[str] = None
    ensure_shotgun_upload_trace_logging_configured()
    append_feedback_log_verbose(
        "note_upload_precheck",
        note_id=nid,
        **upload_source_path_meta(abs_path),
    )
    for attempt in range(1, _NOTE_UPLOAD_RETRIES + 1):
        for strat in _NOTE_UPLOAD_FIELD_STRATEGIES:
            label = strat if strat is not None else "field_none"
            append_feedback_log_verbose(
                "note_attachment_try",
                note_id=nid,
                attempt=attempt,
                max_attempts=_NOTE_UPLOAD_RETRIES,
                strategy=label,
            )
            try:
                if strat is None:
                    sg.upload("Note", n, abs_path)
                else:
                    sg.upload("Note", n, abs_path, strat)
                append_feedback_log_verbose(
                    "note_attachment_ok",
                    note_id=nid,
                    attempt=attempt,
                    strategy=label,
                )
                return True, None
            except Exception as exc:
                last_err = str(exc)
                _prev = (last_err or "").replace("\r", " ").replace("\n", " ")[:240]
                _fail_payload: Dict[str, Any] = {
                    "note_id": nid,
                    "attempt": attempt,
                    "strategy": label,
                    "err_type": type(exc).__name__,
                    "err_len": len(last_err or ""),
                    "err_preview": _prev,
                    "upload_diag": sg_upload_exception_diag(exc),
                }
                if is_shotgun_upload_trace_enabled():
                    _fail_payload["exc_trace_preview"] = exception_trace_preview(exc)
                append_feedback_log_verbose("note_attachment_try_failed", **_fail_payload)
                logger.warning(
                    "Note 첨부 업로드 실패 (attempt=%d strategy=%s): %s",
                    attempt,
                    label,
                    exc,
                )
        if attempt < _NOTE_UPLOAD_RETRIES:
            time.sleep(float(attempt) * _NOTE_UPLOAD_RETRY_SLEEP_BASE)
    return False, last_err


def note_addressings_from_assignees(assignees: Any) -> List[Dict[str, Any]]:
    """Task.task_assignees 등에서 Note.addressings_to 용 HumanUser 링크만 추린다."""
    out: List[Dict[str, Any]] = []
    if not assignees:
        return out
    if not isinstance(assignees, list):
        return out
    for a in assignees:
        if not isinstance(a, dict):
            continue
        if (a.get("type") or "").strip() != "HumanUser":
            continue
        i = a.get("id")
        if i is None:
            continue
        try:
            out.append({"type": "HumanUser", "id": int(i)})
        except (TypeError, ValueError):
            continue
    return out


class CreateNoteResult(NamedTuple):
    """Result of creating a Note with optional attachment upload."""

    note: Dict[str, Any]
    attachment_requested: bool
    attachment_ok: bool
    attachment_error: Optional[str]


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


def list_notes_for_project(
    sg: Any,
    project_id: int,
    *,
    limit: int = 400,
    days_back: int = 14,
) -> List[Dict[str, Any]]:
    """Return Notes in *project*, newest first (optionally limited to recent *days_back*)."""
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return []
    if pid <= 0:
        return []

    cutoff: Optional[datetime] = None
    if days_back > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))

    link_clause = ["project", "is", {"type": "Project", "id": pid}]
    filters = _build_filters(link_clause, cutoff)
    order = [{"field_name": "created_at", "direction": "desc"}]
    try:
        raw = sg.find("Note", filters, _NOTE_FIELDS, limit=limit, order=order)
    except Exception as exc:
        raise ShotGridError(f"노트 조회 실패: {exc}") from exc
    return [_format_note(n) for n in (raw or [])]


def create_note_with_result(
    sg: Any,
    *,
    project_id: int,
    shot_id: int,
    subject: str,
    content: str,
    version_id: Optional[int] = None,
    attachment_path: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    author_user: Optional[Dict[str, Any]] = None,
    addressings_to: Optional[List[Dict[str, Any]]] = None,
    addressings_cc: Optional[List[Dict[str, Any]]] = None,
) -> CreateNoteResult:
    """ShotGrid에 Note를 생성하고 선택적으로 이미지를 첨부한다. 첨부 실패 여부를 반환한다.

    ``attachment_paths``가 비어 있지 않으면 여러 파일을 순서대로 업로드한다.
    그렇지 않고 ``attachment_path``만 있으면 단일 첨부와 동일하다.
    """
    links: List[Dict[str, Any]] = [{"type": "Shot", "id": int(shot_id)}]
    if version_id is not None:
        links.append({"type": "Version", "id": int(version_id)})
    data: Dict[str, Any] = {
        "project": {"type": "Project", "id": int(project_id)},
        "note_links": links,
        "subject": (subject.strip() or "(BPE 피드백)"),
        "content": (content or "").strip(),
    }
    if author_user and author_user.get("id") is not None:
        try:
            data["user"] = {"type": "HumanUser", "id": int(author_user["id"])}
        except (TypeError, ValueError):
            pass
    if addressings_to:
        data["addressings_to"] = addressings_to
    if addressings_cc is not None:
        data["addressings_cc"] = addressings_cc
    elif addressings_to:
        data["addressings_cc"] = addressings_to
    try:
        note = sg.create("Note", data)
    except Exception as exc:
        raise ShotGridError(f"Note 생성 실패: {exc}") from exc
    try:
        nid = int(note["id"])
    except (TypeError, ValueError, KeyError):
        nid = 0
    append_feedback_log_verbose("note_sg_create_ok", note_id=nid)
    att_err: Optional[str] = None
    att_ok = True
    paths: List[str] = []
    if attachment_paths:
        paths = [str(p).strip() for p in attachment_paths if p and str(p).strip()]
    elif attachment_path and str(attachment_path).strip():
        paths = [str(attachment_path).strip()]
    requested = bool(paths)
    for pth in paths:
        att_ok, att_err = _upload_note_file_with_strategies(sg, note, pth, nid)
        if not att_ok:
            if att_err is None:
                att_err = "upload failed"
            break
    return CreateNoteResult(
        note=note,
        attachment_requested=requested,
        attachment_ok=att_ok if requested else True,
        attachment_error=att_err,
    )


def create_note(
    sg: Any,
    *,
    project_id: int,
    shot_id: int,
    subject: str,
    content: str,
    version_id: Optional[int] = None,
    attachment_path: Optional[str] = None,
    author_user: Optional[Dict[str, Any]] = None,
    addressings_to: Optional[List[Dict[str, Any]]] = None,
    addressings_cc: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """ShotGrid에 Note를 생성하고 선택적으로 이미지를 첨부한다."""
    return create_note_with_result(
        sg,
        project_id=project_id,
        shot_id=shot_id,
        subject=subject,
        content=content,
        version_id=version_id,
        attachment_path=attachment_path,
        author_user=author_user,
        addressings_to=addressings_to,
        addressings_cc=addressings_cc,
    ).note


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


def _is_missing_attachment_note_field_error(exc: BaseException) -> bool:
    """Some sites have no Attachment.note; API returns read() field missing."""
    msg = str(exc).lower()
    return "doesn't exist" in msg or "does not exist" in msg


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
            if _is_missing_attachment_note_field_error(exc2):
                logger.debug("get_note_attachments: skip note filter (schema): %s", exc2)
                return []
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
