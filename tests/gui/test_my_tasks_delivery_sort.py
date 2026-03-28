"""Tests for My Tasks status combo Delivery + delivery-date sort helpers."""

from __future__ import annotations

from bpe.gui.tabs.my_tasks_tab import (
    STATUS_COMBO_ALL,
    STATUS_COMBO_DELIVERY,
    parse_status_combo_for_fetch,
    sort_tasks_by_delivery_urgency,
)


def test_parse_delivery_sort() -> None:
    assert parse_status_combo_for_fetch(STATUS_COMBO_DELIVERY) == (None, True)


def test_parse_all_no_sort() -> None:
    assert parse_status_combo_for_fetch(STATUS_COMBO_ALL) == (None, False)


def test_parse_wip() -> None:
    assert parse_status_combo_for_fetch("wip") == ("wip", False)


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
