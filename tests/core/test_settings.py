"""Tests for bpe.core.settings."""

from __future__ import annotations

from pathlib import Path

import bpe.core.settings as settings_mod
from bpe.core.settings import (
    get_presets_dir,
    get_tools_settings,
    get_unc_mappings,
    load_settings,
    save_settings,
    save_tools_settings,
    set_presets_dir,
    set_unc_mappings,
)


def test_load_empty(tmp_app_dir: Path) -> None:
    assert load_settings() == {}


def test_save_and_load(tmp_app_dir: Path) -> None:
    save_settings({"foo": "bar"})
    assert load_settings() == {"foo": "bar"}


def test_presets_dir_default(tmp_app_dir: Path) -> None:
    assert get_presets_dir() == settings_mod._DEFAULT_PRESETS_DIR


def test_set_presets_dir(tmp_app_dir: Path, tmp_path: Path) -> None:
    custom = tmp_path / "custom_presets"
    set_presets_dir(str(custom))
    assert get_presets_dir() == custom.resolve()
    assert custom.exists()
    # Other settings preserved
    save_settings({**load_settings(), "other_key": 123})
    assert load_settings()["other_key"] == 123
    assert get_presets_dir() == custom.resolve()


def test_tools_defaults(tmp_app_dir: Path) -> None:
    tools = get_tools_settings()
    assert tools["qc_checker"]["enabled"] is False
    assert tools["post_render_viewer"]["enabled"] is False


def test_tools_merge(tmp_app_dir: Path) -> None:
    save_settings({"tools": {"qc_checker": {"enabled": True}}})
    tools = get_tools_settings()
    assert tools["qc_checker"]["enabled"] is True
    assert tools["post_render_viewer"]["enabled"] is False


def test_save_tools_preserves_other_keys(tmp_app_dir: Path) -> None:
    save_settings({"presets_dir": "/some/path", "tools": {}})
    save_tools_settings({"qc_checker": {"enabled": True}})
    s = load_settings()
    assert s["presets_dir"] == "/some/path"
    assert s["tools"]["qc_checker"]["enabled"] is True


def test_unc_mappings_default_contains_zeus(tmp_app_dir: Path) -> None:
    m = get_unc_mappings()
    assert "//zeus.lennon.co.kr/beluca" in m
    assert m["//zeus.lennon.co.kr/beluca"] == "W:"


def test_set_get_unc_mappings(tmp_app_dir: Path) -> None:
    set_unc_mappings({"//zeus.lennon.co.kr/beluca": "W:"})
    assert get_unc_mappings() == {"//zeus.lennon.co.kr/beluca": "W:"}
    save_settings({**load_settings(), "other": 1})
    assert load_settings()["other"] == 1
    assert get_unc_mappings()["//zeus.lennon.co.kr/beluca"] == "W:"
