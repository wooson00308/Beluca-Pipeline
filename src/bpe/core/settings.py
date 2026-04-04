"""settings.json read/write — tools, presets_dir, and other app-wide config."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import bpe.core.config as cfg
from bpe.core.atomic_io import read_json_file, write_json_file
from bpe.core.logging import get_logger

logger = get_logger("settings")

# Default presets directory when settings.json has no presets_dir.
# Windows: 팀 네트워크 드라이브 / macOS: 로컬 앱 디렉토리
if sys.platform == "win32":
    _DEFAULT_PRESETS_DIR = Path(r"W:\team\_Pipeline\Nuke Environment Presets")
else:
    _DEFAULT_PRESETS_DIR = cfg.APP_DIR / "presets"

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
    """Return the directory where presets.json is stored.

    설정값 또는 플랫폼 기본 경로를 반환한다.
    네트워크 경로가 접근 불가능하면 로컬 폴백(``APP_DIR/presets``)을 반환한다.
    """
    _LOCAL_FALLBACK = cfg.APP_DIR / "presets"

    settings = load_settings(settings_file)
    p = settings.get("presets_dir")
    target = Path(p.strip()) if isinstance(p, str) and p.strip() else _DEFAULT_PRESETS_DIR

    # 이미 존재하면 바로 반환
    if target.exists():
        return target

    # 존재하지 않으면 생성 시도, 실패 시 로컬 폴백
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        logger.warning("프리셋 경로 접근 불가 (%s), 로컬 폴백: %s", target, _LOCAL_FALLBACK)
        return _LOCAL_FALLBACK


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
