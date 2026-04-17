"""Resolve path to merged CA bundle for shotgun_api3 Shotgun(ca_certs=...)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_BUNDLE_NAME = "bpe_sg_merged.pem"


def _bundled_merged_pem_path() -> Optional[Path]:
    """Path to packaged bpe_sg_merged.pem (certifi + enterprise CA), if present."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "bpe" / "resources" / "shotgrid" / _BUNDLE_NAME
            if p.is_file():
                return p
    # Dev / source: this file is bpe/core/shotgrid_ca_bundle.py
    pkg = Path(__file__).resolve().parent.parent / "resources" / "shotgrid" / _BUNDLE_NAME
    if pkg.is_file():
        return pkg
    return None


def resolve_shotgun_ca_certs_path(merged_settings: Dict[str, Any]) -> Optional[str]:
    """
    PEM path for Shotgun(ca_certs=...). API and uploads use the same bundle (shotgun_api3).

    Priority:
      1) Opt-out: BPE_SHOTGRID_NO_EXTRA_CA — pass None (Shotgun uses default / SHOTGUN_API_CACERTS)
      2) merged_settings['ca_certs'] — settings.json / studio / BPE_SHOTGRID_CACERTS env (via merge)
      3) Bundled bpe/resources/shotgrid/bpe_sg_merged.pem if file exists
      4) None
    """
    flag = (os.environ.get("BPE_SHOTGRID_NO_EXTRA_CA") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return None

    raw = (str(merged_settings.get("ca_certs") or "")).strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return str(p.resolve())

    bundled = _bundled_merged_pem_path()
    if bundled is not None:
        return str(bundled.resolve())
    return None
