"""ShotGrid settings — 4-layer merge: defaults -> studio.json -> settings.json -> env vars."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import bpe.core.config as cfg
from bpe.core.settings import load_settings, save_settings

_DEFAULT_SHOTGRID: Dict[str, Any] = {
    "base_url": "https://beluca.shotgrid.autodesk.com",
    "script_name": "belucaAPI",
    "script_key": "dnolt2flVfbdoehoknpfp)bbc",
    "published_file_type": "Image Sequence",
    "task_content": "comp",
    "task_due_date_field": "",
    "task_status_field": "",
    "last_project_id": None,
    # My Tasks: 브라우저에서 열 Canvas 페이지 ID (팀 페이지 기본값)
    "shot_browser_page_id": 14100,
    # 비어 있으면 자동 탐지; 필요 시 전체 경로 (또는 환경 변수 BPE_CHROME_PATH)
    "chrome_executable": "",
    # corporate HTTP proxy for ShotGrid + S3 uploads (shotgun_api3 Shotgun http_proxy); optional
    "http_proxy": "",
    # PEM path for Shotgun(ca_certs=...); empty = bundled bpe_sg_merged.pem if present
    "ca_certs": "",
}


def _studio_json_candidates() -> list:
    """Search order for the studio auto-config file."""
    paths: list = []
    env_path = os.environ.get("BPE_SHOTGRID_STUDIO_JSON", "").strip()
    if env_path:
        paths.append(Path(env_path).expanduser())
    try:
        if getattr(sys, "frozen", False):
            paths.append(Path(sys.executable).resolve().parent / "shotgrid_studio.json")
    except Exception:
        pass
    paths.append(cfg.APP_DIR / "shotgrid_studio.json")
    try:
        paths.append(Path(__file__).resolve().parents[3] / "shotgrid_studio.json")
    except Exception:
        pass
    return paths


def load_studio_dict() -> Dict[str, Any]:
    """Load shotgrid_studio.json from the first valid candidate path."""
    for path in _studio_json_candidates():
        try:
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                continue
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def studio_config_path_resolved() -> Optional[Path]:
    """Return the path to the first studio file with actual credentials, or None."""
    for path in _studio_json_candidates():
        try:
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                continue
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue
            if any(
                str(data.get(k, "") or "").strip()
                for k in ("base_url", "script_name", "script_key")
            ):
                return path.resolve()
        except Exception:
            continue
    return None


def get_shotgrid_settings(settings_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Merge ShotGrid settings in priority order:
      1) Built-in defaults
      2) shotgrid_studio.json
      3) settings.json "shotgrid" section (non-empty strings only)
      4) Environment variables (highest priority)
    """
    merged: Dict[str, Any] = {**_DEFAULT_SHOTGRID}

    # Layer 2: studio json
    studio = load_studio_dict()
    for k, v in studio.items():
        if k not in merged:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        merged[k] = v

    # Layer 3: settings.json
    settings = load_settings(settings_file)
    raw = settings.get("shotgrid")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k == "script_key" and isinstance(v, str) and not v.strip():
                continue
            if v is None:
                continue
            if isinstance(v, str) and not v.strip() and k != "last_project_id":
                continue
            merged[k] = v

    # Layer 4: environment variables
    url = os.environ.get("BPE_SHOTGRID_BASE_URL", "").strip()
    if url:
        merged["base_url"] = url
    sn = os.environ.get("BPE_SHOTGRID_SCRIPT_NAME", "").strip()
    if sn:
        merged["script_name"] = sn
    sk = os.environ.get("BPE_SHOTGRID_SCRIPT_KEY", "").strip()
    if sk:
        merged["script_key"] = sk
    hp = os.environ.get("BPE_SHOTGRID_HTTP_PROXY", "").strip()
    if hp:
        merged["http_proxy"] = hp
    cac = os.environ.get("BPE_SHOTGRID_CACERTS", "").strip()
    if cac:
        merged["ca_certs"] = cac

    return merged


def save_shotgrid_settings(partial: Dict[str, Any], settings_file: Optional[Path] = None) -> None:
    """Merge-save only the given keys into settings.json 'shotgrid' section."""
    settings = load_settings(settings_file)
    cur = settings.get("shotgrid")
    if not isinstance(cur, dict):
        cur = {}
    for k, v in partial.items():
        if k == "script_key" and isinstance(v, str) and not v.strip():
            continue
        cur[k] = v
    settings["shotgrid"] = {**_DEFAULT_SHOTGRID, **cur}
    save_settings(settings, settings_file)
