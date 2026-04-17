"""Tests for list_review_tasks_for_project and related task helpers."""

from __future__ import annotations

from typing import Any, Dict

from bpe.shotgrid.tasks import list_review_tasks_for_project
from tests.shotgrid.mock_sg import MockShotgun


def _task_row(
    tid: int,
    shot_code: str,
    shot_id: int,
    status: str,
    project_id: int = 1,
    proj_code: str = "PROJ",
    *,
    version_user_name: str = "",
    version_created_name: str = "",
    version_created_at: str = "",
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": tid,
        "content": "comp",
        "sg_status_list": status,
        "due_date": None,
        "project": {"type": "Project", "id": project_id, "code": proj_code, "name": proj_code},
        "entity": {
            "type": "Shot",
            "id": shot_id,
            "code": shot_code,
            "description": "",
            "image": None,
        },
        "entity.Shot.code": shot_code,
        "entity.Shot.description": "",
        "entity.Shot.image": None,
        "project.Project.code": proj_code,
        "project.Project.name": proj_code,
        "sg_latest_version": {"type": "Version", "id": 7, "code": f"{shot_code}_v001"},
    }
    if version_user_name:
        row["sg_latest_version.Version.user"] = {
            "type": "HumanUser",
            "id": 99,
            "name": version_user_name,
        }
    if version_created_name:
        row["sg_latest_version.Version.created_by"] = {
            "type": "HumanUser",
            "id": 88,
            "name": version_created_name,
        }
    if version_created_at:
        row["sg_latest_version.Version.created_at"] = version_created_at
    return row


def test_list_review_tasks_in_filter_sv_tm() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "PROJ"})
    sg._add_entity("Task", _task_row(10, "S001", 100, "sv"))
    sg._add_entity("Task", _task_row(11, "S002", 101, "tm"))
    sg._add_entity("Task", _task_row(12, "S003", 102, "wip"))

    rows = list_review_tasks_for_project(sg, 1, statuses=["sv", "tm"])
    codes = sorted((r.get("shot_code") or "") for r in rows)
    assert codes == ["S001", "S002"]
    assert all(r.get("task_id") in (10, 11) for r in rows)
    by_code = {r.get("shot_code"): r for r in rows}
    assert by_code["S001"].get("latest_version_code") == "S001_v001"
    assert by_code["S001"].get("latest_version_id") == 7
    assert by_code["S001"].get("latest_version_sg_path") == ""
    assert by_code["S001"].get("version_uploader_name") == ""
    assert rows[0].get("task_id") == 10


def test_list_review_tasks_sv_only() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity("Task", _task_row(10, "S001", 100, "sv"))
    sg._add_entity("Task", _task_row(11, "S002", 101, "tm"))

    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert len(rows) == 1
    assert rows[0].get("shot_code") == "S001"


def test_list_review_tasks_per_status_merge_fallback() -> None:
    class PickySG(MockShotgun):
        def find(self, entity_type, filters, fields, **kwargs):
            for f in filters or []:
                if isinstance(f, list) and len(f) >= 3 and f[1] == "in":
                    raise RuntimeError("in not supported")
            return super().find(entity_type, filters, fields, **kwargs)

    sg = PickySG()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity("Task", _task_row(10, "A", 1, "sv"))
    sg._add_entity("Task", _task_row(11, "B", 2, "tm"))

    rows = list_review_tasks_for_project(sg, 1, statuses=["sv", "tm"])
    assert len(rows) == 2


def test_list_review_tasks_project_flat_fields_when_nested_minimal() -> None:
    """SG가 project를 type/id만 주고 code·name은 project.Project.* 평면 키로만 줄 때."""
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "FLAT"})
    row: Dict[str, Any] = {
        "id": 10,
        "content": "comp",
        "sg_status_list": "sv",
        "due_date": None,
        "project": {"type": "Project", "id": 1},
        "entity": {
            "type": "Shot",
            "id": 100,
            "code": "S001",
            "description": "",
            "image": None,
        },
        "entity.Shot.code": "S001",
        "entity.Shot.description": "",
        "entity.Shot.image": None,
        "project.Project.code": "FLAT",
        "project.Project.name": "Flat Name",
        "sg_latest_version": {"type": "Version", "id": 7, "code": "S001_v001"},
    }
    sg._add_entity("Task", row)
    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert len(rows) == 1
    assert rows[0].get("project_code") == "FLAT"
    assert rows[0].get("project_name") == "Flat Name"
    assert rows[0].get("project_folder") == "FLAT"


def test_list_review_tasks_version_uploader_from_user() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "PROJ"})
    sg._add_entity(
        "Task",
        _task_row(10, "S001", 100, "sv", version_user_name="권동설"),
    )
    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert len(rows) == 1
    assert rows[0].get("version_uploader_name") == "권동설"


def test_list_review_tasks_version_uploader_created_by_fallback() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "PROJ"})
    sg._add_entity(
        "Task",
        _task_row(10, "S001", 100, "sv", version_created_name="백업이름"),
    )
    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert rows[0].get("version_uploader_name") == "백업이름"


def test_list_review_tasks_version_uploader_prefers_user_over_created() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "PROJ"})
    sg._add_entity(
        "Task",
        _task_row(
            10,
            "S001",
            100,
            "sv",
            version_user_name="우선",
            version_created_name="무시",
        ),
    )
    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert rows[0].get("version_uploader_name") == "우선"


def test_list_review_tasks_sorted_oldest_version_first() -> None:
    """피드백 큐: 버전 created_at 오름차순(먼저 올린 샷이 위)."""
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "PROJ"})
    sg._add_entity(
        "Task",
        _task_row(
            11,
            "S002",
            102,
            "sv",
            version_created_at="2021-06-01T12:00:00+00:00",
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            10,
            "S001",
            101,
            "sv",
            version_created_at="2020-01-01T12:00:00+00:00",
        ),
    )
    rows = list_review_tasks_for_project(sg, 1, statuses=["sv"])
    assert [r.get("shot_code") for r in rows] == ["S001", "S002"]
