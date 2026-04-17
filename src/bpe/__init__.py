"""Beluca Pipeline Engine (BPE) - VFX Pipeline Desktop Tool."""

from __future__ import annotations

import sys
from pathlib import Path

from bpe.core.shotgun_python_api_path import prepend_studio_shotgun_api_if_available

prepend_studio_shotgun_api_if_available()


def _read_version() -> str:
    # PyInstaller 번들: sys._MEIPASS 루트에 VERSION.txt
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "VERSION.txt"
        if p.exists():
            return p.read_text().strip()
    # 소스 실행: 프로젝트 루트
    p = Path(__file__).resolve().parent.parent.parent / "VERSION.txt"
    if p.exists():
        return p.read_text().strip()
    return "0.0.0"


__version__ = _read_version()
