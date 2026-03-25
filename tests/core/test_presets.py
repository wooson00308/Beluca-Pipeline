"""Tests for bpe.core.presets."""

from __future__ import annotations

from pathlib import Path

from bpe.core.presets import (
    delete_preset,
    delete_preset_template,
    ensure_store,
    get_preset,
    load_preset_template,
    load_presets,
    save_preset_template,
    save_presets,
    upsert_preset,
)


def test_ensure_store_creates_dirs(tmp_app_dir: Path) -> None:
    ensure_store()
    assert (tmp_app_dir / "presets.json").exists()


def test_empty_presets(tmp_app_dir: Path) -> None:
    assert load_presets() == {}


def test_save_and_load(tmp_app_dir: Path) -> None:
    data = {"SBS_030": {"fps": "23.976", "project_code": "SBS_030"}}
    save_presets(data)
    loaded = load_presets()
    assert loaded["SBS_030"]["fps"] == "23.976"


def test_upsert_and_get(tmp_app_dir: Path) -> None:
    upsert_preset("TEST", {"fps": "24"})
    p = get_preset("TEST")
    assert p is not None
    assert p["fps"] == "24"

    upsert_preset("TEST", {"fps": "30"})
    assert get_preset("TEST")["fps"] == "30"


def test_delete_preset(tmp_app_dir: Path) -> None:
    upsert_preset("DEL_ME", {"fps": "24"})
    assert delete_preset("DEL_ME") is True
    assert get_preset("DEL_ME") is None
    assert delete_preset("DEL_ME") is False


def test_get_nonexistent(tmp_app_dir: Path) -> None:
    assert get_preset("NOPE") is None


def test_preset_template_lifecycle(tmp_app_dir: Path) -> None:
    assert load_preset_template("T1") is None

    save_preset_template("T1", "Root {\n fps 24\n}")
    content = load_preset_template("T1")
    assert content is not None
    assert "fps 24" in content

    delete_preset_template("T1")
    assert load_preset_template("T1") is None
