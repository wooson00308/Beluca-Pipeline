"""Parse Nuke .nk files to extract preset-compatible settings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_knob(text: str, knob: str) -> Optional[str]:
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


def _parse_format_name_from_root(rb: str) -> Optional[str]:
    """Last token of quoted or braced Root format line (e.g. plate, UHD)."""
    m = re.search(r'format\s+"([^"]*)"', rb)
    if m:
        parts = m.group(1).split()
        if len(parts) >= 7:
            return parts[-1].strip()
        if parts:
            return parts[-1].strip()
    m2 = re.search(r"format\s+\{([^}]*)\}", rb)
    if m2:
        parts = m2.group(1).split()
        if len(parts) >= 7:
            return parts[-1].strip()
        if parts:
            return parts[-1].strip()
    return None


def _collect_node_stats(content: str) -> Dict[str, Any]:
    """Count node types and collect Read/Write node names (review UI only)."""
    by_type: Dict[str, int] = {}
    for line in content.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\{", line)
        if m:
            t = m.group(1)
            by_type[t] = by_type.get(t, 0) + 1

    write_names: List[str] = []
    for wb in _extract_all_blocks(content, "Write"):
        nm = get_knob(wb, "name")
        if nm:
            write_names.append(nm)

    read_names: List[str] = []
    for rb in _extract_all_blocks(content, "Read"):
        nm = get_knob(rb, "name")
        if nm:
            read_names.append(nm)

    total = sum(by_type.values())
    return {
        "by_type": by_type,
        "write_names": write_names,
        "read_names": read_names,
        "total": total,
    }


def _pick_exr_write_block(all_writes: List[str]) -> Optional[str]:
    """Prefer Write2 / setup_pro_write with file_type exr, else first exr block."""
    exr_blocks: List[Tuple[str, str]] = []
    for wb in all_writes:
        nm = (get_knob(wb, "name") or "").strip()
        ft = (get_knob(wb, "file_type") or "exr").lower()
        if ft in ("mov", "mp4"):
            continue
        exr_blocks.append((nm, wb))

    if not exr_blocks:
        return None

    for prefer in ("Write2", "setup_pro_write"):
        for nm, inner in exr_blocks:
            if nm == prefer:
                return inner
    return exr_blocks[0][1]


def _pick_mov_write_block(all_writes: List[str]) -> Optional[str]:
    """First Write block with file_type mov or mp4."""
    for wb in all_writes:
        ft = (get_knob(wb, "file_type") or "").lower()
        if ft in ("mov", "mp4"):
            return wb
    return None


def parse_nk_file(nk_path: str) -> Dict[str, Any]:
    """
    Extract preset-compatible settings from an NK file.

    Handles nested ``{}`` and ``{value}`` formats correctly.

    Returns:
        Dict of detected settings. Includes ``_node_stats`` for review UI only.

    Raises:
        ValueError: when the file cannot be read.
    """
    try:
        content = Path(nk_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise ValueError(f"NK 파일을 읽지 못했습니다: {e}") from e

    result: Dict[str, Any] = {}
    result["_node_stats"] = _collect_node_stats(content)

    # --- Root block ---
    root_blocks = _extract_all_blocks(content, "Root")
    rb = root_blocks[0] if root_blocks else None
    if rb:
        fps = get_knob(rb, "fps")
        if fps:
            result["fps"] = fps
        for pat in (r'format "(\d+) (\d+)', r"format \{(\d+) (\d+)"):
            fmt_m = re.search(pat, rb)
            if fmt_m:
                result["plate_width"] = fmt_m.group(1)
                result["plate_height"] = fmt_m.group(2)
                break
        pfn = _parse_format_name_from_root(rb)
        if pfn:
            result["plate_format_name"] = pfn

        cm = get_knob(rb, "colorManagement")
        if cm:
            result["color_management"] = cm

        for nk_knob, key in [
            ("workingSpaceLUT", "working_space_lut"),
            ("monitorLut", "monitor_lut"),
            ("int8Lut", "int8_lut"),
            ("int16Lut", "int16_lut"),
            ("logLut", "log_lut"),
            ("floatLut", "float_lut"),
        ]:
            v = get_knob(rb, nk_knob)
            if v:
                result[key] = v
        ocio = get_knob(rb, "customOCIOConfigPath")
        if ocio:
            result["ocio_path"] = ocio.replace("\\\\", "\\").strip()

    # --- Viewer (first) ---
    viewer_blocks = _extract_all_blocks(content, "Viewer")
    if viewer_blocks:
        vp = get_knob(viewer_blocks[0], "viewerProcess")
        if vp:
            result["viewer_process"] = vp

    # --- Write blocks: EXR vs MOV ---
    all_writes = _extract_all_blocks(content, "Write")
    wb_exr = _pick_exr_write_block(all_writes)
    wb_mov = _pick_mov_write_block(all_writes)

    if wb_exr:
        result["write_enabled"] = True
        for knob, key in [
            ("channels", "write_channels"),
            ("compression", "write_compression"),
            ("metadata", "write_metadata"),
        ]:
            v = get_knob(wb_exr, knob)
            if v:
                result[key] = v
        file_type = get_knob(wb_exr, "file_type")
        # datatype: Nuke 기본값(16 bit half)은 NK에 저장 안 됨 → EXR이면 추론
        dt_val = get_knob(wb_exr, "datatype")
        if dt_val:
            result["write_datatype"] = dt_val
        elif file_type == "exr":
            result["write_datatype"] = "16 bit half"
        if file_type == "exr":
            dt = (result.get("write_datatype") or "").lower()
            result["delivery_format"] = (
                "EXR 32bit" if ("32" in dt or "float" in dt) else "EXR 16bit"
            )
        elif file_type in ("mov", "mp4"):
            result["delivery_format"] = "ProRes 422 HQ"
        ocio_cs = get_knob(wb_exr, "ocioColorspace")
        colorspace = get_knob(wb_exr, "colorspace")
        display = get_knob(wb_exr, "display")
        view = get_knob(wb_exr, "view")
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

    if wb_mov:
        codec = get_knob(wb_mov, "mov64_codec") or get_knob(wb_mov, "codec")
        if codec:
            result["mov_codec"] = codec
        profile = (
            get_knob(wb_mov, "mov64_codec_profile")
            or get_knob(wb_mov, "mov64_profile")
            or get_knob(wb_mov, "mov64_quality")
        )
        if profile:
            result["mov_profile"] = profile
        fps_mov = get_knob(wb_mov, "fps")
        if fps_mov:
            result["mov_fps"] = fps_mov
        ch_mov = get_knob(wb_mov, "channels")
        if ch_mov:
            result["mov_channels"] = ch_mov
        mcs = get_knob(wb_mov, "ocioColorspace") or get_knob(wb_mov, "colorspace")
        if mcs:
            result["mov_colorspace"] = mcs
        md = get_knob(wb_mov, "display")
        if md:
            result["mov_display"] = md
        mv = get_knob(wb_mov, "view")
        if mv:
            result["mov_view"] = mv

    if "delivery_format" not in result and wb_mov:
        result["delivery_format"] = "ProRes 422 HQ"

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
        cs = get_knob(rb_read, "colorspace")
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
    "color_management": "",
    "working_space_lut": "",
    "monitor_lut": "",
    "int8_lut": "",
    "int16_lut": "",
    "log_lut": "",
    "float_lut": "",
    "viewer_process": "",
    "mov_codec": "",
    "mov_profile": "",
    "mov_fps": "",
    "mov_channels": "",
    "mov_colorspace": "",
    "mov_display": "",
    "mov_view": "",
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


def merge_parsed_into_preset(
    parsed_fields: Dict[str, Any], preset_name: str = ""
) -> Dict[str, Any]:
    """
    Merge output of :func:`parse_nk_file` (with ``_node_stats`` already removed)
    into a full preset dict using :data:`_PRESET_DEFAULTS`.
    """
    data: Dict[str, Any] = {}
    for key, default in _PRESET_DEFAULTS.items():
        data[key] = parsed_fields.get(key, default)
    if "write_colorspace" not in parsed_fields:
        data["write_colorspace"] = data["write_out_colorspace"]
    if preset_name:
        data["project_code"] = preset_name
    return data


def parse_nk_for_preset(
    nk_path: str, preset_name: str = ""
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parse an NK file and return a complete preset dict with defaults filled in,
    plus node statistics for review UI.

    *preset_name* is written into ``project_code`` when provided.

    Returns:
        ``(preset_data, node_stats)`` — *node_stats* is empty if no file stats.

    Raises ``ValueError`` when the file cannot be read (propagated from
    :func:`parse_nk_file`).
    """
    parsed = parse_nk_file(nk_path)
    node_stats = parsed.pop("_node_stats", {})
    data = merge_parsed_into_preset(parsed, preset_name=preset_name)
    return data, node_stats


def merge_nk_preserve_root_template(old_nk: str, new_nk: str) -> str:
    """
    Keep the first ``Root`` block and everything before it from *old_nk*,
    append everything after the first ``Root`` block from *new_nk*.

    Used when replacing only the node tree while preserving project Root settings.
    """
    from bpe.core.nk_generator import _find_blocks_with_positions

    old_roots = _find_blocks_with_positions(old_nk, "Root")
    new_roots = _find_blocks_with_positions(new_nk, "Root")
    if not old_roots:
        raise ValueError("기존 NK에서 Root 블록을 찾을 수 없습니다.")
    if not new_roots:
        raise ValueError("새 NK에서 Root 블록을 찾을 수 없습니다.")
    _, end_old, _ = old_roots[0]
    _, end_new, _ = new_roots[0]
    return old_nk[:end_old] + new_nk[end_new:]


def merge_nodetree_content(old_template: str, new_content: str) -> str:
    """
    Replace or append node tree content after the first ``Root`` block.

    If *new_content* contains a ``Root`` block, use ``merge_nk_preserve_root_template``.
    Otherwise (e.g. Nuke Ctrl+C node copy with no Root), append after the first
    ``Root`` block of *old_template*.
    """
    from bpe.core.nk_generator import _find_blocks_with_positions

    new_roots = _find_blocks_with_positions(new_content, "Root")
    if new_roots:
        return merge_nk_preserve_root_template(old_template, new_content)
    old_roots = _find_blocks_with_positions(old_template, "Root")
    if not old_roots:
        raise ValueError("기존 NK 템플릿에서 Root 블록을 찾을 수 없습니다.")
    _, end_old, _ = old_roots[0]
    return old_template[:end_old] + "\n" + new_content.strip() + "\n"
