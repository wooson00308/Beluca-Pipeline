"""Tests for bpe.shotgrid.timelogs — create_time_log."""

from __future__ import annotations

from datetime import date

import pytest

from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.timelogs import create_time_log
from tests.shotgrid.mock_sg import MockShotgun


def _base_sg() -> MockShotgun:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 10, "name": "TestProj"})
    sg._add_entity("Task", {"id": 20, "content": "comp"})
    sg._add_entity("HumanUser", {"id": 30, "name": "Artist A", "login": "artistA"})
    return sg


class TestCreateTimeLog:
    def test_basic_creation(self) -> None:
        sg = _base_sg()
        result = create_time_log(
            sg,
            project_id=10,
            task_id=20,
            user_id=30,
            duration_minutes=90,
            description="comp work",
        )
        assert result["type"] == "TimeLog"
        assert "id" in result

    def test_stored_fields(self) -> None:
        sg = _base_sg()
        create_time_log(
            sg,
            project_id=10,
            task_id=20,
            user_id=30,
            duration_minutes=60,
            description="컴포지팅",
        )
        logs = sg.find("TimeLog", [], None)
        assert len(logs) == 1
        log = logs[0]
        assert log["duration"] == 60
        assert log["description"] == "컴포지팅"
        assert log["project"] == {"type": "Project", "id": 10}
        assert log["entity"] == {"type": "Task", "id": 20}
        assert log["user"] == {"type": "HumanUser", "id": 30}

    def test_custom_date(self) -> None:
        sg = _base_sg()
        custom = date(2026, 1, 15)
        create_time_log(
            sg,
            project_id=10,
            task_id=20,
            user_id=30,
            duration_minutes=30,
            log_date=custom,
        )
        logs = sg.find("TimeLog", [], None)
        assert logs[0]["date"] == "2026-01-15"

    def test_default_date_is_today(self) -> None:
        sg = _base_sg()
        create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=45)
        logs = sg.find("TimeLog", [], None)
        assert logs[0]["date"] == date.today().isoformat()

    def test_zero_duration_raises(self) -> None:
        sg = _base_sg()
        with pytest.raises(ShotGridError, match="1분 이상"):
            create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=0)

    def test_negative_duration_raises(self) -> None:
        sg = _base_sg()
        with pytest.raises(ShotGridError, match="1분 이상"):
            create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=-5)

    def test_empty_description_is_stored_as_empty(self) -> None:
        sg = _base_sg()
        create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=10)
        logs = sg.find("TimeLog", [], None)
        assert logs[0]["description"] == ""

    def test_multiple_logs(self) -> None:
        sg = _base_sg()
        create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=30)
        create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=60)
        logs = sg.find("TimeLog", [], None)
        assert len(logs) == 2
        durations = {log["duration"] for log in logs}
        assert durations == {30, 60}
