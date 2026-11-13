"""Tests for bpe.shotgrid.confirm_submit — 노트와 상태를 따로 성공/실패로 알려 주는 보내기.

전부 MockShotgun 으로만 돈다(실제 ShotGrid 연결은 conftest 가 막는다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import bpe.shotgrid.confirm_submit as cs
from bpe.shotgrid.confirm_submit import addressings_for_confirm, note_subject, submit_confirm
from tests.shotgrid.mock_sg import MockShotgun


def _sg() -> MockShotgun:
    sg = MockShotgun()
    sg._add_entity("Task", {"id": 500, "content": "comp", "sg_status_list": "sv"})
    return sg


def _submit(sg: Any, **over: Any) -> Any:
    args = dict(
        project_id=1,
        shot_id=10,
        version_id=77,
        task_id=500,
        status_code="retake",
        status_field="sg_status_list",
        subject="제목",
        content="[1015] 엣지 정리",
    )
    args.update(over)
    return submit_confirm(sg, **args)


def _notes(sg: MockShotgun) -> list:
    return sg._entities.get("Note", [])


def _task_status(sg: MockShotgun) -> str:
    return sg._entities["Task"][0]["sg_status_list"]


def test_note_and_status_both_ok() -> None:
    sg = _sg()
    res = _submit(sg)
    assert res.all_ok and res.note_ok and res.status_ok
    assert res.note_id is not None
    assert len(_notes(sg)) == 1
    assert _notes(sg)[0]["content"] == "[1015] 엣지 정리"
    assert _task_status(sg) == "retake"


def test_status_only_when_nothing_to_say() -> None:
    sg = _sg()
    res = _submit(sg, content="  ", status_code="cfrm")
    assert res.note_needed is False and res.status_ok and res.all_ok
    assert _notes(sg) == []
    assert _task_status(sg) == "cfrm"


def test_note_failure_does_not_change_status(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("네트워크 끊김")

    monkeypatch.setattr(cs, "create_note_with_result", _boom)
    res = _submit(sg)
    assert not res.note_ok and "네트워크 끊김" in res.note_error
    assert res.status_needed and not res.status_ok
    assert not res.all_ok
    assert _task_status(sg) == "sv"


def test_status_failure_keeps_note_and_retry_does_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sg = _sg()
    calls = {"n": 0}

    def _fail_once(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        raise RuntimeError("권한 없음")

    monkeypatch.setattr(cs, "update_task_status", _fail_once)
    first = _submit(sg)
    assert first.note_ok and not first.status_ok and "권한 없음" in first.status_error
    assert not first.all_ok
    assert len(_notes(sg)) == 1

    monkeypatch.undo()
    retry = _submit(sg, existing_note_id=first.note_id)
    assert retry.note_ok and retry.status_ok and retry.all_ok
    assert retry.note_id == first.note_id
    assert len(_notes(sg)) == 1  # 노트가 두 번 가지 않는다
    assert _task_status(sg) == "retake"


def test_images_only_note_gets_placeholder_text(tmp_path: Path) -> None:
    sg = _sg()
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = _submit(sg, content="", attachment_paths=[str(png)], status_code="")
    assert res.note_ok and res.status_needed is False and res.all_ok
    assert _notes(sg)[0]["content"] == cs.EMPTY_NOTE_TEXT
    assert _task_status(sg) == "sv"


def test_addressings_include_people_and_vendor_groups() -> None:
    got = addressings_for_confirm(
        [
            {"type": "HumanUser", "id": 3, "name": "작업자"},
            {"type": "Group", "id": 9, "name": "업체"},
            {"type": "ApiUser", "id": 1},
            "쓰레기",
        ]
    )
    assert got == [{"type": "HumanUser", "id": 3}, {"type": "Group", "id": 9}]
    assert addressings_for_confirm(None) == []


def test_note_subject() -> None:
    assert note_subject({"name": "수퍼"}, "S_comp_v002", "S") == "수퍼's Note on S_comp_v002 and S"
    assert note_subject(None, "", "S") == "User's Note on S"
