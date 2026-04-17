"""Tests for bpe.shotgrid.timelogs — create_time_log."""

from __future__ import annotations

from datetime import date

import pytest

from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.timelogs import create_time_log, sum_duration_minutes_for_user_date
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
        assert log.get("created_by") == {"type": "HumanUser", "id": 30}
        assert log.get("updated_by") == {"type": "HumanUser", "id": 30}

    def test_create_retries_audit_fields_when_created_by_rejected(self) -> None:
        class RejectCreatedByMock(MockShotgun):
            def create(self, entity_type: str, data: dict) -> dict:  # type: ignore[override]
                if entity_type == "TimeLog" and "created_by" in data:
                    raise ValueError("Field created_by is read-only on TimeLog")
                return super().create(entity_type, data)

        sg = RejectCreatedByMock()
        sg._add_entity("Project", {"id": 10, "name": "TestProj"})
        sg._add_entity("Task", {"id": 20, "content": "comp"})
        sg._add_entity("HumanUser", {"id": 30, "name": "Artist A", "login": "artistA"})
        create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=20)
        logs = sg.find("TimeLog", [], None)
        assert len(logs) == 1
        assert logs[0]["duration"] == 20
        assert logs[0]["user"] == {"type": "HumanUser", "id": 30}
        assert logs[0].get("updated_by") == {"type": "HumanUser", "id": 30}
        assert "created_by" not in logs[0]

    def test_create_does_not_retry_on_unrelated_error(self) -> None:
        class BoomCreateMock(MockShotgun):
            def create(self, entity_type: str, data: dict) -> dict:  # type: ignore[override]
                raise RuntimeError("connection reset by peer")

        sg = BoomCreateMock()
        sg._add_entity("Project", {"id": 10, "name": "TestProj"})
        sg._add_entity("Task", {"id": 20, "content": "comp"})
        sg._add_entity("HumanUser", {"id": 30, "name": "Artist A", "login": "artistA"})
        with pytest.raises(ShotGridError, match="TimeLog 생성 실패"):
            create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=10)
        assert sg.find("TimeLog", [], None) == []

    def test_create_succeeds_with_updated_by_only_when_created_by_rejected_on_create(self) -> None:
        """created_by 가 create 에서 거부되면 updated_by 만 넣은 변형으로 성공하는 사이트."""

        class SplitAuditMock(MockShotgun):
            def create(self, entity_type: str, data: dict) -> dict:  # type: ignore[override]
                if entity_type == "TimeLog" and "created_by" in data:
                    raise ValueError("created_by rejected on create")
                return super().create(entity_type, data)

        sg = SplitAuditMock()
        sg._add_entity("Project", {"id": 10, "name": "TestProj"})
        sg._add_entity("Task", {"id": 20, "content": "comp"})
        sg._add_entity("HumanUser", {"id": 30, "name": "Artist A", "login": "artistA"})
        result = create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=25)
        assert result.get("type") == "TimeLog"
        logs = sg.find("TimeLog", [], None)
        assert len(logs) == 1
        assert logs[0].get("updated_by") == {"type": "HumanUser", "id": 30}
        assert "created_by" not in logs[0]

    def test_create_success_without_post_update_calls(self) -> None:
        sg = _base_sg()
        result = create_time_log(sg, project_id=10, task_id=20, user_id=30, duration_minutes=15)
        assert result.get("type") == "TimeLog"
        assert result.get("id") is not None
        logs = sg.find("TimeLog", [], None)
        assert len(logs) == 1
        assert logs[0].get("created_by") == {"type": "HumanUser", "id": 30}
        assert logs[0].get("updated_by") == {"type": "HumanUser", "id": 30}

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


class TestSumDurationMinutesForUserDate:
    def test_sums_all_projects_when_project_id_none(self) -> None:
        sg = MockShotgun()
        d = date(2026, 3, 10)
        sg._add_entity(
            "TimeLog",
            {
                "duration": 45,
                "user": {"type": "HumanUser", "id": 30},
                "date": d.isoformat(),
                "project": {"type": "Project", "id": 10},
            },
        )
        sg._add_entity(
            "TimeLog",
            {
                "duration": 15,
                "user": {"type": "HumanUser", "id": 30},
                "date": d.isoformat(),
                "project": {"type": "Project", "id": 11},
            },
        )
        total = sum_duration_minutes_for_user_date(sg, user_id=30, target_date=d, project_id=None)
        assert total == 60

    def test_filters_by_project(self) -> None:
        sg = MockShotgun()
        d = date(2026, 3, 11)
        sg._add_entity(
            "TimeLog",
            {
                "duration": 100,
                "user": {"type": "HumanUser", "id": 1},
                "date": d.isoformat(),
                "project": {"type": "Project", "id": 99},
            },
        )
        sg._add_entity(
            "TimeLog",
            {
                "duration": 5,
                "user": {"type": "HumanUser", "id": 1},
                "date": d.isoformat(),
                "project": {"type": "Project", "id": 100},
            },
        )
        assert (
            sum_duration_minutes_for_user_date(sg, user_id=1, target_date=d, project_id=99) == 100
        )
