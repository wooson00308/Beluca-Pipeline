"""Tests for bpe.shotgrid.shot_filters — 스키마 기반 카테고리 탐색과 Shot 값 수집."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from bpe.shotgrid.shot_filters import (
    clear_shot_facet_cache,
    discover_shot_facet_fields,
    fetch_shot_facet_data,
)
from tests.shotgrid.mock_sg import MockShotgun


def _wrap(value: Any) -> Dict[str, Any]:
    """실제 ShotGrid 스키마 응답 형태 ``{"value": ...}``."""
    return {"value": value}


def _schema_entry(data_type: str, label: str, *, visible: bool = True) -> Dict[str, Any]:
    return {
        "data_type": _wrap(data_type),
        "name": _wrap(label),
        "visible": _wrap(visible),
        "properties": {"valid_values": _wrap([])},
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_shot_facet_cache()


def _sg_with_schema() -> MockShotgun:
    sg = MockShotgun()
    sg._set_schema("Shot", "sg_sequence", _schema_entry("entity", "Sequence"))
    sg._set_schema("Shot", "sg_status_list", _schema_entry("status_list", "Status"))
    sg._set_schema("Shot", "tags", _schema_entry("multi_entity", "Tags"))
    sg._set_schema("Shot", "sg_element", _schema_entry("list", "Element"))
    sg._set_schema("Shot", "sg_omit", _schema_entry("checkbox", "Omit"))
    # 제외 대상: 자유서술·시스템 필드, 지원하지 않는 타입, 숨김 필드
    sg._set_schema("Shot", "description", _schema_entry("text", "Description"))
    sg._set_schema("Shot", "code", _schema_entry("text", "Shot Code"))
    sg._set_schema("Shot", "sg_cut_in", _schema_entry("number", "Cut In"))
    sg._set_schema("Shot", "sg_secret", _schema_entry("list", "Secret", visible=False))
    return sg


def test_discover_returns_only_filterable_visible_fields() -> None:
    sg = _sg_with_schema()
    fields = discover_shot_facet_fields(sg, 1)
    names = [f.field_name for f in fields]
    # ShotGrid Shot 패널 순서(Sequence → Status → Tags → Element → Char) 우선, 나머지는 뒤로
    assert names == ["sg_sequence", "sg_status_list", "tags", "sg_element", "sg_omit"]
    assert "description" not in names
    assert "sg_cut_in" not in names
    assert "sg_secret" not in names


def test_discover_marks_shotgrid_primary_categories() -> None:
    sg = _sg_with_schema()
    primary = {f.field_name for f in discover_shot_facet_fields(sg, 1) if f.primary}
    assert primary == {"sg_sequence", "sg_status_list", "tags", "sg_element"}


def test_discover_primary_prefers_exact_label_over_partial() -> None:
    """``Status Note`` 같은 필드가 진짜 ``Status``를 밀어내면 안 된다."""
    sg = MockShotgun()
    sg._set_schema("Shot", "sg_status_note", _schema_entry("list", "Status Note"))
    sg._set_schema("Shot", "sg_status_list", _schema_entry("status_list", "Status"))
    fields = {f.field_name: f.primary for f in discover_shot_facet_fields(sg, 1)}
    assert fields["sg_status_list"] is True
    assert fields["sg_status_note"] is False


def test_discover_primary_matches_by_field_name_when_label_differs() -> None:
    sg = MockShotgun()
    sg._set_schema("Shot", "sg_sequence", _schema_entry("entity", "에피소드"))
    fields = discover_shot_facet_fields(sg, 1)
    assert [f.primary for f in fields] == [True]


def test_discover_primary_allows_partial_label_match() -> None:
    sg = MockShotgun()
    sg._set_schema("Shot", "sg_cast", _schema_entry("multi_entity", "Characters"))
    fields = discover_shot_facet_fields(sg, 1)
    assert fields[0].primary is True


def test_discover_passes_project_entity() -> None:
    sg = _sg_with_schema()
    discover_shot_facet_fields(sg, 42)
    assert sg.last_schema_project_entity == {"type": "Project", "id": 42}


def test_discover_uses_display_label() -> None:
    sg = _sg_with_schema()
    fields = {f.field_name: f.display_label for f in discover_shot_facet_fields(sg, 1)}
    assert fields["sg_sequence"] == "Sequence"
    assert fields["tags"] == "Tags"


def test_discover_handles_flat_schema_shape() -> None:
    sg = MockShotgun()
    sg._set_schema("Shot", "tags", {"data_type": "multi_entity", "name": "Tags"})
    fields = discover_shot_facet_fields(sg, 1)
    assert [f.field_name for f in fields] == ["tags"]


def test_discover_caches_per_project() -> None:
    sg = _sg_with_schema()
    first = discover_shot_facet_fields(sg, 1)
    sg._schema["Shot"].clear()
    cached = discover_shot_facet_fields(sg, 1)
    assert [f.field_name for f in cached] == [f.field_name for f in first]
    assert discover_shot_facet_fields(sg, 2) == []


def test_discover_survives_schema_error() -> None:
    class Boom:
        def schema_field_read(self, *a: Any, **k: Any) -> Dict[str, Any]:
            raise RuntimeError("permission denied")

    assert discover_shot_facet_fields(Boom(), 1) == []


def test_discover_invalid_project_id() -> None:
    assert discover_shot_facet_fields(_sg_with_schema(), None) == []


# ── fetch_shot_facet_data ────────────────────────────────────────


def _sg_with_shots(n: int) -> MockShotgun:
    sg = _sg_with_schema()
    sg._add_entity("Project", {"id": 1, "code": "P"})
    for i in range(n):
        sg._add_entity(
            "Shot",
            {
                "id": 100 + i,
                "code": f"SH{i:03d}",
                "project": {"type": "Project", "id": 1},
                "sg_status_list": "ip" if i % 2 == 0 else "fin",
                "tags": ["hero"] if i % 3 == 0 else [],
            },
        )
    return sg


def test_fetch_returns_id_and_facet_fields_only() -> None:
    sg = _sg_with_shots(3)
    fields = discover_shot_facet_fields(sg, 1)
    rows = fetch_shot_facet_data(sg, 1, fields)
    assert len(rows) == 3
    assert set(rows[0]) <= {"type", "id", *[f.field_name for f in fields]}
    assert "code" not in rows[0]


def test_fetch_paginates_past_chunk_size() -> None:
    sg = _sg_with_shots(7)
    fields = discover_shot_facet_fields(sg, 1)
    rows = fetch_shot_facet_data(sg, 1, fields, chunk=2)
    assert [r["id"] for r in rows] == [100 + i for i in range(7)]


def test_fetch_respects_max_rows_cap() -> None:
    sg = _sg_with_shots(10)
    fields = discover_shot_facet_fields(sg, 1)
    rows = fetch_shot_facet_data(sg, 1, fields, chunk=2, max_rows=4)
    assert len(rows) == 4


def test_fetch_never_uses_unlimited_find() -> None:
    """limit=0(무제한)으로 조회하면 대형 프로젝트에서 타임아웃 난다."""
    sg = _sg_with_shots(3)
    fields = discover_shot_facet_fields(sg, 1)
    seen: List[int] = []
    original = sg.find

    def _spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(int(kwargs.get("limit", 0)))
        return original(*args, **kwargs)

    sg.find = _spy  # type: ignore[method-assign]
    fetch_shot_facet_data(sg, 1, fields)
    assert seen and all(limit > 0 for limit in seen)


def test_fetch_without_fields_returns_empty() -> None:
    assert fetch_shot_facet_data(_sg_with_shots(2), 1, []) == []


def test_fetch_drops_unqueryable_fields() -> None:
    sg = _sg_with_shots(2)
    fields = discover_shot_facet_fields(sg, 1)
    original = sg.find

    def _picky(entity_type: str, filters: Any, read_fields: Any, **kwargs: Any) -> Any:
        if "tags" in (read_fields or []):
            raise RuntimeError("field not readable: tags")
        return original(entity_type, filters, read_fields, **kwargs)

    sg.find = _picky  # type: ignore[method-assign]
    rows = fetch_shot_facet_data(sg, 1, fields)
    assert len(rows) == 2
    assert all("tags" not in r for r in rows)


def test_fetch_survives_total_failure() -> None:
    sg = _sg_with_shots(2)
    fields = discover_shot_facet_fields(sg, 1)

    def _boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("down")

    sg.find = _boom  # type: ignore[method-assign]
    assert fetch_shot_facet_data(sg, 1, fields) == []
