"""ShotGrid TimeLog entity creation."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.timelogs")


def _should_retry_time_log_create_without_created_by(exc: BaseException) -> bool:
    """`created_by`를 넣은 create만 실패한 경우에만 재시도한다(권한·네트워크 등은 재시도 안 함)."""
    s = str(exc).lower()
    if "created_by" in s:
        return True
    if "unknown field" in s:
        return True
    if "invalid" in s and "field" in s:
        return True
    if "read-only" in s or "read only" in s:
        return True
    if "not editable" in s:
        return True
    if "following keys" in s and "invalid" in s:
        return True
    return False


def create_time_log(
    sg: Any,
    *,
    project_id: int,
    task_id: int,
    user_id: int,
    duration_minutes: int,
    description: str = "",
    log_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Create a TimeLog entity on ShotGrid.

    Parameters
    ----------
    sg:
        Authenticated Shotgun instance.
    project_id:
        ShotGrid Project entity ID.
    task_id:
        ShotGrid Task entity ID (the TimeLog ``entity`` link field).
    user_id:
        ShotGrid HumanUser entity ID.
    duration_minutes:
        Time spent in **minutes** (must be >= 1).
    description:
        Optional free-text description.
    log_date:
        Date to record; defaults to today.
    """
    if duration_minutes < 1:
        raise ShotGridError("TimeLog duration은 1분 이상이어야 합니다.")

    record_date = (log_date or date.today()).isoformat()
    human_user = {"type": "HumanUser", "id": int(user_id)}

    data: Dict[str, Any] = {
        "project": {"type": "Project", "id": int(project_id)},
        "entity": {"type": "Task", "id": int(task_id)},
        "user": human_user,
        "duration": int(duration_minutes),
        "description": (description or "").strip(),
        "date": record_date,
    }

    try:
        try:
            result = sg.create("TimeLog", {**data, "created_by": human_user})
        except Exception as exc:
            if _should_retry_time_log_create_without_created_by(exc):
                logger.warning(
                    "TimeLog create(created_by 포함) 거부 — created_by 없이 재시도: %s",
                    exc,
                )
                result = sg.create("TimeLog", data)
            else:
                raise
        logger.info(
            "TimeLog created: id=%s task=%d user=%d duration=%dmin",
            result.get("id"),
            task_id,
            user_id,
            duration_minutes,
        )
        tl_id = result.get("id")
        if tl_id is not None:
            tid = int(tl_id)
            try:
                sg.update("TimeLog", tid, {"updated_by": human_user})
            except Exception as exc:
                logger.warning(
                    "TimeLog updated_by 보정 실패(기록은 생성됨): id=%s err=%s",
                    tl_id,
                    exc,
                )
            try:
                sg.update("TimeLog", tid, {"created_by": human_user})
            except Exception as exc:
                logger.warning(
                    "TimeLog created_by 보정 실패(기록은 생성됨): id=%s err=%s",
                    tl_id,
                    exc,
                )
        return result
    except Exception as e:
        raise ShotGridError(
            f"TimeLog 생성 실패: {e}\nShotGrid 관리자에게 TimeLog 엔티티 권한을 확인해 주세요."
        ) from e


def sum_duration_minutes_for_user_date(
    sg: Any,
    *,
    user_id: int,
    target_date: date,
    project_id: Optional[int] = None,
    limit: int = 2000,
) -> int:
    """Sum TimeLog ``duration`` (minutes) for user on ``target_date``.

    If ``project_id`` is None, sums across all projects.
    """
    ds = target_date.isoformat()
    filters: List[Any] = [
        ["user", "is", {"type": "HumanUser", "id": int(user_id)}],
        ["date", "is", ds],
    ]
    if project_id is not None:
        filters.append(["project", "is", {"type": "Project", "id": int(project_id)}])
    try:
        rows = list(sg.find("TimeLog", filters, ["duration"], limit=int(limit)) or [])
    except Exception as exc:
        logger.warning("sum_duration_minutes_for_user_date find failed: %s", exc)
        return 0
    total = 0
    for r in rows:
        try:
            total += int(r.get("duration") or 0)
        except (TypeError, ValueError):
            pass
    return total
