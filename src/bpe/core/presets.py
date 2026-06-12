"""Preset CRUD — presets.json and per-preset NK templates."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import bpe.core.config as cfg
from bpe.core.atomic_io import atomic_write_text, write_json_file
from bpe.core.logging import get_logger
from bpe.core.settings import get_presets_dir

logger = get_logger("presets")


def _preset_file(settings_file: Optional[Path] = None) -> Path:
    return get_presets_dir(settings_file) / "presets.json"


def ensure_store() -> None:
    """Create all required directories and an empty presets.json if missing.

    네트워크 프리셋 경로에 접근할 수 없으면 로컬 폴백(``APP_DIR/presets``)을 사용한다.
    """
    cfg.APP_DIR.mkdir(parents=True, exist_ok=True)
    presets_dir = get_presets_dir()
    try:
        presets_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = cfg.APP_DIR / "presets"
        logger.warning("프리셋 경로 접근 불가 (%s), 로컬 폴백 사용: %s", presets_dir, fallback)
        fallback.mkdir(parents=True, exist_ok=True)
        presets_dir = fallback
    pf = presets_dir / "presets.json"
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
    logger.warning("presets.json 로드 실패(12회 재시도 후): %s", pf)
    return {}


def save_presets(data: Dict[str, Any]) -> None:
    """Save all presets atomically."""
    ensure_store()
    write_json_file(_preset_file(), data)


def find_matching_preset_keys(presets: Dict[str, Any], project_code: str) -> List[str]:
    """주어진 project_code에 대응하는 프리셋 키 목록을 반환한다.

    매칭 규칙:
      - 키가 project_code와 대소문자 무시 정확 일치, 또는
      - 키가 ``project_code_`` 로 시작 (언더스코어 경계로 오매칭 방지)

    예) project_code='shweq_023' → ['SHWEQ_023', 'SHWEQ_023_AI'] 매칭
        'SHWEQ_0234'는 매칭 안 됨 (언더스코어 없이 이어지므로)

    반환값은 정확 일치 항목을 앞에 두고 나머지는 알파벳 순으로 정렬한다.
    """
    pc = (project_code or "").strip().upper()
    if not pc:
        return []
    result: List[str] = []
    for k in presets:
        ku = k.upper()
        if ku == pc or ku.startswith(pc + "_"):
            result.append(k)
    return sorted(result, key=lambda k: (k.upper() != pc, k.upper()))


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
