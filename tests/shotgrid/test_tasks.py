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
) -> Dict[str, Any]:
    return {
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
    assert rows[0].get("latest_version_code") == "S001_v001"
    assert rows[0].get("latest_version_id") == 7
    assert rows[0].get("latest_version_sg_path") == ""


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
