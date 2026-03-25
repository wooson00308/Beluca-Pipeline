"""Shared fixtures for all BPE tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated APP_DIR — patches bpe.core.config so every module sees tmp paths."""
    app_dir = tmp_path / ".setup_pro"
    app_dir.mkdir()
    cache_dir = app_dir / "cache"
    cache_dir.mkdir()

    import bpe.core.config as cfg

    monkeypatch.setattr(cfg, "APP_DIR", app_dir)
    monkeypatch.setattr(cfg, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(cfg, "SETTINGS_FILE", app_dir / "settings.json")
    monkeypatch.setattr(cfg, "SHOT_BUILDER_FILE", app_dir / "shot_builder.json")
    monkeypatch.setattr(cfg, "FORMAT_CACHE_FILE", cache_dir / "nuke_formats.json")
    monkeypatch.setattr(cfg, "COLORSPACE_CACHE_FILE", cache_dir / "nuke_colorspaces.json")
    monkeypatch.setattr(cfg, "DATATYPE_CACHE_FILE", cache_dir / "nuke_write_datatypes.json")
    monkeypatch.setattr(cfg, "OCIO_CONFIG_CACHE_FILE", cache_dir / "ocio_configs.json")

    return app_dir
