"""Tests for bpe.shotgrid.shot_text — 샷의 글 칸에 적용하기(MockShotgun 으로만 돈다)."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

import bpe.shotgrid.tasks as tasks_mod
from bpe.core.confirm_shot_text import KIND_DESCRIPTION, KIND_WORK_ORDER
from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.shot_text import apply_shot_text, read_shot_text, shot_text_field
from tests.shotgrid.mock_sg import MockShotgun

NL = chr(10)


@pytest.fixture(autouse=True)
def _fresh_field_cache() -> Iterator[None]:
    """워크오더 칸 이름은 한 번 찾으면 기억한다 — 시험마다 비운다."""
    prev = tasks_mod._VFX_FIELD_CACHE
    tasks_mod._VFX_FIELD_CACHE = None
    try:
        yield
    finally:
        tasks_mod._VFX_FIELD_CACHE = prev


def _sg(work_order: Any = "2D 합성", description: Any = "- 와이어 리무브") -> MockShotgun:
    sg = MockShotgun()
    sg._schema = {"Shot": {"code": {}, "description": {}, "sg_vfx_work_order": {}}}
    sg._add_entity(
        "Shot",
        {"id": 10, "code": "ep06_s017_0170", "sg_vfx_work_order": work_order,
         "description": description},
    )  # fmt: skip
    return sg


def _shot(sg: MockShotgun) -> dict:
    return sg._entities["Shot"][0]


def test_fields_are_the_shot_columns_not_a_note() -> None:
    sg = _sg()
    assert shot_text_field(sg, KIND_WORK_ORDER) == "sg_vfx_work_order"
    assert shot_text_field(sg, KIND_DESCRIPTION) == "description"
    assert read_shot_text(sg, 10, KIND_WORK_ORDER) == "2D 합성"
    assert read_shot_text(sg, 10, KIND_DESCRIPTION) == "- 와이어 리무브"
    with pytest.raises(ShotGridError):
        shot_text_field(sg, "status")


def test_apply_writes_the_box_as_it_is() -> None:
    sg = _sg()
    # 불러온 글을 그대로 두고 덧붙였다
    kept = "2D 합성" + NL + "AI" + NL + "ENV 빙벽" + NL
    assert apply_shot_text(sg, 10, KIND_WORK_ORDER, kept, expected="2D 합성") == (
        True,
        "2D 합성" + NL + "AI" + NL + "ENV 빙벽",
    )
    assert _shot(sg)["sg_vfx_work_order"] == "2D 합성" + NL + "AI" + NL + "ENV 빙벽"
    assert _shot(sg)["description"] == "- 와이어 리무브"  # 다른 칸은 건드리지 않는다
    assert not sg._entities.get("Note")  # 노트를 만들지 않는다

    # 불러온 글을 지우고 다른 글을 썼다 — 새 글로 바뀐다
    assert apply_shot_text(sg, 10, KIND_DESCRIPTION, "피 추가", expected="- 와이어 리무브") == (
        True,
        "피 추가",
    )
    assert _shot(sg)["description"] == "피 추가"

    # 다 지우고 적용하면 칸이 비워진다
    assert apply_shot_text(sg, 10, KIND_DESCRIPTION, "  " + NL, expected="피 추가") == (True, "")
    assert _shot(sg)["description"] == ""


def test_apply_to_an_empty_column() -> None:
    sg = _sg(work_order=None, description="")
    assert apply_shot_text(sg, 10, KIND_WORK_ORDER, "MATTE", expected="") == (True, "MATTE")
    assert apply_shot_text(sg, 10, KIND_DESCRIPTION, "피 추가", expected="") == (True, "피 추가")


def test_apply_does_not_overwrite_text_changed_meanwhile() -> None:
    sg = _sg()
    # 내가 칸을 연 뒤 다른 사람이 한 줄을 더 적었다
    latest = "2D 합성" + NL + "260928 - omit"
    _shot(sg)["sg_vfx_work_order"] = latest
    done, value = apply_shot_text(sg, 10, KIND_WORK_ORDER, "AI", expected="2D 합성")
    assert (done, value) == (False, latest)  # 바꾸지 않고 지금 글을 돌려준다
    assert _shot(sg)["sg_vfx_work_order"] == latest
    # 그 글을 보고 다시 적용하면 된다
    assert apply_shot_text(sg, 10, KIND_WORK_ORDER, latest + NL + "AI", expected=latest) == (
        True,
        latest + NL + "AI",
    )
    # 화면에 글이 안 불러와져 있었는데(빈 칸) 샷그리드에는 글이 있던 경우도 덮어쓰지 않는다
    done, value = apply_shot_text(sg, 10, KIND_DESCRIPTION, "새 글", expected="")
    assert (done, value) == (False, "- 와이어 리무브")
    assert _shot(sg)["description"] == "- 와이어 리무브"


def test_apply_without_a_change_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg()
    wrote = []
    monkeypatch.setattr(sg, "update", lambda *a, **k: wrote.append(a))
    assert apply_shot_text(sg, 10, KIND_WORK_ORDER, "2D 합성" + NL, expected="2D 합성") == (
        True,
        "2D 합성",
    )
    assert wrote == []


def test_missing_shot_is_an_error() -> None:
    sg = _sg()
    with pytest.raises(ShotGridError):
        apply_shot_text(sg, 999, KIND_WORK_ORDER, "AI", expected="")
    assert _shot(sg)["sg_vfx_work_order"] == "2D 합성"


def test_site_without_a_work_order_column() -> None:
    sg = MockShotgun()
    sg._schema = {"Shot": {"code": {}, "description": {}}}
    sg._add_entity("Shot", {"id": 10, "description": ""})
    with pytest.raises(ShotGridError):
        apply_shot_text(sg, 10, KIND_WORK_ORDER, "AI", expected="")
    assert apply_shot_text(sg, 10, KIND_DESCRIPTION, "피 추가", expected="") == (True, "피 추가")


def test_save_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg()

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no permission")

    monkeypatch.setattr(sg, "update", _boom)
    with pytest.raises(ShotGridError) as err:
        apply_shot_text(sg, 10, KIND_WORK_ORDER, "AI", expected="2D 합성")
    assert "워크오더" in str(err.value) and "no permission" in str(err.value)
    assert _shot(sg)["sg_vfx_work_order"] == "2D 합성"
