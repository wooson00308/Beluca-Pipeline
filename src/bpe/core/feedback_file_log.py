"""피드백 진단용 NDJSON 로그 — `bpe_feedback.log` (exe 옆 또는 cwd).

- ``append_feedback_log``: 항상 기록 (기존 영상 파이프라인 진단).
- ``append_feedback_log_verbose``: **기본값 ON** — 노트 제출·첨부 등 상세 이벤트.

끄려면 앱 시작 전에 다음 중 하나:

- ``BPE_FEEDBACK_DIAG_QUIET=1`` (또는 ``true`` / ``yes`` / ``on``)
- ``BPE_FEEDBACK_DIAG_VERBOSE=0`` (또는 ``false`` / ``no`` / ``off``)

꺼져 있을 때 ``append_feedback_log_verbose`` 는 즉시 반환(파일 미개방).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_CACHED_VERBOSE: Optional[bool] = None


def reset_feedback_diag_verbose_cache() -> None:
    """테스트에서 환경 변수를 바꾼 뒤 캐시를 비울 때만 사용."""
    global _CACHED_VERBOSE
    _CACHED_VERBOSE = None


def is_feedback_diag_verbose() -> bool:
    """상세 피드백 파일 로그 기본 ON. QUIET 또는 VERBOSE=0 으로 끔 (프로세스당 한 번 캐시)."""
    global _CACHED_VERBOSE
    if _CACHED_VERBOSE is None:
        quiet = (os.environ.get("BPE_FEEDBACK_DIAG_QUIET") or "").strip().lower()
        if quiet in ("1", "true", "yes", "on"):
            _CACHED_VERBOSE = False
        else:
            v = (os.environ.get("BPE_FEEDBACK_DIAG_VERBOSE") or "").strip().lower()
            if v in ("0", "false", "no", "off"):
                _CACHED_VERBOSE = False
            else:
                _CACHED_VERBOSE = True
    return bool(_CACHED_VERBOSE)


def feedback_log_dir() -> Path:
    """로그 파일을 둘 디렉터리 (번들: exe 옆).

    ``BPE_FEEDBACK_LOG_DIR`` 이 비어 있지 않으면 해당 경로를 우선한다 (exe 위치와 무관).
    """
    override = (os.environ.get("BPE_FEEDBACK_LOG_DIR") or "").strip()
    if override:
        p = Path(override).expanduser()
        try:
            p = p.resolve()
        except OSError:
            p = Path(override).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return p
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _write_line(event: str, **data: Any) -> None:
    try:
        line: Dict[str, Any] = {
            "ts_ms": int(time.time() * 1000),
            "event": event,
        }
        line.update(data)
        path = feedback_log_dir() / "bpe_feedback.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def append_feedback_log(event: str, **data: Any) -> None:
    """진단용 한 줄 JSON (경로·토큰·개인정보 넣지 말 것)."""
    _write_line(event, **data)


def append_feedback_log_verbose(event: str, **data: Any) -> None:
    """상세 진단 — QUIET/VERBOSE=0 이면 즉시 반환(파일 미개방)."""
    if not is_feedback_diag_verbose():
        return
    _write_line(event, **data)
