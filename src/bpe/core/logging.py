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

    # 번들: 샷그리드 모듈 로그를 exe 옆 파일에도 기록 (dits-test 등 공유 경로 수집용).
    if getattr(sys, "frozen", False):
        try:
            from bpe.core.feedback_file_log import feedback_log_dir

            sg_path = feedback_log_dir() / "bpe_shotgrid.log"
            sg_fh = logging.FileHandler(sg_path, encoding="utf-8", mode="w")
            sg_fh.setLevel(logging.DEBUG)
            sg_fh.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            sg_root = logging.getLogger("bpe.shotgrid")
            sg_root.setLevel(logging.DEBUG)
            sg_root.addHandler(sg_fh)
        except Exception:
            pass
