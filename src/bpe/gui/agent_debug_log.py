"""NDJSON debug log for agent sessions. Next to exe if frozen, else repo root."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict


def append_agent_ndjson(payload: Dict[str, Any], *, session_id: str = "e2b966") -> None:
    try:
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).parent
        else:
            root = Path(__file__).resolve().parents[3]
        log_path = root / f"debug-{session_id}.log"
        line = {
            "sessionId": session_id,
            "timestamp": int(time.time() * 1000),
            **payload,
        }
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass
