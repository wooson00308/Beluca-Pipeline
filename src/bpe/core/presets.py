"""Preset CRUD — presets.json and per-preset NK templates."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import bpe.core.config as cfg
from bpe.core.atomic_io import atomic_write_text, write_json_file
from bpe.core.settings import get_presets_dir


def _preset_file(settings_file: Optional[Path] = None) -> Path:
    return get_presets_dir() / "presets.json"


def ensure_store() -> None:
    """Create all required directories and an empty presets.json if missing."""
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    presets_dir = get_presets_dir()
    presets_dir.mkdir(parents=True, exist_ok=True)
    pf = _preset_file()
    if not pf.exists():
        atomic_write_text(pf, "{}")
    cfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_presets() -> Dict[str, Any]:
    """Load presets.json with retry for concurrent access on network folders."""
    ensure_store()
    pf = _preset_file()
    for _ in range(12):
        try:
            raw = pf.read_text(encoding="utf-8").strip()
            if not raw:
                return {}
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return {}
        except (json.JSONDecodeError, OSError, PermissionError):
            time.sleep(0.04)
    return {}


def save_presets(data: Dict[str, Any]) -> None:
    """Save all presets atomically."""
    ensure_store()
    write_json_file(_preset_file(), data)


def get_preset(name: str) -> Optional[Dict[str, Any]]:
    """Return a single preset by name, or None."""
    all_presets = load_presets()
    v = all_presets.get(name)
    return v if isinstance(v, dict) else None


def upsert_preset(name: str, data: Dict[str, Any]) -> None:
    """Insert or update a preset."""
    all_presets = load_presets()
    all_presets[name] = data
    save_presets(all_presets)


def delete_preset(name: str) -> bool:
    """Delete a preset. Returns True if it existed."""
    all_presets = load_presets()
    if name not in all_presets:
        return False
    del all_presets[name]
    save_presets(all_presets)
    delete_preset_template(name)
    return True


# Per-preset custom NK templates


def get_preset_template_path(preset_name: str) -> Path:
    return get_presets_dir() / f"{preset_name}_template.nk"


def save_preset_template(preset_name: str, content: str) -> None:
    ensure_store()
    atomic_write_text(get_preset_template_path(preset_name), content)


def load_preset_template(preset_name: str) -> Optional[str]:
    path = get_preset_template_path(preset_name)
    if path.exists():
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    return None


def delete_preset_template(preset_name: str) -> None:
    path = get_preset_template_path(preset_name)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
