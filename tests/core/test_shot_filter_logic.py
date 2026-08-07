"""Tests for bpe.core.shot_filter_logic — 패싯 카운트와 AND/OR 매칭 규칙."""

from __future__ import annotations

from typing import Any, Dict, List, Set

import pytest

from bpe.core.shot_filter_logic import (
    ShotFacetField,
    build_facet_counts,
    facet_key,
    matching_shot_ids,
    normalize_facet_value,
    selection_value_count,
    sort_facet_values_by_label,
    split_facet_fields_for_display,
)

FIELDS = [
    ShotFacetField("sg_sequence", "Sequence", "entity"),
    ShotFacetField("sg_status_list", "Status", "status_list"),
    ShotFacetField("tags", "Tags", "multi_entity"),
]

# id / sequence(단일 엔티티 dict) / status(문자열) / tags(혼합 리스트)
SHOTS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "sg_sequence": {"type": "Sequence", "id": 9, "name": "EP03"},
        "sg_status_list": "ip",
        "tags": [{"name": "matte"}, "hero"],
    },
    {
        "id": 2,
        "sg_sequence": {"type": "Sequence", "id": 9, "name": "EP03"},
        "sg_status_list": "fin",
        "tags": ["hero"],
    },
    {
        "id": 3,
        "sg_sequence": {"type": "Sequence", "id": 10, "name": "EP04"},
        "sg_status_list": "ip",
        "tags": [],
    },
]


# ── normalize_facet_value ────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, []),
        ("", []),
        ("   ", []),
        ("EP03", ["EP03"]),
        ("  EP03  ", ["EP03"]),
        (True, ["예"]),
        (False, ["아니오"]),
        ({"type": "Sequence", "id": 1, "name": "EP03"}, ["EP03"]),
        ({"code": "EP03"}, ["EP03"]),
        ({"id": 1}, []),
        ([{"name": "matte"}, "hero", "", None, 5], ["matte", "hero"]),
        ([], []),
        (5, []),
    ],
)
def test_normalize_facet_value(raw: Any, expected: List[str]) -> None:
    assert normalize_facet_value(raw) == expected


def test_facet_key_lowercases_and_strips() -> None:
    assert facet_key("  Hero ") == "hero"
    assert facet_key(None) == ""


# ── build_facet_counts ───────────────────────────────────────────


def test_build_facet_counts_basic() -> None:
    counts = build_facet_counts(SHOTS, FIELDS)
    assert counts["sg_sequence"] == [("EP03", 2), ("EP04", 1)]
    assert counts["sg_status_list"] == [("ip", 2), ("fin", 1)]
    assert counts["tags"] == [("hero", 2), ("matte", 1)]


def test_build_facet_counts_dedupes_within_one_shot() -> None:
    rows = [{"id": 1, "tags": ["hero", "Hero", "hero"]}]
    counts = build_facet_counts(rows, [ShotFacetField("tags", "Tags", "multi_entity")])
    assert counts["tags"] == [("hero", 1)]


def test_build_facet_counts_ties_sorted_by_label() -> None:
    rows = [{"id": 1, "tags": ["b"]}, {"id": 2, "tags": ["a"]}]
    counts = build_facet_counts(rows, [ShotFacetField("tags", "Tags", "multi_entity")])
    assert counts["tags"] == [("a", 1), ("b", 1)]


def test_build_facet_counts_skips_rows_without_usable_id() -> None:
    rows = [{"id": None, "tags": ["x"]}, {"id": "bad", "tags": ["x"]}, {"id": "7", "tags": ["x"]}]
    counts = build_facet_counts(rows, [ShotFacetField("tags", "Tags", "multi_entity")])
    assert counts["tags"] == [("x", 1)]


def test_build_facet_counts_empty_field_present_as_empty_list() -> None:
    counts = build_facet_counts([{"id": 1}], FIELDS)
    assert counts["tags"] == []


# ── matching_shot_ids ────────────────────────────────────────────


@pytest.mark.parametrize(
    "selections, expected",
    [
        ({}, {1, 2, 3}),
        ({"sg_sequence": set()}, {1, 2, 3}),
        ({"sg_sequence": {"EP03"}}, {1, 2}),
        ({"sg_sequence": {"ep03"}}, {1, 2}),  # 대소문자 무시
        ({"sg_sequence": {"EP03", "EP04"}}, {1, 2, 3}),  # 같은 카테고리 = OR
        ({"sg_sequence": {"EP03"}, "sg_status_list": {"ip"}}, {1}),  # 카테고리 간 = AND
        ({"sg_sequence": {"EP04"}, "tags": {"hero"}}, set()),
        ({"tags": {"matte"}}, {1}),
        ({"sg_status_list": {"없는상태"}}, set()),
        ({"모르는필드": {"x"}}, {1, 2, 3}),  # 미지 필드는 조건에서 제외
        ({"sg_sequence": {"  "}}, {1, 2, 3}),  # 공백만 선택은 무시
    ],
)
def test_matching_shot_ids(selections: Dict[str, Set[str]], expected: Set[int]) -> None:
    assert matching_shot_ids(SHOTS, FIELDS, selections) == expected


def test_matching_shot_ids_empty_rows() -> None:
    assert matching_shot_ids([], FIELDS, {"tags": {"hero"}}) == set()


# ── selection_value_count ────────────────────────────────────────


def test_selection_value_count() -> None:
    assert selection_value_count({}) == 0
    assert selection_value_count({"a": {"x", "y"}, "b": {"z"}}) == 3
    assert selection_value_count({"a": {"x", "X"}}) == 1
    assert selection_value_count({"a": set()}) == 0


# ── sort_facet_values_by_label (ShotGrid는 개수가 아니라 이름순) ──


def test_sort_facet_values_by_label_ignores_counts() -> None:
    # SG 원본 Element: 개미 6, 군중 45, 군중 기마 41, 깃발 17, 돌 13 — 개수 순이 아님
    values = [("돌", 13), ("군중", 45), ("개미", 6), ("깃발", 17), ("군중 기마", 41)]
    assert [v for v, _n in sort_facet_values_by_label(values)] == [
        "개미",
        "군중",
        "군중 기마",
        "깃발",
        "돌",
    ]


def test_sort_facet_values_by_label_is_case_insensitive() -> None:
    values = [("beta", 1), ("Alpha", 9), ("gamma", 5)]
    assert [v for v, _n in sort_facet_values_by_label(values)] == ["Alpha", "beta", "gamma"]


def test_sort_facet_values_by_label_does_not_mutate_input() -> None:
    values = [("b", 1), ("a", 2)]
    sort_facet_values_by_label(values)
    assert values == [("b", 1), ("a", 2)]


# ── split_facet_fields_for_display ───────────────────────────────


def _field(name: str, *, primary: bool = False) -> ShotFacetField:
    return ShotFacetField(name, name.title(), "list", primary=primary)


def _counts(**spec: int) -> Dict[str, List[Any]]:
    """필드별 값 종류 개수만 흉내낸 counts dict."""
    return {name: [(f"v{i}", 1) for i in range(n)] for name, n in spec.items()}


def test_split_keeps_primary_order_and_moves_rest() -> None:
    fields = [
        _field("sequence", primary=True),
        _field("status", primary=True),
        _field("tags", primary=True),
        _field("assets"),
        _field("location"),
    ]
    primary, secondary = split_facet_fields_for_display(
        fields, _counts(sequence=16, status=11, tags=8, assets=2, location=8)
    )
    assert [f.field_name for f in primary] == ["sequence", "status", "tags"]
    assert [f.field_name for f in secondary] == ["assets", "location"]


def test_split_pushes_useless_fields_to_the_end() -> None:
    """값이 샷마다 다른 필드(554종)와 값이 1개뿐인 필드는 뒤로."""
    fields = [
        _field("sequence", primary=True),
        _field("status", primary=True),
        _field("tags", primary=True),
        _field(
            "image_source",
        ),
        _field("type"),
        _field("location"),
    ]
    _p, secondary = split_facet_fields_for_display(
        fields, _counts(sequence=16, status=11, tags=8, image_source=554, type=1, location=8)
    )
    assert [f.field_name for f in secondary] == ["location", "type", "image_source"]


def test_split_promotes_when_primary_too_few() -> None:
    fields = [
        _field("sequence", primary=True),
        _field("aaa"),
        _field("bbb"),
        _field("ccc"),
        _field("ddd"),
    ]
    primary, secondary = split_facet_fields_for_display(
        fields, _counts(sequence=5, aaa=3, bbb=3, ccc=3, ddd=3)
    )
    assert [f.field_name for f in primary] == ["sequence", "aaa", "bbb", "ccc", "ddd"]
    assert secondary == []


def test_split_promotion_skips_fields_without_values() -> None:
    fields = [_field("aaa"), _field("empty"), _field("bbb")]
    primary, secondary = split_facet_fields_for_display(fields, _counts(aaa=3, bbb=3))
    assert [f.field_name for f in primary] == ["aaa", "bbb"]
    assert [f.field_name for f in secondary] == ["empty"]


def test_split_no_promotion_when_enough_primary() -> None:
    fields = [
        _field("sequence", primary=True),
        _field("status", primary=True),
        _field("tags", primary=True),
        _field("zzz"),
    ]
    primary, secondary = split_facet_fields_for_display(
        fields, _counts(sequence=5, status=5, tags=5, zzz=5)
    )
    assert len(primary) == 3
    assert [f.field_name for f in secondary] == ["zzz"]


def test_split_handles_empty_input() -> None:
    assert split_facet_fields_for_display([], {}) == ([], [])
