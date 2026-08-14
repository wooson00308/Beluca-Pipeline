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
    monkeypatch.setattr(cfg, "SOURCE_LIBRARY_INDEX_FILE", cache_dir / "source_library.sqlite")
    monkeypatch.setattr(cfg, "MEDIA_THUMBS_DIR", cache_dir / "media_thumbs")

    # Presets default dir must stay under isolated APP_DIR (not team W: drive).
    import bpe.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_DEFAULT_PRESETS_DIR", app_dir)

    return app_dir


@pytest.fixture(autouse=True)
def _block_real_shared_library_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """source_library_config.config_dir() 의 기본값을 항상 임시 폴더로 고정한다.

    2026-08-13 사고: 격리(monkeypatch)를 빠뜨린 테스트가 pytest 실행마다 실제 팀
    공유 library.json(W:\\...)을 덮어써 데이터가 유실됐다. 개별 테스트가 스스로
    ``monkeypatch.setattr(libcfg, "config_dir", ...)`` 로 다시 지정하는 건 안전하다
    (같은 테스트 안에서 나중 호출이 이 기본값을 덮어쓴다) — 실제로 모든 기존 테스트가
    이미 그렇게 하고 있다. 이 fixture는 그걸 깜빡한 새 테스트가 나와도 실서버 경로가
    반환되지 않도록 하는 마지막 방어선이다.
    """
    import bpe.core.source_library_config as libcfg

    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "_blocked_shared_default")
