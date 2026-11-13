"""Tests for bpe.shotgrid.confirm_context — Note 칸의 지난 내용 (MockShotgun)."""

from __future__ import annotations

from typing import Any, Dict

import pytest

import bpe.shotgrid.confirm_context as cc
from bpe.shotgrid.confirm_context import list_shot_history, version_comments
from tests.shotgrid.mock_sg import MockShotgun

_SHOT = {"type": "Shot", "id": 101, "name": "S_0010"}


def _version(vid: int, code: str, when: str, text: str, *, task: int = 1) -> Dict[str, Any]:
    return {
        "id": vid,
        "code": code,
        "description": text,
        "created_at": when,
        "user": {"type": "HumanUser", "id": 9, "name": "작업자"},
        "entity": {"type": "Shot", "id": 101},
        "sg_task": {"type": "Task", "id": task, "name": "comp"} if task else None,
    }


def _note(nid: int, when: str, text: str, version: str) -> Dict[str, Any]:
    return {
        "id": nid,
        "subject": "",
        "content": text,
        "created_at": when,
        "created_by": {"type": "HumanUser", "id": 3, "name": "SV"},
        "project": {"type": "Project", "id": 1, "name": "PROJ"},
        "note_links": [_SHOT, {"type": "Version", "id": 1, "name": version}],
    }


def _sg() -> MockShotgun:
    sg = MockShotgun()
    sg._add_entity("Version", _version(71, "S_0010_comp_v001", "2026-11-01 10:00", "첫 버전입니다"))
    sg._add_entity("Version", _version(72, "S_0010_comp_v002", "2026-11-05 10:00", ""))
    sg._add_entity(
        "Version", _version(73, "S_0010_comp_v003", "2026-11-09 10:00", "엣지 정리했습니다")
    )
    sg._add_entity(
        "Version", _version(74, "S_0010_making_v001", "2026-11-10 10:00", "다른 태스크", task=2)
    )
    sg._add_entity("Note", _note(1, "2026-11-03 09:00", "[1040] 엣지 밝은 테", "S_0010_comp_v001"))
    return sg


def test_version_comments_skip_empty_ones_and_other_tasks() -> None:
    rows = version_comments(_sg(), 101, task_id=1)
    assert [r["version_code"] for r in rows] == ["S_0010_comp_v003", "S_0010_comp_v001"]
    assert rows[0]["kind"] == "version" and rows[0]["author"] == "작업자"
    assert rows[0]["content"] == "엣지 정리했습니다"
    # 태스크를 안 주면 그 샷의 버전 글을 전부
    assert len(version_comments(_sg(), 101)) == 3


def test_history_merges_notes_and_version_comments_newest_first() -> None:
    rows = list_shot_history(_sg(), 101, task_id=1)
    assert [(r["kind"], r["version_code"]) for r in rows] == [
        ("version", "S_0010_comp_v003"),
        ("note", "S_0010_comp_v001"),
        ("version", "S_0010_comp_v001"),
    ]


def test_history_survives_a_failed_version_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(cc, "version_comments", _boom)
    rows = list_shot_history(_sg(), 101, task_id=1)
    assert [r["kind"] for r in rows] == ["note"]
