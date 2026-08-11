# @cursor-change: 2026-08-09, 0.13.x, handoff send_id/consumed (Nuke 자동 팝업용)
"""BPE → Nuke 핸드오프 JSON.

클립보드 Tcl 붙여넣기가 한글 경로에서 실패할 때를 위한.
원본 미디어는 건드리지 않고 ``~/.setup_pro/cache/library_handoff.json`` 만 쓴다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import bpe.core.config as cfg
from bpe.core.atomic_io import read_json_file, write_json_file
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.source_library_scan import KIND_SEQUENCE, row_pattern_path


def handoff_path() -> Path:
    return cfg.CACHE_DIR / "library_handoff.json"


def write_handoff(rows: Sequence[Dict[str, Any]]) -> Path:
    """선택 항목들을 핸드오프 파일에 기록한다 (새 send_id)."""
    items: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        path = normalize_path_str(row_pattern_path(row))
        entry: Dict[str, Any] = {
            "path": path,
            "kind": kind,
            "name": str(row.get("name") or ""),
        }
        if kind == KIND_SEQUENCE:
            first = int(row.get("frame_first") or 0)
            last = int(row.get("frame_last") or first)
            if last < first:
                first, last = last, first
            entry["first"] = first
            entry["last"] = last
        items.append(entry)
    payload = {
        "version": 1,
        "send_id": str(uuid.uuid4()),
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "consumed": False,
        "items": items,
    }
    path = handoff_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, payload)
    return path


def read_handoff_payload() -> Dict[str, Any]:
    """전체 handoff dict. 없거나 깨지면 빈 dict."""
    data = read_json_file(handoff_path(), {})
    return data if isinstance(data, dict) else {}


def read_handoff() -> List[Dict[str, Any]]:
    data = read_handoff_payload()
    items = data.get("items")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and str(it.get("path") or "").strip():
            out.append(dict(it))
    return out


def handoff_send_id(data: Optional[Dict[str, Any]] = None) -> str:
    raw = data if data is not None else read_handoff_payload()
    return str(raw.get("send_id") or "").strip()


def handoff_is_consumed(data: Optional[Dict[str, Any]] = None) -> bool:
    raw = data if data is not None else read_handoff_payload()
    return bool(raw.get("consumed"))


def mark_handoff_consumed() -> None:
    """Yes/No 처리 후 같은 전송이 다시 뜨지 않게 표시."""
    data = read_handoff_payload()
    if not data:
        return
    data["consumed"] = True
    path = handoff_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, data)
