"""Tests for All Tasks: roster assignees, Shot dedupe, paging (My Tasks)."""

from __future__ import annotations

from typing import Any, Dict, List

from bpe.shotgrid.tasks import (
    list_comp_tasks_for_project_shot_paged,
    summarize_shot_tasks_for_project,
)
from tests.shotgrid.mock_sg import MockShotgun


def _shot_entity(sid: int, code: str) -> Dict[str, Any]:
    return {
        "type": "Shot",
        "id": sid,
        "code": code,
        "name": code,
        "description": "",
        "image": None,
    }


def _task_row(
    tid: int,
    *,
    assignees: List[Dict[str, Any]],
    content: str = "comp",
    status: str = "wip",
    project_id: int = 1,
    shot_code: str = "S01",
    shot_id: int = 1,
) -> Dict[str, Any]:
    ent = _shot_entity(shot_id, shot_code)
    return {
        "type": "Task",
        "id": tid,
        "content": content,
        "sg_status_list": status,
        "due_date": None,
        "task_assignees": assignees,
        "project": {"type": "Project", "id": project_id, "code": "P", "name": "P"},
        "entity": ent,
        "entity.Shot.code": shot_code,
        "entity.Shot.description": "",
        "entity.Shot.image": None,
        "project.Project.code": "P",
        "project.Project.name": "P",
        "sg_latest_version": None,
    }


def test_shot_paged_includes_all_assignees_on_project() -> None:
    """Roster includes U1+U2 from project Tasks; both Shots appear (dedupe one row per Shot)."""
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "P"})
    sg._add_entity(
        "Task",
        _task_row(
            10,
            assignees=[{"type": "HumanUser", "id": 1, "name": "U1"}],
            shot_code="A",
            shot_id=100,
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            20,
            assignees=[{"type": "HumanUser", "id": 2, "name": "U2"}],
            shot_code="B",
            shot_id=101,
        ),
    )
    rows = list_comp_tasks_for_project_shot_paged(sg, 1, page_size=50)
    assert len(rows) == 2
    codes = sorted((r.get("shot_code") or "") for r in rows)
    assert codes == ["A", "B"]


def test_summarize_shot_tasks_for_project_counts_and_total() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity(
        "Task",
        _task_row(
            10,
            assignees=[{"type": "HumanUser", "id": 1}],
            status="wip",
            shot_code="A",
            shot_id=1,
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            11,
            assignees=[{"type": "HumanUser", "id": 1}],
            status="sv",
            shot_code="B",
            shot_id=2,
        ),
    )
    counts, total = summarize_shot_tasks_for_project(sg, 1, task_content="")
    assert total == 2
    assert counts.get("wip") == 1
    assert counts.get("sv") == 1


def test_shot_paged_order_and_offset() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    for tid, sid in [(100, 1), (200, 2), (300, 3), (400, 4), (500, 5)]:
        sg._add_entity(
            "Task",
            _task_row(
                tid,
                assignees=[{"type": "HumanUser", "id": 1}],
                shot_code=f"S{sid}",
                shot_id=sid,
            ),
        )
    p1 = list_comp_tasks_for_project_shot_paged(sg, 1, page_1based=1, page_size=2, task_content="")
    p2 = list_comp_tasks_for_project_shot_paged(sg, 1, page_1based=2, page_size=2, task_content="")
    assert [r.get("task_id") for r in p1] == [500, 400]
    assert [r.get("task_id") for r in p2] == [300, 200]


def test_shot_paged_includes_any_human_assignee_not_roster_limited() -> None:
    """Every Shot Task with a HumanUser assignee is included (U2 even if not on a roster popup)."""
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "P"})
    sg._add_entity(
        "Task",
        _task_row(
            10,
            assignees=[{"type": "HumanUser", "id": 1, "name": "U1"}],
            shot_code="A",
            shot_id=100,
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            20,
            assignees=[{"type": "HumanUser", "id": 99, "name": "Rare"}],
            shot_code="B",
            shot_id=101,
        ),
    )
    rows = list_comp_tasks_for_project_shot_paged(sg, 1, page_size=50)
    assert len(rows) == 2
    assert sorted(r.get("shot_code") for r in rows) == ["A", "B"]


def test_unassigned_shot_task_ignored_for_overview() -> None:
    """Tasks with no HumanUser assignees do not count toward assigned-shot overview."""
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity(
        "Task",
        {
            "type": "Task",
            "id": 1,
            "content": "comp",
            "sg_status_list": "wip",
            "due_date": None,
            "task_assignees": [],
            "project": {"type": "Project", "id": 1, "code": "P", "name": "P"},
            "entity": _shot_entity(200, "NoAssign"),
            "entity.Shot.code": "NoAssign",
            "entity.Shot.description": "",
            "entity.Shot.image": None,
            "project.Project.code": "P",
            "project.Project.name": "P",
            "sg_latest_version": None,
        },
    )
    sg._add_entity(
        "Task",
        _task_row(
            2,
            assignees=[{"type": "HumanUser", "id": 1}],
            shot_code="HasAssign",
            shot_id=201,
        ),
    )
    rows = list_comp_tasks_for_project_shot_paged(sg, 1, page_size=50)
    assert len(rows) == 1
    assert rows[0].get("shot_code") == "HasAssign"


def test_dedupe_same_shot_prefers_comp() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity(
        "Task",
        _task_row(
            50,
            assignees=[{"type": "HumanUser", "id": 1}],
            content="roto",
            shot_code="S",
            shot_id=1,
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            60,
            assignees=[{"type": "HumanUser", "id": 1}],
            content="comp",
            shot_code="S",
            shot_id=1,
        ),
    )
    rows = list_comp_tasks_for_project_shot_paged(sg, 1, page_size=50)
    assert len(rows) == 1
    assert rows[0].get("task_id") == 60


def test_dedupe_same_shot_tiebreak_highest_task_id() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1})
    sg._add_entity(
        "Task",
        _task_row(
            40,
            assignees=[{"type": "HumanUser", "id": 1}],
            content="roto",
            shot_code="S",
            shot_id=1,
        ),
    )
    sg._add_entity(
        "Task",
        _task_row(
            55,
            assignees=[{"type": "HumanUser", "id": 1}],
            content="plate",
            shot_code="S",
            shot_id=1,
        ),
    )
    rows = list_comp_tasks_for_project_shot_paged(sg, 1, page_size=50)
    assert len(rows) == 1
    assert rows[0].get("task_id") == 55
