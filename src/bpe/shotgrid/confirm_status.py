"""샷그리드에 정해 둔 상태(Status)별 이름·색·아이콘 읽기 — 컨펌 창이 같은 모양으로 보여 주려고."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict, List, Optional, Sequence

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.confirm_status")

_CHUNK = 100


def _hex_color(value: Any) -> str:
    """샷그리드의 ``"29,215,46"`` → ``"#1dd72e"``. 못 읽으면 빈 글."""
    parts = str(value or "").split(",")
    if len(parts) != 3:
        return ""
    try:
        r, g, b = (max(0, min(255, int(p.strip()))) for p in parts)
    except ValueError:
        return ""
    return f"#{r:02x}{g:02x}{b:02x}"


def _png_bytes(value: Any) -> bytes:
    """아이콘의 ``image_data``(base64 PNG). 없거나 깨졌으면 빈 바이트."""
    text = "".join(str(value or "").split())
    if not text or text == "None":
        return b""
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return b""


def fetch_status_styles(
    sg: Any, codes: Optional[Sequence[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """상태 코드 → ``{"name", "color", "icon_png", "icon_key"}``.

    ``color`` 는 ``#rrggbb``(없으면 빈 글), ``icon_png`` 는 올려 둔 아이콘 그림(없으면 빈 바이트),
    ``icon_key`` 는 샷그리드 기본 아이콘의 이름(예: ``icon_undo``).
    """
    want = {c.strip().lower() for c in codes} if codes else None
    rows = sg.find("Status", [], ["code", "name", "bg_color", "icon"]) or []
    out: Dict[str, Dict[str, Any]] = {}
    icon_of: Dict[str, int] = {}
    for r in rows:
        code = str(r.get("code") or "").strip().lower()
        if not code or (want is not None and code not in want):
            continue
        out[code] = {
            "name": str(r.get("name") or "").strip(),
            "color": _hex_color(r.get("bg_color")),
            "icon_png": b"",
            "icon_key": "",
        }
        icon = r.get("icon")
        if isinstance(icon, dict) and icon.get("id") is not None:
            icon_of[code] = int(icon["id"])
    ids: List[int] = sorted(set(icon_of.values()))
    icons: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(ids), _CHUNK):
        try:
            found = sg.find(
                "Icon", [["id", "in", ids[i : i + _CHUNK]]], ["image_data", "image_map_key"]
            )
        except Exception as e:  # 아이콘을 못 읽어도 이름·색은 쓴다
            logger.warning("confirm status: icon lookup failed: %s", e)
            break
        for ic in found or []:
            icons[int(ic["id"])] = ic
    for code, icon_id in icon_of.items():
        ic = icons.get(icon_id)
        if ic is None:
            continue
        out[code]["icon_png"] = _png_bytes(ic.get("image_data"))
        key = str(ic.get("image_map_key") or "").strip()
        out[code]["icon_key"] = "" if key == "None" else key
    return out
