"""Tests for bpe.shotgrid.confirm_list — 컨펌 목록에 "올린 쪽" 붙이기 (MockShotgun)."""

from __future__ import annotations

from typing import Any, Dict

import pytest

import bpe.shotgrid.confirm_list as cl
from bpe.core.confirm_list import GROUP_INTERNAL, GROUP_VENDOR, filter_rows
from bpe.shotgrid.confirm_list import list_confirm_tasks, version_uploaders
from tests.shotgrid.mock_sg import MockShotgun


def _task(tid: int, shot: str, status: str, version_id: int) -> Dict[str, Any]:
    return {
        "id": tid,
        "content": "comp",
        "sg_status_list": status,
        "due_date": None,
        "project": {"type": "Project", "id": 1, "code": "PROJ", "name": "PROJ"},
        "entity": {"type": "Shot", "id": tid + 100, "code": shot},
        "entity.Shot.code": shot,
        "project.Project.code": "PROJ",
        "project.Project.name": "PROJ",
        "sg_latest_version": {"type": "Version", "id": version_id, "code": f"{shot}_comp_v002"},
    }


def _sg() -> MockShotgun:
    sg = MockShotgun()
    sg._add_entity("Task", _task(1, "S_0010", "sv", 71))
    sg._add_entity("Task", _task(2, "S_0020", "sv", 72))
    sg._add_entity("Version", {"id": 71, "user": {"type": "Group", "id": 5, "name": "업체 A"}})
    sg._add_entity("Version", {"id": 72, "user": {"type": "HumanUser", "id": 9, "name": "작업자"}})
    return sg


def test_version_uploaders_reads_type_and_name() -> None:
    who = version_uploaders(_sg(), [71, 72, 72])
    assert who == {
        71: {"type": "Group", "name": "업체 A"},
        72: {"type": "HumanUser", "name": "작업자"},
    }
    assert version_uploaders(_sg(), []) == {}


def test_list_confirm_tasks_marks_vendor_and_internal() -> None:
    rows = list_confirm_tasks(_sg(), 1)
    by_shot = {r["shot_code"]: r for r in rows}
    assert by_shot["S_0010"]["uploader_type"] == "Group"
    assert by_shot["S_0010"]["uploader_name"] == "업체 A"
    assert by_shot["S_0020"]["uploader_type"] == "HumanUser"
    assert [r["shot_code"] for r in filter_rows(rows, GROUP_VENDOR)] == ["S_0010"]
    assert [r["shot_code"] for r in filter_rows(rows, GROUP_INTERNAL)] == ["S_0020"]


def test_uploader_lookup_failure_still_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(cl, "version_uploaders", _boom)
    rows = list_confirm_tasks(_sg(), 1)
    assert len(rows) == 2
    assert all(r["uploader_type"] == "" for r in rows)


# ── 태스크의 「최신 버전」 칸이 비어 있을 때(실제 사이트가 이렇다) ────────────────


def _bare_task(tid: int, shot: str, status: str = "sv") -> Dict[str, Any]:
    t = _task(tid, shot, status, 0)
    t["sg_latest_version"] = None
    return t


def _version(
    vid: int, code: str, when: str, user: Dict[str, Any], *, task: int = 0, shot: int = 0
) -> Dict[str, Any]:
    return {
        "id": vid,
        "code": code,
        "created_at": when,
        "user": user,
        "sg_path_to_movie": f"W:/x/{code}.mov",
        "sg_task": {"type": "Task", "id": task} if task else None,
        "entity": {"type": "Shot", "id": shot} if shot else None,
        "image": f"https://thumb.invalid/{vid}.jpg",
    }


_VENDOR = {"type": "Group", "id": 5, "name": "업체 A"}
_ARTIST = {"type": "HumanUser", "id": 9, "name": "작업자"}


def test_latest_version_comes_from_version_records_linked_to_the_task() -> None:
    sg = MockShotgun()
    sg._add_entity("Task", _bare_task(1, "S_0010"))
    sg._add_entity("Task", _bare_task(2, "S_0020"))
    sg._add_entity("Version", _version(71, "S_0010_comp_v001", "2026-11-01", _ARTIST, task=1))
    sg._add_entity("Version", _version(72, "S_0010_comp_v002", "2026-11-05", _VENDOR, task=1))
    sg._add_entity("Version", _version(73, "S_0020_comp_v003", "2026-11-03", _ARTIST, task=2))
    rows = {r["shot_code"]: r for r in list_confirm_tasks(sg, 1)}
    a, b = rows["S_0010"], rows["S_0020"]
    assert a["latest_version_id"] == 72 and a["latest_version_code"] == "S_0010_comp_v002"
    assert a["uploader_type"] == "Group" and a["uploader_name"] == "업체 A"
    assert a["latest_version_sg_path"].endswith("S_0010_comp_v002.mov")
    assert str(a["latest_version_created_at"]).startswith("2026-11-05")
    assert a["latest_version_image"].endswith("72.jpg")
    assert b["latest_version_id"] == 73 and b["uploader_type"] == "HumanUser"
    assert [r["shot_code"] for r in filter_rows(list(rows.values()), GROUP_VENDOR)] == ["S_0010"]
    assert [r["shot_code"] for r in filter_rows(list(rows.values()), GROUP_INTERNAL)] == ["S_0020"]


def test_falls_back_to_the_newest_version_on_the_shot() -> None:
    sg = MockShotgun()
    sg._add_entity("Task", _bare_task(1, "S_0010"))  # 샷 id = 101
    sg._add_entity("Version", _version(81, "S_0010_comp_v001", "2026-11-01", _ARTIST, shot=101))
    sg._add_entity("Version", _version(82, "S_0010_comp_v002", "2026-11-06", _VENDOR, shot=101))
    row = list_confirm_tasks(sg, 1)[0]
    assert row["latest_version_id"] == 82 and row["uploader_type"] == "Group"


def test_task_without_any_version_stays_internal_and_empty() -> None:
    sg = MockShotgun()
    sg._add_entity("Task", _bare_task(1, "S_0010"))
    row = list_confirm_tasks(sg, 1)[0]
    assert row["latest_version_id"] is None and row["uploader_type"] == ""
    assert filter_rows([row], GROUP_INTERNAL) == [row]


def test_version_lookup_failure_still_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(cl, "latest_versions", _boom)
    sg = MockShotgun()
    sg._add_entity("Task", _bare_task(1, "S_0010"))
    assert len(list_confirm_tasks(sg, 1)) == 1


def test_annotation_list_takes_any_task_in_wtg_or_assign() -> None:
    from bpe.shotgrid.confirm_list import list_annotation_shots

    sg = MockShotgun()
    for tid, shot_id, shot, content, status in (
        (1, 10, "S_0010", "comp", "wtg"),
        (2, 10, "S_0010", "roto", "assign"),
        (3, 20, "S_0020", "matte", "assign"),
        (4, 30, "S_0030", "comp", "sv"),  # 컨펌 대기는 Annotation 목록에 안 나온다
    ):
        t = _bare_task(tid, shot, status)
        t["content"] = content
        t["entity"] = {"type": "Shot", "id": shot_id, "name": shot, "code": shot}
        sg._add_entity("Task", t)
    rows = list_annotation_shots(sg, 1)
    assert [r["shot_code"] for r in rows] == ["S_0010", "S_0020"]
    assert [t["task_content"] for t in rows[0]["tasks"]] == ["comp", "roto"]


def _picked_sg() -> MockShotgun:
    import bpe.shotgrid.tasks as tasks_mod

    tasks_mod._VFX_FIELD_CACHE = None
    sg = MockShotgun()
    sg._schema = {
        "Shot": {"code": {}, "description": {}, "sg_vfx_work_order": {}},
        "Task": {"sg_status_list": {"data_type": "status_list"}},
    }
    proj = {"type": "Project", "id": 1, "code": "MMK", "name": "문무"}
    for sid, code, order, desc in (
        (20, "ep06_s010_0020", "AI", "병사 연장"),
        (10, "ep06_s010_0010", "2D 합성", ""),
        (30, "ep06_s010_0030", None, None),
    ):
        sg._add_entity(
            "Shot",
            {"id": sid, "code": code, "sg_vfx_work_order": order, "description": desc,
             "image": f"http://img/{sid}", "sg_status_list": "ip", "project": proj,
             "project.Project.code": "MMK", "project.Project.name": "문무"},
        )  # fmt: skip
    who = {"type": "HumanUser", "id": 3, "name": "김작업"}
    for tid, sid, content, status, people in (
        (1, 10, "edit", "fin", []),
        (2, 10, "comp", "ip", [who]),
        (3, 10, "roto", "wtg", [who]),
        (4, 20, "org", "fin", []),
    ):
        sg._add_entity(
            "Task",
            {"id": tid, "content": content, "sg_status_list": status,
             "task_assignees": people, "entity": {"type": "Shot", "id": sid}},
        )  # fmt: skip
    return sg


def test_picked_shots_come_whatever_their_task_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import bpe.shotgrid.tasks as tasks_mod
    from bpe.shotgrid.confirm_list import list_shots_for_annotation

    monkeypatch.setattr(tasks_mod, "_VFX_FIELD_CACHE", None)
    sg = _picked_sg()
    assert list_shots_for_annotation(sg, 1, []) == []
    rows = list_shots_for_annotation(sg, 1, [30, 10, 20, 999, 10])
    assert [r["shot_code"] for r in rows] == [
        "ep06_s010_0010",
        "ep06_s010_0020",
        "ep06_s010_0030",
    ]  # fmt: skip  — 샷 이름 순, 없는 샷(999)은 빠진다
    first, second, third = rows
    # 작업 태스크만 보이고(edit 같은 재료 태스크는 뺀다), 상태·담당은 모두 모은다
    assert [t["task_content"] for t in first["tasks"]] == ["comp", "roto"]
    assert first["task_statuses"] == ["ip", "wtg"]
    assert [a["name"] for a in first["task_assignees"]] == ["김작업"]
    assert (first["task_id"], first["task_content"], first["task_status"]) == (2, "comp", "ip")
    assert first["vfx_work_order"] == "2D 합성" and first["shot_description"] == ""
    assert first["shot_image"] == "http://img/10"
    assert (first["project_id"], first["project_folder"]) == (1, "MMK")
    assert first["status_field"] == "sg_status_list"
    # 재료 태스크뿐인 샷 — 줄에는 태스크가 없지만 번호는 그 태스크의 것
    assert second["tasks"] == [] and second["task_id"] == 4
    assert second["vfx_work_order"] == "AI" and second["shot_description"] == "병사 연장"
    # 태스크가 하나도 없는 샷도 나온다
    assert third["tasks"] == [] and third["task_id"] is None
    assert third["vfx_work_order"] == "" and third["shot_description"] == ""


def test_picked_shots_are_read_in_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    import bpe.shotgrid.tasks as tasks_mod
    from bpe.shotgrid.confirm_list import list_shots_for_annotation

    monkeypatch.setattr(tasks_mod, "_VFX_FIELD_CACHE", None)
    monkeypatch.setattr(cl, "_CHUNK", 2)
    sg = _picked_sg()
    asked = []
    real = sg.find

    def _find(kind: str, filters: Any, fields: Any, **kw: Any) -> Any:
        asked.append((kind, len(filters[0][2])))
        return real(kind, filters, fields, **kw)

    monkeypatch.setattr(sg, "find", _find)
    rows = list_shots_for_annotation(sg, 1, [10, 20, 30])
    assert len(rows) == 3
    assert asked == [("Shot", 2), ("Task", 2), ("Shot", 1), ("Task", 1)]
