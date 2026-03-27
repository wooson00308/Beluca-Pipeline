"""Tests for VFX work order and delivery date field helpers on Shot (tasks module)."""

from __future__ import annotations

from bpe.shotgrid import tasks as tasks_mod


def test_detect_shot_vfx_field_matches_schema_name() -> None:
    class FakeSG:
        def schema_field_read(self, entity_type: str, field_name: str | None = None) -> dict:
            assert entity_type == "Shot"
            return {"code": {}, "sg_vfx_work_order": {}, "description": {}}

    prev = tasks_mod._VFX_FIELD_CACHE
    try:
        tasks_mod._VFX_FIELD_CACHE = None
        assert tasks_mod._detect_shot_vfx_field(FakeSG()) == "sg_vfx_work_order"
    finally:
        tasks_mod._VFX_FIELD_CACHE = prev


def test_detect_shot_vfx_field_empty_when_no_match() -> None:
    class FakeSG:
        def schema_field_read(self, entity_type: str, field_name: str | None = None) -> dict:
            return {"code": {}, "description": {}}

    prev = tasks_mod._VFX_FIELD_CACHE
    try:
        tasks_mod._VFX_FIELD_CACHE = None
        assert tasks_mod._detect_shot_vfx_field(FakeSG()) == ""
    finally:
        tasks_mod._VFX_FIELD_CACHE = prev


def test_vfx_work_order_from_row_entity_shot_key() -> None:
    row = {"entity.Shot.sg_vfx_work_order": "note text"}
    assert tasks_mod._vfx_work_order_from_row(row, "sg_vfx_work_order") == "note text"


def test_vfx_work_order_from_row_empty_field() -> None:
    assert tasks_mod._vfx_work_order_from_row({}, "sg_vfx_work_order") == ""


def test_detect_shot_delivery_date_field_prefers_sg_delivery_date() -> None:
    class FakeSG:
        def schema_field_read(self, entity_type: str, field_name: str | None = None) -> dict:
            assert entity_type == "Shot"
            return {
                "code": {},
                "sg_foo": {},
                "sg_delivery_date": {},
                "description": {},
            }

    prev = tasks_mod._DELIVERY_FIELD_CACHE
    try:
        tasks_mod._DELIVERY_FIELD_CACHE = None
        assert tasks_mod._detect_shot_delivery_date_field(FakeSG()) == "sg_delivery_date"
    finally:
        tasks_mod._DELIVERY_FIELD_CACHE = prev


def test_detect_shot_delivery_date_field_delivery_and_date_in_name() -> None:
    class FakeSG:
        def schema_field_read(self, entity_type: str, field_name: str | None = None) -> dict:
            return {"code": {}, "sg_custom_delivery_date_x": {}, "description": {}}

    prev = tasks_mod._DELIVERY_FIELD_CACHE
    try:
        tasks_mod._DELIVERY_FIELD_CACHE = None
        assert tasks_mod._detect_shot_delivery_date_field(FakeSG()) == "sg_custom_delivery_date_x"
    finally:
        tasks_mod._DELIVERY_FIELD_CACHE = prev


def test_detect_shot_delivery_date_field_empty_when_no_match() -> None:
    class FakeSG:
        def schema_field_read(self, entity_type: str, field_name: str | None = None) -> dict:
            return {"code": {}, "description": {}}

    prev = tasks_mod._DELIVERY_FIELD_CACHE
    try:
        tasks_mod._DELIVERY_FIELD_CACHE = None
        assert tasks_mod._detect_shot_delivery_date_field(FakeSG()) == ""
    finally:
        tasks_mod._DELIVERY_FIELD_CACHE = prev


def test_delivery_date_from_row_entity_shot_key() -> None:
    row = {"entity.Shot.sg_delivery_date": "2026-04-23"}
    assert tasks_mod._delivery_date_from_row(row, "sg_delivery_date") == "2026-04-23"


def test_delivery_date_from_row_dict_date() -> None:
    row = {"entity.Shot.sg_delivery_date": {"date": "2026-04-23"}}
    assert tasks_mod._delivery_date_from_row(row, "sg_delivery_date") == "2026-04-23"
