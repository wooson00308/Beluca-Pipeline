"""컨펌 창의 보내기 — 노트 만들기와 태스크 상태 바꾸기를 따로 성공/실패로 알려 준다.

기존 피드백 탭은 노트가 간 뒤 상태 변경이 실패하면 전체를 "실패"로 알려서, 다시 누르면
노트가 두 번 갔다. 여기서는 결과를 나눠 돌려주고, 이미 간 노트는 다시 만들지 않는다.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from bpe.core.logging import get_logger
from bpe.shotgrid.client import get_default_sg, get_shotgun_for_version_mutation, resolve_sudo_login
from bpe.shotgrid.notes import build_native_style_note_subject, create_note_with_result
from bpe.shotgrid.tasks import update_task_status
from bpe.shotgrid.users import guess_human_user_for_me

logger = get_logger("shotgrid.confirm_submit")

EMPTY_NOTE_TEXT = "(이미지 피드백)"


class ConfirmSubmitResult(NamedTuple):
    note_needed: bool
    note_ok: bool
    note_id: Optional[int]
    note_error: str
    attachment_ok: bool
    attachment_error: str
    status_needed: bool
    status_ok: bool
    status_error: str

    @property
    def all_ok(self) -> bool:
        note_fine = (not self.note_needed) or (self.note_ok and self.attachment_ok)
        status_fine = (not self.status_needed) or self.status_ok
        return note_fine and status_fine


def addressings_for_confirm(assignees: Any) -> List[Dict[str, Any]]:
    """태스크 담당에서 노트 받는 사람 — 사람과 그룹(외주 업체) 둘 다 넣는다."""
    out: List[Dict[str, Any]] = []
    if not isinstance(assignees, list):
        return out
    for a in assignees:
        if not isinstance(a, dict) or a.get("type") not in ("HumanUser", "Group"):
            continue
        try:
            out.append({"type": str(a["type"]), "id": int(a["id"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def open_submit_session() -> Tuple[Any, Optional[Dict[str, Any]]]:
    """노트를 쓸 연결과 작성자(나). 피드백 탭과 같은 방식(sudo 로그인)."""
    base_sg = get_default_sg()
    me = guess_human_user_for_me(base_sg)
    sudo_login = (os.environ.get("BPE_FEEDBACK_NOTE_SUDO_LOGIN") or "").strip()
    if not sudo_login and me and me.get("id") is not None:
        try:
            sudo_login = (resolve_sudo_login(base_sg, int(me["id"])) or "").strip()
        except Exception:
            sudo_login = ""
        if not sudo_login:
            sudo_login = (me.get("login") or "").strip()
    sg = get_shotgun_for_version_mutation(sudo_login) if sudo_login else base_sg
    return sg, me


def note_subject(me: Optional[Dict[str, Any]], version_code: str, shot_code: str) -> str:
    name = ((me or {}).get("name") or (me or {}).get("login") or "").strip()
    return build_native_style_note_subject(name, version_code or None, shot_code)


def submit_confirm(
    sg: Any,
    *,
    project_id: int,
    shot_id: int,
    version_id: Optional[int],
    task_id: Optional[int],
    status_code: str,
    status_field: Optional[str],
    subject: str,
    content: str,
    attachment_paths: Optional[List[str]] = None,
    author_user: Optional[Dict[str, Any]] = None,
    addressings_to: Optional[List[Dict[str, Any]]] = None,
    addressings_cc: Optional[List[Dict[str, Any]]] = None,
    existing_note_id: Optional[int] = None,
) -> ConfirmSubmitResult:
    """노트(메모·그림이 있을 때만)를 보내고, 상태(고른 경우만)를 바꾼다.

    *existing_note_id* 가 있으면 노트는 이미 간 것으로 보고 다시 만들지 않는다
    (상태만 다시 시도할 때).
    """
    text = (content or "").strip()
    paths = [p for p in (attachment_paths or []) if p]
    note_needed = bool(text or paths)
    note_ok, note_id, note_error = False, existing_note_id, ""
    attachment_ok, attachment_error = True, ""

    if existing_note_id is not None:
        note_ok = True
    elif note_needed:
        try:
            res = create_note_with_result(
                sg,
                project_id=int(project_id),
                shot_id=int(shot_id),
                subject=subject,
                content=text or EMPTY_NOTE_TEXT,
                version_id=version_id,
                attachment_path=None,
                attachment_paths=paths or None,
                author_user=author_user,
                addressings_to=addressings_to or None,
                addressings_cc=addressings_cc or None,
            )
        except Exception as e:
            logger.warning("confirm submit: note create failed: %s", e)
            note_error = str(e) or type(e).__name__
        else:
            row = res.note if isinstance(res.note, dict) else {}
            if row.get("id") is not None:
                note_ok, note_id = True, int(row["id"])
                if res.attachment_requested and not res.attachment_ok:
                    attachment_ok = False
                    attachment_error = res.attachment_error or "그림을 올리지 못했습니다"
            else:
                note_error = "노트가 만들어지지 않았습니다"

    code = (status_code or "").strip()
    status_needed = bool(code and task_id is not None)
    status_ok, status_error = False, ""
    if status_needed and (note_ok or not note_needed):
        try:
            update_task_status(sg, int(task_id), code, field_name=(status_field or None))  # type: ignore[arg-type]
            status_ok = True
        except Exception as e:
            logger.warning("confirm submit: status update failed: %s", e)
            status_error = str(e) or type(e).__name__
    elif status_needed:
        status_error = "노트를 보내지 못해 상태는 바꾸지 않았습니다"

    return ConfirmSubmitResult(
        note_needed=note_needed,
        note_ok=note_ok,
        note_id=note_id,
        note_error=note_error,
        attachment_ok=attachment_ok,
        attachment_error=attachment_error,
        status_needed=status_needed,
        status_ok=status_ok,
        status_error=status_error,
    )
