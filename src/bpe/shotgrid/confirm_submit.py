"""컨펌 창의 보내기 — 노트 만들기와 상태 바꾸기(태스크·버전)를 따로 성공/실패로 알려 준다.

기존 피드백 탭은 노트가 간 뒤 상태 변경이 실패하면 전체를 "실패"로 알려서, 다시 누르면
노트가 두 번 갔다. 여기서는 결과를 나눠 돌려주고, 이미 간 노트는 다시 만들지 않는다.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from bpe.core.confirm_guide_note import (
    SOURCE_TASKS,
    TASK_EDIT,
    TASK_PLATE,
    match_version,
    pick_note_version,
)
from bpe.core.confirm_media import twin_version_key
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
    # 버전 상태 — 샷그리드 버전 목록의 상태 칸. 태스크 상태와 같은 값으로 함께 바꾼다.
    version_needed: bool = False
    version_ok: bool = False
    version_count: int = 0
    version_error: str = ""

    @property
    def all_ok(self) -> bool:
        note_fine = (not self.note_needed) or (self.note_ok and self.attachment_ok)
        status_fine = (not self.status_needed) or self.status_ok
        version_fine = (not self.version_needed) or self.version_ok
        return note_fine and status_fine and version_fine


VERSION_STATUS_FIELD = "sg_status_list"


def version_ids_with_twins(sg: Any, version_id: Optional[int]) -> List[int]:
    """상태를 함께 바꿀 버전들 — 그 버전과, 같은 샷에 올라온 쌍둥이(``_v003`` ↔ ``_v003_lut``).

    쌍둥이를 못 읽어도 원래 버전 하나는 돌려준다.
    """
    if version_id is None:
        return []
    ids = [int(version_id)]
    try:
        me = sg.find_one("Version", [["id", "is", int(version_id)]], ["code", "entity"])
        code = str((me or {}).get("code") or "").strip()
        entity = (me or {}).get("entity")
        if not code or not isinstance(entity, dict) or entity.get("id") is None:
            return ids
        key = twin_version_key(code)
        link = {"type": str(entity.get("type") or "Shot"), "id": int(entity["id"])}
        for v in sg.find("Version", [["entity", "is", link]], ["id", "code"]) or []:
            vid = v.get("id")
            if vid is None or int(vid) in ids:
                continue
            if twin_version_key(str(v.get("code") or "")) == key:
                ids.append(int(vid))
    except Exception as e:
        logger.warning("confirm submit: twin version lookup failed: %s", e)
    return ids


def update_version_statuses(sg: Any, version_ids: List[int], status_code: str) -> Tuple[int, str]:
    """버전들의 상태를 바꾼다 → ``(바뀐 개수, 첫 오류 글)``. 하나가 실패해도 나머지는 시도한다."""
    done, error = 0, ""
    for vid in version_ids:
        try:
            sg.update("Version", int(vid), {VERSION_STATUS_FIELD: status_code})
            done += 1
        except Exception as e:
            logger.warning("confirm submit: version %s status update failed: %s", vid, e)
            error = error or (str(e) or type(e).__name__)
    return done, error


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


def source_versions(sg: Any, shot_id: int) -> List[Dict[str, Any]]:
    """샷의 edit·org 태스크 버전들 — 최근 것이 앞. ``[{"id", "code", "task"}]``."""
    rows = (
        sg.find(
            "Version",
            [
                ["entity", "is", {"type": "Shot", "id": int(shot_id)}],
                ["sg_task.Task.content", "in", [TASK_EDIT, TASK_PLATE]],
            ],
            ["id", "code", "sg_task"],
            order=[{"field_name": "created_at", "direction": "desc"}],
        )
        or []
    )
    out: List[Dict[str, Any]] = []
    for v in rows:
        task = v.get("sg_task") if isinstance(v.get("sg_task"), dict) else {}
        if v.get("id") is None:
            continue
        out.append(
            {
                "id": int(v["id"]),
                "code": str(v.get("code") or ""),
                "task": str(task.get("name") or "").strip().lower(),
                "task_id": task.get("id"),
            }
        )
    return out


def guide_note_target(
    sg: Any,
    shot_id: int,
    *,
    codes: Dict[str, str],
    drawn: List[str],
    shown: str,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Annotation 노트를 붙일 버전 → ``(그린 영상, 버전)``. 붙일 버전이 없으면 ``("", None)``.

    *codes* 는 ``{영상: 연 파일의 이름}`` — 같은 이름의 버전을 먼저 찾는다.
    샷그리드에서 직접 그려 올린 노트처럼 edit·org 버전에 붙여야 guide 봇이 집어 간다.
    """
    versions = source_versions(sg, shot_id)
    found = {
        source: match_version(versions, task, codes.get(source, ""))
        for source, task in SOURCE_TASKS.items()
    }
    return pick_note_version(drawn, shown, found)


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
    with_version_status: bool = True,
    empty_note_text: str = EMPTY_NOTE_TEXT,
    note_task_id: Optional[int] = None,
) -> ConfirmSubmitResult:
    """노트(메모·그림이 있을 때만)를 보내고, 상태(고른 경우만)를 바꾼다.

    상태는 태스크와 버전(그리고 그 버전의 쌍둥이 ``_lut`` 버전)을 같은 값으로 함께 바꾼다.
    *existing_note_id* 가 있으면 노트는 이미 간 것으로 보고 다시 만들지 않는다
    (상태만 다시 시도할 때 — 이미 바뀐 쪽에 같은 값을 다시 써도 해가 없다).
    *empty_note_text* 는 글 없이 그림만 보낼 때 본문에 넣는 글 — Annotation 은 빈 글을 준다
    (노트에는 쓴 사람의 글만 들어간다).
    *note_task_id* 는 노트의 Tasks 칸에 걸 태스크(노트가 붙는 버전의 태스크) — 샷그리드에서
    직접 단 노트와 같은 모양이라, 나중에 guide 로 표시했을 때 봇이 다루던 노트와 다르지 않다.
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
                content=text or empty_note_text,
                version_id=version_id,
                attachment_path=None,
                attachment_paths=paths or None,
                author_user=author_user,
                addressings_to=addressings_to or None,
                addressings_cc=addressings_cc or None,
                task_ids=[int(note_task_id)] if note_task_id is not None else None,
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

    version_needed = bool(code and version_id is not None and with_version_status)
    version_ok, version_count, version_error = False, 0, ""
    if version_needed and (note_ok or not note_needed):
        targets = version_ids_with_twins(sg, version_id)
        version_count, version_error = update_version_statuses(sg, targets, code)
        version_ok = bool(targets) and version_count == len(targets)
    elif version_needed:
        version_error = "노트를 보내지 못해 버전 상태는 바꾸지 않았습니다"

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
        version_needed=version_needed,
        version_ok=version_ok,
        version_count=version_count,
        version_error=version_error,
    )
