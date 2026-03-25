"""Tests for bpe.core.cache."""

from __future__ import annotations

from pathlib import Path

from bpe.core.cache import (
    load_colorspaces_cache,
    load_datatypes_cache,
    load_nuke_formats_cache,
    load_ocio_configs_cache,
    save_colorspaces_cache,
    save_datatypes_cache,
    save_nuke_formats_cache,
    save_ocio_configs_cache,
)


def test_formats_empty(tmp_app_dir: Path) -> None:
    assert load_nuke_formats_cache() == {}


def test_formats_roundtrip(tmp_app_dir: Path) -> None:
    data = {"HD": "1920 1080"}
    save_nuke_formats_cache(data)
    assert load_nuke_formats_cache() == data


def test_colorspaces_roundtrip(tmp_app_dir: Path) -> None:
    data = ["sRGB", "ACES - ACES2065-1", "scene_linear"]
    save_colorspaces_cache(data)
    assert load_colorspaces_cache() == data


def test_datatypes_roundtrip(tmp_app_dir: Path) -> None:
    data = ["16 bit half", "32 bit float"]
    save_datatypes_cache(data)
    assert load_datatypes_cache() == data


def test_ocio_configs_roundtrip(tmp_app_dir: Path) -> None:
    data = ["/path/to/config.ocio"]
    save_ocio_configs_cache(data)
    assert load_ocio_configs_cache() == data
