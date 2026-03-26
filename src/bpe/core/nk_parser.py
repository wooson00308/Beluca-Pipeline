"""Parse Nuke .nk files to extract preset-compatible settings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_knob(text: str, knob: str) -> Optional[str]:
    """
    Extract a knob value supporting three NK formats:
      knob "value"  /  knob {value}  /  knob value
    """
    m = re.search(rf'(?:^|\s){re.escape(knob)} "([^"]*)"', text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(rf"(?:^|\s){re.escape(knob)} \{{([^}}]*)\}}", text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(rf'(?:^|\s){re.escape(knob)} ([^\s"{{][^\s]*)', text, re.MULTILINE)
    if m:
        return m.group(1)
    return None


def _extract_all_blocks(content: str, node_type: str) -> List[str]:
    """Extract inner text of all blocks of *node_type* tracking nested ``{}``."""
    blocks: List[str] = []
    pattern = re.compile(rf"(?:^|\n){re.escape(node_type)} \{{", re.MULTILINE)
    for m in pattern.finditer(content):
        start = m.end()
        depth = 1
        i = start
        while i < len(content) and depth > 0:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        if depth == 0:
            blocks.append(content[start : i - 1])
    return blocks


def _find_named_block(content: str, node_type: str, node_name: str) -> Optional[str]:
    """Return the inner text of the first block whose ``name`` knob matches."""
    name_re = re.compile(rf"(?:^|\s)name {re.escape(node_name)}\s*(?:\n|$)", re.MULTILINE)
    for block in _extract_all_blocks(content, node_type):
        if name_re.search(block):
            return block
    return None


def parse_nk_file(nk_path: str) -> Dict[str, Any]:
    """
    Extract preset-compatible settings from an NK file.

    Handles nested ``{}`` and ``{value}`` formats correctly.

    Returns:
        Dict of detected settings (missing items are omitted).

    Raises:
        ValueError: when the file cannot be read.
    """
    try:
        content = Path(nk_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise ValueError(f"NK 파일을 읽지 못했습니다: {e}") from e

    result: Dict[str, Any] = {}

    # --- Root block ---
    root_blocks = _extract_all_blocks(content, "Root")
    rb = root_blocks[0] if root_blocks else None
    if rb:
        fps = _get_knob(rb, "fps")
        if fps:
            result["fps"] = fps
        for pat in (r'format "(\d+) (\d+)', r"format \{(\d+) (\d+)"):
            fmt_m = re.search(pat, rb)
            if fmt_m:
                result["plate_width"] = fmt_m.group(1)
                result["plate_height"] = fmt_m.group(2)
                break
        ocio = _get_knob(rb, "customOCIOConfigPath")
        if ocio:
            result["ocio_path"] = ocio.replace("\\\\", "\\").strip()

    # --- Write block ---
    wb = _find_named_block(content, "Write", "Write2") or _find_named_block(
        content, "Write", "setup_pro_write"
    )
    if not wb:
        all_writes = _extract_all_blocks(content, "Write")
        wb = all_writes[0] if all_writes else None
    if wb:
        result["write_enabled"] = True
        for knob, key in [
            ("channels", "write_channels"),
            ("datatype", "write_datatype"),
            ("compression", "write_compression"),
            ("metadata", "write_metadata"),
        ]:
            v = _get_knob(wb, knob)
            if v:
                result[key] = v
        file_type = _get_knob(wb, "file_type")
        if file_type == "exr":
            dt = (result.get("write_datatype") or "").lower()
            result["delivery_format"] = (
                "EXR 32bit" if ("32" in dt or "float" in dt) else "EXR 16bit"
            )
        elif file_type in ("mov", "mp4"):
            result["delivery_format"] = "ProRes 422 HQ"
        ocio_cs = _get_knob(wb, "ocioColorspace")
        colorspace = _get_knob(wb, "colorspace")
        display = _get_knob(wb, "display")
        view = _get_knob(wb, "view")
        if ocio_cs:
            result["write_out_colorspace"] = ocio_cs
            result["write_colorspace"] = ocio_cs
        elif colorspace:
            result["write_out_colorspace"] = colorspace
            result["write_colorspace"] = colorspace
        if display:
            result["write_output_display"] = display
        if view:
            result["write_output_view"] = view
        if ocio_cs or (colorspace and colorspace not in ("scene_linear", "")):
            result["write_transform_type"] = "colorspace"
        elif display and view:
            result["write_transform_type"] = "display/view"

    # --- Read block ---
    rb_read = (
        _find_named_block(content, "Read", "Read4")
        or _find_named_block(content, "Read", "Read_Plate")
        or _find_named_block(content, "Read", "Read5")
    )
    if not rb_read:
        all_reads = _extract_all_blocks(content, "Read")
        rb_read = all_reads[0] if all_reads else None
    if rb_read:
        cs = _get_knob(rb_read, "colorspace")
        if cs:
            result["read_input_transform"] = cs

    return result


# Default values used when NK analysis misses a field.
_PRESET_DEFAULTS: Dict[str, Any] = {
    "project_type": "드라마(OTT)",
    "project_code": "",
    "delivery_format": "EXR 16bit",
    "fps": "23.976",
    "plate_format_choice": "(직접입력)",
    "plate_format_name": "",
    "plate_width": "1920",
    "plate_height": "1080",
    "ocio_path": "",
    "write_enabled": True,
    "write_channels": "all",
    "write_datatype": "16 bit half",
    "write_compression": "PIZ Wavelet (32 scanlines)",
    "write_metadata": "all metadata",
    "write_transform_type": "colorspace",
    "write_out_colorspace": "ACES - ACES2065-1",
    "write_output_display": "ACES",
    "write_output_view": "Rec.709",
    "write_colorspace": "ACES - ACES2065-1",
    "read_input_transform": "ACES - ACES2065-1",
}


def parse_nk_for_preset(nk_path: str, preset_name: str = "") -> Dict[str, Any]:
    """
    Parse an NK file and return a complete preset dict with defaults filled in.

    *preset_name* is written into ``project_code`` when provided.

    Raises ``ValueError`` when the file cannot be read (propagated from
    :func:`parse_nk_file`).
    """
    parsed = parse_nk_file(nk_path)
    data: Dict[str, Any] = {}
    for key, default in _PRESET_DEFAULTS.items():
        data[key] = parsed.get(key, default)
    # write_colorspace falls back to write_out_colorspace when not explicitly set
    if "write_colorspace" not in parsed:
        data["write_colorspace"] = data["write_out_colorspace"]
    if preset_name:
        data["project_code"] = preset_name
    return data
