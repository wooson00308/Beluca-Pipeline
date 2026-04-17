"""Tests for My Tasks shot substring filter helper."""

from __future__ import annotations

from bpe.gui.tabs.my_tasks_tab import _filter_tasks_by_shot_substring


def test_filter_tasks_by_shot_substring_empty_needle_returns_all() -> None:
    tasks = [
        {"shot_code": "A_001", "task_id": 1},
        {"shot_code": "B_002", "task_id": 2},
    ]
    assert len(_filter_tasks_by_shot_substring(tasks, None)) == 2
    assert len(_filter_tasks_by_shot_substring(tasks, "")) == 2


def test_filter_tasks_by_shot_substring_case_insensitive() -> None:
    tasks = [
        {"shot_code": "E109_S002_0010", "task_id": 1},
        {"shot_code": "OTHER", "task_id": 2},
    ]
    out = _filter_tasks_by_shot_substring(tasks, "e109")
    assert len(out) == 1
    assert out[0]["task_id"] == 1


def test_filter_tasks_by_shot_substring_middle_of_code() -> None:
    tasks = [
        {"shot_code": "E109_S002_0010", "task_id": 1},
        {"shot_code": "E110_S002_0010", "task_id": 2},
    ]
    out = _filter_tasks_by_shot_substring(tasks, "S002")
    assert len(out) == 2


def test_filter_tasks_by_shot_substring_short_needle_noop() -> None:
    tasks = [{"shot_code": "AB", "task_id": 1}]
    assert len(_filter_tasks_by_shot_substring(tasks, "a")) == 1
