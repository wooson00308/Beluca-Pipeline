"""ShotGrid 파일 업로드(sg.upload) 진단 — shotgun_api3/urllib DEBUG 파일 로그 및 경로 메타.

켜기:

- ``BPE_SHOTGUN_UPLOAD_TRACE=1`` — ``shotgun_upload_trace.log`` 에 shotgun_api3·
  urllib3.connectionpool DEBUG, 실패 시 NDJSON에 traceback 전체(상한 있음).
- **PyInstaller 번들** 이고 실행 파일명이 ``BPE_dev.exe`` 이면 위 트레이스를 **기본 켬**
  (``BPE_SHOTGUN_UPLOAD_TRACE=0`` 등으로 끔).

``shotgun_upload_trace.log`` 경로는 ``feedback_log_dir()`` 와 동일 — 번들이면 exe 옆,
또는 ``BPE_FEEDBACK_LOG_DIR`` 로 덮어쓸 수 있음.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from bpe.core.feedback_file_log import feedback_log_dir

_TRACE_LOGGERS_CONFIGURED = False
_SHARED_HANDLER: Optional[logging.Handler] = None


def is_shotgun_upload_trace_enabled() -> bool:
    v = (os.environ.get("BPE_SHOTGUN_UPLOAD_TRACE") or "").strip().lower()
    if v in ("0", "false", "no", "off", "n"):
        return False
    if v in ("1", "true", "yes", "on", "y"):
        return True
    if getattr(sys, "frozen", False):
        try:
            if Path(sys.executable).resolve().name.lower() == "bpe_dev.exe":
                return True
        except OSError:
            pass
    return False


def ensure_shotgun_upload_trace_logging_configured() -> None:
    """환경 변수가 켜져 있을 때만, 한 번만 FileHandler 부착."""
    global _TRACE_LOGGERS_CONFIGURED, _SHARED_HANDLER
    if _TRACE_LOGGERS_CONFIGURED:
        return
    if not is_shotgun_upload_trace_enabled():
        return
    try:
        path = feedback_log_dir() / "shotgun_upload_trace.log"
        _SHARED_HANDLER = logging.FileHandler(path, encoding="utf-8")
        _SHARED_HANDLER.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        for name in ("shotgun_api3", "urllib3.connectionpool"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(_SHARED_HANDLER)
    except OSError:
        return
    _TRACE_LOGGERS_CONFIGURED = True


def upload_source_path_meta(local_path: str) -> Dict[str, Any]:
    """전체 경로 대신 파일명·크기만 (UNC 노출 최소화)."""
    out: Dict[str, Any] = {"path_basename": Path((local_path or "").strip()).name}
    try:
        p = Path(local_path)
        out["exists"] = p.is_file()
        if out["exists"]:
            out["size_bytes"] = int(p.stat().st_size)
    except OSError as exc:
        out["stat_err"] = type(exc).__name__
    return out


def exception_trace_preview(exc: BaseException, *, max_len: int = 12000) -> str:
    """실패 업로드 예외의 전체 스택(진단용, 길이 상한)."""
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    s = "".join(lines).replace("\r", "").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len] + "\n...[traceback truncated]"
