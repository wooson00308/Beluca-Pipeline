"""Tests for My Tasks assignee display / Enter-resolve helpers."""

from __future__ import annotations

from bpe.gui.tabs.my_tasks_tab import _format_human_user_display, _pick_user_for_enter_resolve


def test_format_human_user_full() -> None:
    u = {"name": "김가영", "login": "gykim", "email": "gykim@beluca.co.kr"}
    assert _format_human_user_display(u) == "김가영 gykim (gykim@beluca.co.kr)"


def test_format_human_user_name_login_only() -> None:
    u = {"name": "A", "login": "b", "email": ""}
    assert _format_human_user_display(u) == "A b"


def test_pick_enter_single() -> None:
    users = [{"id": 1, "name": "권동설", "login": "kds"}]
    assert _pick_user_for_enter_resolve(users, "권") == users[0]


def test_pick_enter_exact_name_among_many() -> None:
    users = [
        {"id": 1, "name": "김", "login": "kim1"},
        {"id": 2, "name": "김가영", "login": "gykim"},
    ]
    assert _pick_user_for_enter_resolve(users, "김가영") == users[1]


def test_pick_enter_ambiguous() -> None:
    users = [
        {"id": 1, "name": "김", "login": "a"},
        {"id": 2, "name": "김", "login": "b"},
    ]
    assert _pick_user_for_enter_resolve(users, "김") is None
