"""Tests for My Tasks delivery-date sort helpers and natural shot sort."""

from __future__ import annotations

from bpe.gui.tabs.my_tasks_tab import (
    _SORT_MODE_DELIVERY,
    _SORT_MODE_SHOT,
    _natural_sort_key,
    _sort_tasks_by_mode,
    sort_tasks_by_delivery_urgency,
)


def test_sort_empty() -> None:
    assert sort_tasks_by_delivery_urgency([]) == []


def test_sort_by_date_ascending() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "C", "delivery_date": "2025-06-01"},
        {"task_id": 2, "shot_code": "A", "delivery_date": "2025-03-15"},
        {"task_id": 3, "shot_code": "B", "delivery_date": "2025-04-20"},
    ]
    out = sort_tasks_by_delivery_urgency(tasks)
    assert [t["task_id"] for t in out] == [2, 3, 1]


def test_sort_missing_date_last() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "X", "delivery_date": None},
        {"task_id": 2, "shot_code": "Y", "delivery_date": "2025-01-01"},
        {"task_id": 3, "shot_code": "Z", "delivery_date": ""},
    ]
    out = sort_tasks_by_delivery_urgency(tasks)
    assert out[0]["task_id"] == 2
    assert {out[1]["task_id"], out[2]["task_id"]} == {1, 3}


def test_sort_same_date_tiebreak_task_id() -> None:
    tasks = [
        {"task_id": 30, "shot_code": "S", "delivery_date": "2025-05-05"},
        {"task_id": 10, "shot_code": "S", "delivery_date": "2025-05-05"},
        {"task_id": 20, "shot_code": "S", "delivery_date": "2025-05-05"},
    ]
    out = sort_tasks_by_delivery_urgency(tasks)
    assert [t["task_id"] for t in out] == [10, 20, 30]


def test_sort_dict_delivery_field() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "a", "delivery_date": {"date": "2025-12-01"}},
        {"task_id": 2, "shot_code": "b", "delivery_date": {"date": "2025-01-01"}},
    ]
    out = sort_tasks_by_delivery_urgency(tasks)
    assert [t["task_id"] for t in out] == [2, 1]


def test_sort_parse_failure_last() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "a", "delivery_date": "not-a-date"},
        {"task_id": 2, "shot_code": "b", "delivery_date": "2025-02-01"},
    ]
    out = sort_tasks_by_delivery_urgency(tasks)
    assert out[0]["task_id"] == 2
    assert out[1]["task_id"] == 1


def test_natural_sort_key_numeric_order() -> None:
    assert _natural_sort_key("shot_2") < _natural_sort_key("shot_10")


def test_sort_tasks_by_mode_shot_ascending() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "CID_010", "task_status": "wip"},
        {"task_id": 2, "shot_code": "CID_002", "task_status": "wip"},
    ]
    out = _sort_tasks_by_mode(tasks, _SORT_MODE_SHOT, ascending=True)
    assert [t["task_id"] for t in out] == [2, 1]


def test_sort_tasks_by_mode_delivery_matches_urgency() -> None:
    tasks = [
        {"task_id": 1, "shot_code": "C", "delivery_date": "2025-06-01"},
        {"task_id": 2, "shot_code": "A", "delivery_date": "2025-03-15"},
    ]
    out_mode = _sort_tasks_by_mode(tasks, _SORT_MODE_DELIVERY, ascending=True)
    out_legacy = sort_tasks_by_delivery_urgency(tasks)
    assert [t["task_id"] for t in out_mode] == [t["task_id"] for t in out_legacy]
