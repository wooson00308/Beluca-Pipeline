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
    sg._add_entity("Task", _task(2, "S_0020", "tm", 72))
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
