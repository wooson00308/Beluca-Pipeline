"""Unified logging for BPE — replaces the 3 fragmented debug-log systems."""

from __future__ import annotations

import logging
import sys

from bpe.core.config import APP_DIR

_LOG_FILE = APP_DIR / "bpe.log"
_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a named logger under the ``bpe`` hierarchy."""
    _ensure_configured()
    return logging.getLogger(f"bpe.{name}")


def _ensure_configured() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    APP_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("bpe")
    root.setLevel(logging.DEBUG)

    # File handler — rotated manually if needed; keeps last run
    try:
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8", mode="w")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(fh)
    except Exception:
        pass

    # Console handler — INFO and above
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)-5s %(message)s"))
    root.addHandler(ch)
