"""Tests for Time Log duration text parsing."""

from __future__ import annotations

from bpe.gui.widgets.time_log_dialog import _parse_duration_minutes


def test_parse_duration_h_m() -> None:
    assert _parse_duration_minutes("1h 30m") == 90
    assert _parse_duration_minutes("2h") == 120
    assert _parse_duration_minutes("90m") == 90


def test_parse_duration_bare_number() -> None:
    assert _parse_duration_minutes("2") == 120
    assert _parse_duration_minutes("90") == 90


def test_parse_duration_decimal_hours() -> None:
    assert _parse_duration_minutes("1.5h") == 90


def test_parse_duration_empty() -> None:
    assert _parse_duration_minutes("") == 0
    assert _parse_duration_minutes("   ") == 0
