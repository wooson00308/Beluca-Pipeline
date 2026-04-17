"""Tests for Feedback tab project path helpers."""

from __future__ import annotations

from typing import Any, Dict

from bpe.gui.tabs.feedback_tab import _effective_project_for_paths


def test_effective_prefers_code() -> None:
    t: Dict[str, Any] = {
        "project_code": "CODE",
        "project_folder": "FOLDER",
        "project_name": "NAME",
    }
    assert _effective_project_for_paths(t) == "CODE"


def test_effective_falls_back_to_folder() -> None:
    t: Dict[str, Any] = {
        "project_code": "",
        "project_folder": "FOLDER",
        "project_name": "NAME",
    }
    assert _effective_project_for_paths(t) == "FOLDER"


def test_effective_falls_back_to_name() -> None:
    t: Dict[str, Any] = {
        "project_code": "",
        "project_folder": "",
        "project_name": "NAME",
    }
    assert _effective_project_for_paths(t) == "NAME"
