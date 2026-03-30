"""ShotGrid TimeLog entity creation."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.timelogs")


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

    data: Dict[str, Any] = {
        "project": {"type": "Project", "id": int(project_id)},
        "entity": {"type": "Task", "id": int(task_id)},
        "user": {"type": "HumanUser", "id": int(user_id)},
        "duration": int(duration_minutes),
        "description": (description or "").strip(),
        "date": record_date,
    }

    try:
        result = sg.create("TimeLog", data)
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
