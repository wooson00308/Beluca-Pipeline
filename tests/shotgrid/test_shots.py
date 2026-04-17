"""Tests for shotgrid.shots helpers."""

from __future__ import annotations

import bpe.shotgrid.shots as shots_mod
from bpe.shotgrid.shots import (
    detect_shot_tags_field,
    normalize_shot_tag_values,
    search_shots_by_code_for_autocomplete,
    search_shots_by_code_prefix,
    shot_tag_strings_from_task_row,
)
from tests.shotgrid.mock_sg import MockShotgun


def test_search_shots_by_code_prefix() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "P"})
    sg._add_entity("Shot", {"id": 10, "code": "ABC_001", "project": {"type": "Project", "id": 1}})
    sg._add_entity("Shot", {"id": 11, "code": "ABC_002", "project": {"type": "Project", "id": 1}})
    rows = search_shots_by_code_prefix(sg, 1, "AB", limit=10)
    codes = [r.get("code") for r in rows]
    assert codes == ["ABC_001", "ABC_002"]


def test_search_shots_by_code_for_autocomplete_includes_middle_match() -> None:
    sg = MockShotgun()
    sg._add_entity("Project", {"id": 1, "code": "P"})
    sg._add_entity(
        "Shot", {"id": 10, "code": "E109_S002_0010", "project": {"type": "Project", "id": 1}}
    )
    rows = search_shots_by_code_for_autocomplete(sg, 1, "S002", limit=10)
    codes = [r.get("code") for r in rows]
    assert "E109_S002_0010" in codes


def test_detect_shot_tags_field_prefers_listish() -> None:
    shots_mod._SHOT_TAGS_FIELD_CACHE = None
    sg = MockShotgun()
    sg._set_schema(
        "Shot",
        "tags",
        {"data_type": "multi_entity", "properties": {}},
    )
    sg._set_schema("Shot", "sg_foo", {"data_type": "float", "properties": {}})
    assert detect_shot_tags_field(sg) == "tags"


def test_shot_tag_strings_from_task_row() -> None:
    row = {
        "entity": {"type": "Shot", "id": 1, "tags": ["a", "b"]},
        "entity.Shot.tags": ["a", "b"],
    }
    assert shot_tag_strings_from_task_row(row, "tags") == ["a", "b"]


def test_normalize_shot_tag_values() -> None:
    assert normalize_shot_tag_values([{"name": "tm"}, "x"]) == ["tm", "x"]
