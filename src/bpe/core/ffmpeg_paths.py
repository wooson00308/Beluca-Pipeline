"""Resolve ffmpeg / ffprobe executables (PATH, env, PyInstaller bundle, exe dir)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _exe_name(base: str) -> str:
    if sys.platform == "win32":
        return f"{base}.exe"
    return base


def _is_usable_file(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _resolve_tool(base: str) -> Optional[str]:
    """ffmpeg / ffprobe: explicit env → BPE_FFMPEG_BIN → _MEIPASS → exe dir → PATH."""
    name = _exe_name(base)
    if base == "ffmpeg":
        explicit = os.environ.get("FFMPEG_PATH", "").strip()
    elif base == "ffprobe":
        explicit = os.environ.get("FFPROBE_PATH", "").strip()
    else:
        explicit = ""
    if explicit:
        ep = Path(explicit)
        if _is_usable_file(ep):
            return str(ep.resolve())

    bindir = os.environ.get("BPE_FFMPEG_BIN", "").strip()
    if bindir:
        bp = Path(bindir) / name
        if _is_usable_file(bp):
            return str(bp.resolve())

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            mp = Path(meipass) / name
            if _is_usable_file(mp):
                return str(mp.resolve())
        exedir = Path(sys.executable).resolve().parent
        ep = exedir / name
        if _is_usable_file(ep):
            return str(ep.resolve())

    return shutil.which(base)


def resolve_ffmpeg() -> Optional[str]:
    return _resolve_tool("ffmpeg")


def resolve_ffprobe() -> Optional[str]:
    return _resolve_tool("ffprobe")
