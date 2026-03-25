"""Path constants and app-wide configuration."""

from __future__ import annotations

from pathlib import Path

# ~/.setup_pro/ 구조 — 기존 BPE v1과 100% 호환
APP_DIR = Path.home() / ".setup_pro"
CACHE_DIR = APP_DIR / "cache"
SETTINGS_FILE = APP_DIR / "settings.json"
SHOT_BUILDER_FILE = APP_DIR / "shot_builder.json"

# 캐시 파일 경로
FORMAT_CACHE_FILE = CACHE_DIR / "nuke_formats.json"
COLORSPACE_CACHE_FILE = CACHE_DIR / "nuke_colorspaces.json"
DATATYPE_CACHE_FILE = CACHE_DIR / "nuke_write_datatypes.json"
OCIO_CONFIG_CACHE_FILE = CACHE_DIR / "ocio_configs.json"
