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


# ── 버전 상태(샷그리드 버전 목록의 상태 칸)도 함께 바꾼다 ─────────────────────────


def _sg_with_versions() -> MockShotgun:
    sg = _sg()
    shot = {"type": "Shot", "id": 10}
    for vid, code, status in (
        (77, "ep08_s014_0040_comp_v003", "sv"),
        (78, "ep08_s014_0040_comp_v003_lut", "sv"),
        (70, "ep08_s014_0040_comp_v002", "retake"),
        (90, "ep08_s014_0050_comp_v003_lut", "sv"),
    ):
        entity = shot if vid != 90 else {"type": "Shot", "id": 11}
        sg._add_entity(
            "Version", {"id": vid, "code": code, "entity": entity, "sg_status_list": status}
        )
    return sg


def _version_status(sg: MockShotgun, vid: int) -> str:
    return next(v for v in sg._entities["Version"] if v["id"] == vid)["sg_status_list"]


def test_status_changes_task_and_version_and_its_lut_twin() -> None:
    sg = _sg_with_versions()
    res = _submit(sg, status_code="cfrm")
    assert res.all_ok and res.status_ok and res.version_ok
    assert res.version_count == 2
    assert _task_status(sg) == "cfrm"
    assert _version_status(sg, 77) == "cfrm"
    assert _version_status(sg, 78) == "cfrm"  # 같은 판의 _lut 쌍둥이
    assert _version_status(sg, 70) == "retake"  # 옛 버전은 그대로
    assert _version_status(sg, 90) == "sv"  # 다른 샷의 같은 이름은 건드리지 않는다


def test_twin_works_from_the_lut_side_too() -> None:
    sg = _sg_with_versions()
    assert sorted(cs.version_ids_with_twins(sg, 78)) == [77, 78]
    assert cs.version_ids_with_twins(sg, None) == []
    assert cs.version_ids_with_twins(sg, 12345) == [12345]  # 못 읽어도 그 버전 하나는 바꾼다


def test_version_failure_is_reported_apart_from_task(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg_with_versions()
    real_update = sg.update

    def _update(entity_type: str, entity_id: int, data: Any) -> Any:
        if entity_type == "Version":
            raise RuntimeError("버전 권한 없음")
        return real_update(entity_type, entity_id, data)

    monkeypatch.setattr(sg, "update", _update)
    res = _submit(sg, status_code="cfrm")
    assert res.note_ok and res.status_ok
    assert res.version_needed and not res.version_ok and "버전 권한 없음" in res.version_error
    assert not res.all_ok
    assert _task_status(sg) == "cfrm" and _version_status(sg, 77) == "sv"


def test_note_failure_does_not_change_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg_with_versions()

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("네트워크 끊김")

    monkeypatch.setattr(cs, "create_note_with_result", _boom)
    res = _submit(sg, status_code="cfrm")
    assert not res.version_ok and res.version_needed
    assert _version_status(sg, 77) == "sv" and _version_status(sg, 78) == "sv"


def test_no_version_means_only_task_changes() -> None:
    sg = _sg_with_versions()
    res = _submit(sg, status_code="cfrm", version_id=None)
    assert res.all_ok and res.version_needed is False
    assert _task_status(sg) == "cfrm" and _version_status(sg, 77) == "sv"


# ── 2026-11-17 추가: Annotation 노트를 edit·org 버전에 붙이기(guide 봇이 집어 가게) ─────────


def _sg_with_source_versions(with_plate: bool = True) -> MockShotgun:
    sg = MockShotgun()
    shot = {"type": "Shot", "id": 10}
    rows = [
        (30, "ep06_s017_0170_edit_v003", "edit", "2026-11-10"),
        (20, "ep06_s017_0170_edit_v002", "edit", "2026-10-01"),
        (77, "ep06_s017_0170_comp_v001", "comp", "2026-11-12"),
        (99, "ep06_s017_0180_edit_v001", "edit", "2026-11-13"),
    ]
    if with_plate:
        rows.append((40, "ep06_s017_0170_org_v004", "org", "2026-11-11"))
    for vid, code, task, when in rows:
        sg._add_entity(
            "Version",
            {
                "id": vid,
                "code": code,
                "entity": shot if vid != 99 else {"type": "Shot", "id": 11},
                "sg_task": {"type": "Task", "id": vid + 1000, "name": task},
                "sg_task.Task.content": task,  # 가짜 샷그리드는 점으로 이은 칸을 그대로 본다
                "created_at": when,
            },
        )
    return sg


def test_source_versions_lists_edit_and_org_of_the_shot() -> None:
    rows = cs.source_versions(_sg_with_source_versions(), 10)
    assert {r["id"] for r in rows} == {30, 20, 40}  # comp 과 다른 샷의 것은 뺀다
    assert all(set(r) == {"id", "code", "task", "task_id"} for r in rows)
    assert {r["id"]: r["task_id"] for r in rows} == {30: 1030, 20: 1020, 40: 1040}
    assert {r["task"] for r in rows} == {"edit", "org"}


def test_guide_note_target_follows_the_drawn_video() -> None:
    sg = _sg_with_source_versions()
    codes = {"edit": "ep06_s017_0170_edit_v003", "org": "ep06_s017_0170_org_v004"}
    src, ver = cs.guide_note_target(sg, 10, codes=codes, drawn=["edit"], shown="org")
    assert src == "edit" and ver is not None and ver["id"] == 30
    src, ver = cs.guide_note_target(sg, 10, codes=codes, drawn=["org"], shown="org")
    assert src == "org" and ver is not None and ver["id"] == 40
    # 연 파일이 옛 버전이면 그 버전에 붙는다
    old = dict(codes, edit="ep06_s017_0170_edit_v002")
    _src, ver = cs.guide_note_target(sg, 10, codes=old, drawn=["edit"], shown="edit")
    assert ver is not None and ver["id"] == 20

    # 샷그리드에 org 버전이 없는 샷 — 원본에 그려도 edit 버전에 붙는다
    no_plate = _sg_with_source_versions(with_plate=False)
    src, ver = cs.guide_note_target(no_plate, 10, codes=codes, drawn=["org"], shown="org")
    assert src == "edit" and ver is not None and ver["id"] == 30
    # edit·org 버전이 하나도 없는 샷
    assert cs.guide_note_target(MockShotgun(), 10, codes=codes, drawn=["org"], shown="org") == (
        "",
        None,
    )


def test_annotation_note_with_pictures_only_has_no_filler_text(tmp_path: Path) -> None:
    sg = _sg()
    png = tmp_path / "annot_version_30.0.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = _submit(
        sg, content="", attachment_paths=[str(png)], status_code="", version_id=30,
        empty_note_text="",
    )  # fmt: skip
    assert res.note_ok and res.all_ok
    note = _notes(sg)[0]
    assert note["content"] == ""  # 노트에는 쓴 글만 — 대신 넣는 글이 없다
    assert {"type": "Version", "id": 30} in note["note_links"]


def test_note_carries_the_task_of_its_version_like_a_native_note() -> None:
    sg = _sg()
    res = _submit(sg, note_task_id=500)
    assert res.note_ok
    assert _notes(sg)[0]["tasks"] == [{"type": "Task", "id": 500}]
    # 걸 태스크가 없으면 Tasks 칸을 건드리지 않는다
    sg = _sg()
    _submit(sg)
    assert "tasks" not in _notes(sg)[0]
