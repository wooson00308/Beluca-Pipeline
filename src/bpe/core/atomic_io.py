"""Atomic file I/O utilities — safe JSON read/write for shared/network folders."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically via temp-file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fp:
            fp.write(text)
        os.replace(str(tmp_path), str(path))
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def read_json_file(path: Path, default: T) -> T:  # type: ignore[type-var]
    """Read a JSON file, returning *default* on any failure."""
    try:
        if not path.exists():
            return default
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return default
        data = json.loads(raw)
        if isinstance(default, dict) and not isinstance(data, dict):
            return default
        if isinstance(default, list) and not isinstance(data, list):
            return default
        return data  # type: ignore[return-value]
    except Exception:
        return default


def write_json_file(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON via atomic write."""
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
