"""ShotGrid TimeLog entity creation."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.timelogs")


def _should_retry_time_log_create_audit(exc: BaseException) -> bool:
    """감사 필드(created_by / updated_by) 때문에 create만 거부된 경우에만 재시도."""
    s = str(exc).lower()
    if "created_by" in s:
        return True
    if "updated_by" in s:
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

    ``created_by`` / ``updated_by`` 는 ShotGrid에서 **create 시에만** 설정 가능한 사이트가 많다.
    따라서 create 페이로드에 넣고, 거부 시 감사 필드 조합을 줄여 재시도한다.
    사후 update 는 하지 않는다.
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

    attempts: List[Dict[str, Any]] = [
        {**data, "created_by": human_user, "updated_by": human_user},
        {**data, "created_by": human_user},
        {**data, "updated_by": human_user},
        data,
    ]

    try:
        result: Optional[Dict[str, Any]] = None
        for i, payload in enumerate(attempts):
            try:
                result = sg.create("TimeLog", payload)
                if i > 0:
                    logger.info(
                        "TimeLog create: 감사 필드 변형 %d/%d 로 성공",
                        i + 1,
                        len(attempts),
                    )
                break
            except Exception as exc:
                is_last = i == len(attempts) - 1
                if is_last:
                    raise
                if not _should_retry_time_log_create_audit(exc):
                    raise
                logger.warning(
                    "TimeLog create 거부 — 감사 필드 조합 축소 후 재시도: %s",
                    exc,
                )
        if result is None:
            raise RuntimeError("TimeLog create returned no result")

        logger.info(
            "TimeLog created: id=%s task=%d user=%d duration=%dmin",
            result.get("id"),
            task_id,
            user_id,
            duration_minutes,
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
