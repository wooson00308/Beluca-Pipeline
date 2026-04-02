"""Tests for list_tasks_for_project_assignee."""

from __future__ import annotations

from bpe.shotgrid.projects import resolve_project_id_by_code
from bpe.shotgrid.tasks import list_tasks_for_project_assignee
from tests.shotgrid.mock_sg import MockShotgun


def test_list_tasks_for_project_assignee_finds_user() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 50, "code": "PROD", "name": "PROD"})
    sg._add_entity(
        "Task",
        {
            "id": 900,
            "content": "Meeting",
            "project": {"type": "Project", "id": 50},
            "task_assignees": [{"type": "HumanUser", "id": 3}],
            "entity": {"type": "CustomEntity01", "id": 1},
        },
    )
    rows = list_tasks_for_project_assignee(sg, 50, 3)
    assert len(rows) == 1
    assert rows[0]["id"] == 900


def test_resolve_project_id_by_code() -> None:
    sg = MockShotgun()
    assert resolve_project_id_by_code(sg, "MISSING") is None
    sg._add_entity("Project", {"id": 77, "code": "PROD", "name": "Prod"})
    assert resolve_project_id_by_code(sg, "PROD") == 77
