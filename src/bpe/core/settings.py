"""settings.json read/write — tools, presets_dir, and other app-wide config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import bpe.core.config as cfg
from bpe.core.atomic_io import read_json_file, write_json_file

# Default presets directory when settings.json has no presets_dir (team pipeline).
_DEFAULT_PRESETS_DIR = Path(r"W:\team\_Pipeline\Nuke Environment Presets")

_DEFAULT_TOOLS: Dict[str, Any] = {
    "qc_checker": {"enabled": False},
    "post_render_viewer": {"enabled": False},
}

# 팀 서버 UNC → W: 드라이브 기본 매핑.
# settings.json 의 unc_mappings 가 있으면 같은 키는 파일 값이 우선(덮어씀).
_DEFAULT_UNC_MAPPINGS: Dict[str, str] = {
    "//zeus.lennon.co.kr/beluca": "W:",
}


def load_settings(settings_file: Optional[Path] = None) -> Dict[str, Any]:
    """Load the entire settings.json."""
    return read_json_file(settings_file or cfg.SETTINGS_FILE, default={})


def save_settings(data: Dict[str, Any], settings_file: Optional[Path] = None) -> None:
    """Save the entire settings.json atomically."""
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_file(settings_file or cfg.SETTINGS_FILE, data)


def get_presets_dir(settings_file: Optional[Path] = None) -> Path:
    """Return the directory where presets.json is stored."""
    settings = load_settings(settings_file)
    p = settings.get("presets_dir")
    if isinstance(p, str) and p.strip():
        return Path(p.strip())
    return _DEFAULT_PRESETS_DIR


def get_unc_mappings(settings_file: Optional[Path] = None) -> Dict[str, str]:
    """Return UNC root → drive letter mappings.

    :data:`_DEFAULT_UNC_MAPPINGS` 를 기본값으로 쓰고, ``settings.json`` 의
    ``unc_mappings`` 에 같은 키가 있으면 파일 값이 우선한다.
    """
    merged: Dict[str, str] = dict(_DEFAULT_UNC_MAPPINGS)
    settings = load_settings(settings_file)
    m = settings.get("unc_mappings")
    if not isinstance(m, dict):
        return merged
    for k, v in m.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            merged[k.strip()] = v.strip()
    return merged


def set_unc_mappings(mappings: Dict[str, str], settings_file: Optional[Path] = None) -> None:
    """Set ``unc_mappings`` in settings.json. Preserves other keys."""
    settings = load_settings(settings_file)
    settings["unc_mappings"] = dict(mappings)
    save_settings(settings, settings_file)


def set_presets_dir(path_str: str, settings_file: Optional[Path] = None) -> None:
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


def save_tools_settings(tools_data: Dict[str, Any], settings_file: Optional[Path] = None) -> None:
    """Update only the 'tools' key in settings.json."""
    settings = load_settings(settings_file)
    settings["tools"] = tools_data
    save_settings(settings, settings_file)


def get_shot_builder_settings() -> Dict[str, Any]:
    return read_json_file(cfg.SHOT_BUILDER_FILE, default={})


def save_shot_builder_settings(data: Dict[str, Any]) -> None:
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_file(cfg.SHOT_BUILDER_FILE, data)
