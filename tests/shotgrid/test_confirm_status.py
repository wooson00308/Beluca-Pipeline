"""Tests for bpe.shotgrid.confirm_status — 상태 색·아이콘 (MockShotgun)."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from bpe.shotgrid.confirm_status import fetch_status_styles
from tests.shotgrid.mock_sg import MockShotgun

_PNG = b"\x89PNG\r\n\x1a\nfake"


def _sg() -> MockShotgun:
    sg = MockShotgun()
    sg._add_entity(
        "Status",
        {
            "id": 1,
            "code": "sv",
            "name": "supervisor confirm",
            "bg_color": "29,215,46",
            "icon": {"type": "Icon", "id": 119},
        },
    )
    sg._add_entity(
        "Status",
        {
            "id": 2,
            "code": "retake",
            "name": "retake",
            "bg_color": "253,205,68",
            "icon": {"type": "Icon", "id": 93},
        },
    )
    sg._add_entity("Status", {"id": 3, "code": "na", "name": "N/A", "bg_color": None, "icon": None})
    data = base64.b64encode(_PNG).decode("ascii")
    # 샷그리드는 base64 를 여러 줄로 끊어 준다
    sg._add_entity(
        "Icon", {"id": 119, "image_data": data[:8] + "\n" + data[8:], "image_map_key": "None"}
    )
    sg._add_entity("Icon", {"id": 93, "image_data": "None", "image_map_key": "icon_undo"})
    return sg


def test_status_styles_carry_colour_name_and_icon() -> None:
    st = fetch_status_styles(_sg())
    assert st["sv"]["name"] == "supervisor confirm" and st["sv"]["color"] == "#1dd72e"
    assert st["sv"]["icon_png"] == _PNG and st["sv"]["icon_key"] == ""
    assert st["retake"]["color"] == "#fdcd44"
    assert st["retake"]["icon_png"] == b"" and st["retake"]["icon_key"] == "icon_undo"
    assert st["na"]["color"] == "" and st["na"]["icon_png"] == b""


def test_status_styles_can_be_limited_to_some_codes() -> None:
    assert sorted(fetch_status_styles(_sg(), ["SV"])) == ["sv"]


def test_icon_lookup_failure_keeps_names_and_colours(monkeypatch: pytest.MonkeyPatch) -> None:
    sg = _sg()
    real_find = sg.find

    def _find(entity: str, *a: Any, **k: Any) -> Any:
        if entity == "Icon":
            raise RuntimeError("조회 실패")
        return real_find(entity, *a, **k)

    monkeypatch.setattr(sg, "find", _find)
    st = fetch_status_styles(sg)
    assert st["sv"]["color"] == "#1dd72e" and st["sv"]["icon_png"] == b""
