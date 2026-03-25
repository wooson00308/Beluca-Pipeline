"""settings.json read/write — tools, presets_dir, and other app-wide config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from bpe.core.atomic_io import read_json_file, write_json_file
import bpe.core.config as cfg

_DEFAULT_TOOLS: Dict[str, Any] = {
    "qc_checker": {"enabled": False},
    "post_render_viewer": {"enabled": False},
}


def load_settings(settings_file: Optional[Path] = None) -> Dict[str, Any]:
    """Load the entire settings.json."""
    return read_json_file(settings_file or cfg.SETTINGS_FILE, default={})


def save_settings(
    data: Dict[str, Any], settings_file: Optional[Path] = None
) -> None:
    """Save the entire settings.json atomically."""
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_file(settings_file or cfg.SETTINGS_FILE, data)


def get_presets_dir(settings_file: Optional[Path] = None) -> Path:
    """Return the directory where presets.json is stored."""
    settings = load_settings(settings_file)
    p = settings.get("presets_dir")
    if isinstance(p, str) and p.strip():
        return Path(p.strip())
    return cfg.APP_DIR


def set_presets_dir(
    path_str: str, settings_file: Optional[Path] = None
) -> None:
    """Set a custom presets directory. Preserves other settings keys."""
    path = Path(path_str).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    settings = load_settings(settings_file)
    settings["presets_dir"] = str(path)
    save_settings(settings, settings_file)


def get_tools_settings(settings_file: Optional[Path] = None) -> Dict[str, Any]:
    """Return the 'tools' section, filling missing keys with defaults."""
    settings = load_settings(settings_file)
    tools = settings.get("tools")
    if not isinstance(tools, dict):
        tools = {}
    merged: Dict[str, Any] = {}
    for key, default_val in _DEFAULT_TOOLS.items():
        entry = tools.get(key)
        if isinstance(entry, dict):
            merged[key] = {**default_val, **entry}
        else:
            merged[key] = dict(default_val)
    return merged


def save_tools_settings(
    tools_data: Dict[str, Any], settings_file: Optional[Path] = None
) -> None:
    """Update only the 'tools' key in settings.json."""
    settings = load_settings(settings_file)
    settings["tools"] = tools_data
    save_settings(settings, settings_file)


def get_shot_builder_settings() -> Dict[str, Any]:
    return read_json_file(cfg.SHOT_BUILDER_FILE, default={})


def save_shot_builder_settings(data: Dict[str, Any]) -> None:
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_file(cfg.SHOT_BUILDER_FILE, data)
