"""Generate and patch Nuke .nk script content from presets."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bpe.core.presets import load_preset_template

# Template sample values used for path/name substitution
_TEMPLATE_SAMPLE_SHOT_ROOT = "W:/vfx/project_2026/SBS_030/04_sq/E107/E107_S022_0080"
_TEMPLATE_SAMPLE_SHOT_NAME = "E107_S022_0080"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _to_nk_path(p: Any) -> str:
    """Convert a path to forward-slash NK format."""
    return str(p).replace("\\", "/")


def _nk_escape_quotes(s: str) -> str:
    """Escape backslashes and double-quotes for NK string literals."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Block / knob manipulation
# ---------------------------------------------------------------------------


def _find_blocks_with_positions(content: str, node_type: str) -> List[Tuple[int, int, str]]:
    """
    Find all blocks of *node_type* in NK content, tracking nested ``{}``.

    Returns:
        list of ``(start, end, inner)`` where *start*/*end* are character
        offsets in *content* and *inner* is the text between the braces.
    """
    results: List[Tuple[int, int, str]] = []
    pattern = re.compile(rf"(?:^|\n)({re.escape(node_type)} \{{)", re.MULTILINE)
    for m in pattern.finditer(content):
        group_start = m.start(1)
        inner_start = m.end()
        depth = 1
        i = inner_start
        while i < len(content) and depth > 0:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        if depth == 0:
            results.append((group_start, i, content[inner_start : i - 1]))
    return results


def _replace_knob_in_block(inner: str, knob_name: str, new_value: str) -> str:
    """
    Replace a knob value inside a block's inner text.

    Handles quoted / braced / bare-token NK formats.
    Returns *inner* unchanged if the knob is not found.
    """
    escaped = _nk_escape_quotes(new_value)
    kn = re.escape(knob_name)

    # Format 1: ' knob "value"'
    result, n = re.subn(
        rf'^( {kn} )"[^"]*"',
        rf'\1"{escaped}"',
        inner,
        flags=re.MULTILINE,
    )
    if n:
        return result

    # Format 2: ' knob {value}'
    result, n = re.subn(
        rf"^( {kn} )\{{[^}}]*\}}",
        rf'\1"{escaped}"',
        inner,
        flags=re.MULTILINE,
    )
    if n:
        return result

    # Format 3: ' knob token'
    result, n = re.subn(
        rf'^( {kn} )([^\s"{{][^\s]*)',
        rf'\1"{escaped}"',
        inner,
        flags=re.MULTILINE,
    )
    if n:
        return result

    return inner


# ---------------------------------------------------------------------------
# Template path resolution
# ---------------------------------------------------------------------------


def get_shot_node_template_path() -> Optional[Path]:
    """Locate ``shot_node_template.nk`` (PyInstaller or dev layout)."""
    candidates: list[Path] = []
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "shot_node_template.nk")
    except Exception:
        pass
    # Dev layout: templates/ dir at project root
    candidates.append(
        Path(__file__).resolve().parent.parent.parent.parent / "templates" / "shot_node_template.nk"
    )
    # Legacy: next to this file
    candidates.append(Path(__file__).resolve().parent / "shot_node_template.nk")
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Preset helpers
# ---------------------------------------------------------------------------


def _preset_datatype_string(preset_data: Dict[str, Any]) -> str:
    dt_raw = preset_data.get("write_datatype", "16 bit half") or "16 bit half"
    if "32" in dt_raw:
        return "32 bit float"
    if "integer" in dt_raw.lower():
        return "8 bit fixed"
    return "16 bit half"


def _preset_first_part(preset_data: Dict[str, Any]) -> str:
    ch = (preset_data.get("write_channels") or "all").strip().lower()
    if ch == "rgb":
        return "rgb"
    return "rgba"


# ---------------------------------------------------------------------------
# Patch functions
# ---------------------------------------------------------------------------


def _patch_read_colorspace(body: str, colorspace: str) -> str:
    """Replace the colorspace knob on Read nodes (Read4, Read5, etc.)."""
    if not colorspace:
        return body

    blocks = _find_blocks_with_positions(body, "Read")
    if not blocks:
        escaped_cs = _nk_escape_quotes(colorspace)
        return re.sub(
            r'( colorspace )"[^"]*"\n( name Read[\w\d_]+\n)',
            rf'\1"{escaped_cs}"\n\2',
            body,
        )

    result = body
    for start, end, inner in reversed(blocks):
        if not re.search(r"(?m)^ name Read[\w\d_]+\s*$", inner):
            continue
        new_inner = _replace_knob_in_block(inner, "colorspace", colorspace)
        if new_inner != inner:
            result = result[:start] + f"Read {{{new_inner}}}" + result[end:]

    return result


def _patch_write2_from_preset(body: str, preset_data: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Patch the main EXR Write2 node with preset compression/metadata/datatype/
    channels/OCIO settings.

    Returns ``(new_body, success)``.
    """
    comp_raw = preset_data.get("write_compression", "PIZ Wavelet (32 scanlines)") or ""
    meta_raw = preset_data.get("write_metadata", "all metadata") or ""
    datatype_val = _preset_datatype_string(preset_data)
    first_part = _preset_first_part(preset_data)

    tt = (
        (preset_data.get("write_transform_type") or "colorspace")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("\\", "/")
    )
    out_cs = _nk_escape_quotes(
        preset_data.get("write_out_colorspace", "ACES - ACES2065-1") or "ACES - ACES2065-1"
    )
    disp = (preset_data.get("write_output_display", "ACES") or "ACES").strip()
    view = (preset_data.get("write_output_view", "Rec.709") or "Rec.709").strip()

    def _knob_line_token(val: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", val):
            return val
        return f'"{_nk_escape_quotes(val)}"'

    # Build colorspace / ocio lines
    if tt == "colorspace":
        cs_line = f' colorspace "{out_cs}"'
        ocio_line = f' ocioColorspace "{out_cs}"'
    elif tt == "display/view":
        cs_line = " colorspace scene_linear"
        ocio_line = f' ocioColorspace "{out_cs}"'
    else:
        cs_line = " colorspace scene_linear"
        ocio_line = ' ocioColorspace "ACES - ACEScg"'

    disp_line = f" display {_knob_line_token(disp)}"
    view_line = f" view {_knob_line_token(view)}"

    # --- Block-based patching ---
    write_blocks = _find_blocks_with_positions(body, "Write")
    write2 = None
    for blk in write_blocks:
        blk_start, blk_end, inner = blk
        if re.search(r"(?m)^ name Write2\s*$", inner):
            write2 = blk
            break

    if write2 is not None:
        blk_start, blk_end, inner = write2

        file_m = re.search(r'(?m)^( file (?:"[^"]*"|\{[^}]*\}|\S+))', inner)
        file_line = (file_m.group(1) + "\n") if file_m else " file placeholder.####.exr\n"

        autocrop_m = re.search(r"(?m)^( autocrop [^\n]+)", inner)
        autocrop_line = (autocrop_m.group(1) + "\n") if autocrop_m else " autocrop true\n"

        ver_m = re.search(r"(?m)^( version \d+)", inner)
        ver_line = (ver_m.group(1) + "\n") if ver_m else " version 1\n"

        inputs_m = re.search(r"(?m)^( inputs \d+)", inner)
        inputs_line = (inputs_m.group(1) + "\n") if inputs_m else ""

        after_m = re.search(r"(?m)^ name Write2\s*\n([\s\S]*)", inner)
        after_name = after_m.group(1) if after_m else ""

        new_inner = (
            "\n"
            + inputs_line
            + file_line
            + " file_type exr\n"
            + autocrop_line
            + f' compression "{_nk_escape_quotes(comp_raw)}"\n'
            + f' metadata "{_nk_escape_quotes(meta_raw)}"\n'
            + f' datatype "{_nk_escape_quotes(datatype_val)}"\n'
            + f" first_part {first_part}\n"
            + cs_line
            + "\n"
            + ver_line
            + ocio_line
            + "\n"
            + disp_line
            + "\n"
            + view_line
            + "\n"
            + " name Write2\n"
            + after_name
        )
        new_body = body[:blk_start] + f"Write {{{new_inner}}}" + body[blk_end:]
        return new_body, True

    # --- Regex fallback ---
    pattern = re.compile(
        r'(Write \{\n file "[^"]+"\n file_type exr\n autocrop true\n)'
        r"(?P<pre>(?:(?! name Write2\n).)*?)"
        r" name Write2\n",
        re.MULTILINE | re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        head = m.group(1)
        pre_text = m.group("pre")
        ver_m2 = re.search(r" version (\d+)\n", pre_text)
        ver_line2 = f" version {ver_m2.group(1)}\n" if ver_m2 else " version 1\n"
        return (
            head
            + f' compression "{_nk_escape_quotes(comp_raw)}"\n'
            + f' metadata "{_nk_escape_quotes(meta_raw)}"\n'
            + f' datatype "{_nk_escape_quotes(datatype_val)}"\n'
            + f" first_part {first_part}\n"
            + cs_line
            + "\n"
            + ver_line2
            + ocio_line
            + "\n"
            + disp_line
            + "\n"
            + view_line
            + "\n name Write2\n"
        )

    new_body, n = pattern.subn(repl, body, count=1)
    return (new_body, True) if n else (body, False)


def _patch_eo7_mov_write(body: str, preset_data: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Patch the preview MOV Write node (eo7Write1) with display/view/ocio
    settings from the preset.

    Returns ``(new_body, success)``.
    """
    tt = (
        (preset_data.get("write_transform_type") or "colorspace")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("\\", "/")
    )
    disp = (preset_data.get("write_output_display", "ACES") or "ACES").strip()
    view = (preset_data.get("write_output_view", "Rec.709") or "Rec.709").strip()

    def _knob_line_token(val: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", val):
            return val
        return f'"{_nk_escape_quotes(val)}"'

    if tt == "colorspace":
        ocio_value = (
            preset_data.get("write_out_colorspace", "ACES - ACEScg") or "ACES - ACEScg"
        ).strip()
    else:
        ocio_value = "ACES - ACEScg"

    ocio_line = f' ocioColorspace "{_nk_escape_quotes(ocio_value)}"'
    disp_tok = _knob_line_token(disp)
    view_tok = _knob_line_token(view)

    new_tail_lines = f"{ocio_line}\n display {disp_tok}\n view {view_tok}\n name eo7Write1\n"

    # 1st: exact string match
    old_tail = ' ocioColorspace "ACES - ACEScg"\n display ACES\n view Rec.709\n name eo7Write1\n'
    if old_tail in body:
        return body.replace(old_tail, new_tail_lines, 1), True

    # 2nd: regex fallback
    eo7_pattern = re.compile(
        r'( ocioColorspace "[^"]*"\n'
        r" display [^\n]+\n"
        r" view [^\n]+\n"
        r" name eo7Write1\n)",
        re.MULTILINE,
    )
    new_body, n = eo7_pattern.subn(new_tail_lines, body, count=1)
    if n:
        return new_body, True

    # 3rd: block-based
    write_blocks = _find_blocks_with_positions(body, "Write")
    eo7 = None
    for blk in write_blocks:
        blk_start, blk_end, inner = blk
        if re.search(r"(?m)^ name eo7Write1\s*$", inner):
            eo7 = blk
            break

    if eo7 is None:
        return body, False

    blk_start, blk_end, inner = eo7
    new_inner = _replace_knob_in_block(inner, "ocioColorspace", ocio_value)
    new_inner = _replace_knob_in_block(new_inner, "display", disp)
    new_inner = _replace_knob_in_block(new_inner, "view", view)
    new_body = body[:blk_start] + f"Write {{{new_inner}}}" + body[blk_end:]
    return new_body, True


def _patch_viewer_fps(body: str, fps: str) -> str:
    """Replace the fps value in the Viewer node."""
    return re.sub(
        r"(Viewer \{\n frame_range [^\n]+\n fps )([\d.]+)",
        rf"\g<1>{fps}",
        body,
        count=1,
    )


# ---------------------------------------------------------------------------
# Minimal NK (fallback when no template exists)
# ---------------------------------------------------------------------------


def _generate_nk_minimal(
    preset_data: Dict[str, Any],
    shot_name: str,
    paths: Dict[str, Path],
    nk_version: str,
) -> str:
    """Generate a bare-bones .nk when no template is available."""
    fps = preset_data.get("fps", "23.976")
    width = int(float(preset_data.get("plate_width", 1920)))
    height = int(float(preset_data.get("plate_height", 1080)))
    ocio_path = (preset_data.get("ocio_path", "") or "").replace("\\", "/")
    format_name = f"SP_{width}x{height}"
    plate_file = f"{_to_nk_path(paths['plate_hi'])}/{shot_name}.####.exr"
    edit_file = f"{_to_nk_path(paths['edit'])}/{shot_name}_edit.####.exr"
    delivery_fmt = (preset_data.get("delivery_format", "EXR 16bit") or "EXR 16bit").upper()
    if "EXR" in delivery_fmt:
        write_file_type, write_ext = "exr", "exr"
    elif "PRORES" in delivery_fmt or "DNXHR" in delivery_fmt:
        write_file_type, write_ext = "mov", "mov"
    else:
        write_file_type, write_ext = "exr", "exr"
    write_file = f"{_to_nk_path(paths['renders'])}/{shot_name}_comp_{nk_version}.####.{write_ext}"
    channels = preset_data.get("write_channels", "all") or "all"
    datatype_val = _preset_datatype_string(preset_data)
    comp_raw = preset_data.get("write_compression", "PIZ Wavelet (32 scanlines)") or ""
    comp_map = {
        "none": "none",
        "ZIP (single line)": "Zip (1 scanline)",
        "ZIP (block of 16 scanlines)": "Zip (16 scanlines)",
        "RLE": "RLE",
        "PIZ Wavelet (32 scanlines)": "PIZ Wavelet",
        "PXR24 (lossy)": "PXR24 (lossy)",
        "B44 (lossy)": "B44 (lossy)",
        "B44A (lossy)": "B44A (lossy)",
        "DWAA (lossy)": "DWAA (lossy)",
        "DWAB (lossy)": "DWAB (lossy)",
    }
    comp_val = comp_map.get(comp_raw, "PIZ Wavelet")
    metadata_raw = preset_data.get("write_metadata", "all metadata") or "all metadata"
    fmt_str = f"{width} {height} 0 0 {width} {height} 1 {format_name}"
    lines = [
        "set cut_paste_input [stack 0]",
        "version 14.1 v4",
        "Root {",
        " inputs 0",
        f" fps {fps}",
        f' format "{fmt_str}"',
        *(
            [
                " colorManagement OCIO",
                " OCIO_config custom",
                f' customOCIOConfigPath "{ocio_path}"',
            ]
            if ocio_path
            else []
        ),
        "}",
        "Read {",
        " inputs 0",
        " file_type exr",
        f" file {plate_file}",
        f" colorspace {(preset_data.get('read_input_transform') or 'scene_linear').strip()}",
        " name Read_Plate",
        " xpos -300",
        " ypos -400",
        "}",
        "set cut_paste_input [stack 0]",
        "Viewer {",
        " inputs 1",
        " name Viewer1",
        " xpos -300",
        " ypos -300",
        "}",
        "push $cut_paste_input",
        "Write {",
        " inputs 1",
        f" file {write_file}",
        f" file_type {write_file_type}",
        f" channels {channels}",
        f' datatype "{datatype_val}"',
        f' compression "{comp_val}"',
        f' metadata "{metadata_raw}"',
        " name setup_pro_write",
        " xpos -300",
        " ypos -200",
        "}",
        "Read {",
        " inputs 0",
        " file_type exr",
        f" file {edit_file}",
        " colorspace scene_linear",
        " name Read_Edit",
        " xpos 100",
        " ypos -400",
        "}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_nk_content(
    preset_data: Dict[str, Any],
    shot_name: str,
    paths: Dict[str, Path],
    nk_version: str,
) -> Tuple[str, List[str]]:
    """
    Build a full .nk script from a template + preset data.

    Uses ``shot_node_template.nk`` (team default node tree) with Root (preset)
    + path/Write/Viewer patches.  Falls back to a minimal graph when no
    template is found.

    Returns:
        ``(nk_content, warnings)`` — *warnings* lists any patch failures.
    """
    warnings: List[str] = []

    preset_name = (preset_data.get("project_code") or "").strip().upper()
    custom_body = load_preset_template(preset_name) if preset_name else None
    if custom_body:
        body = custom_body
    else:
        tpl_path = get_shot_node_template_path()
        if tpl_path is None:
            return _generate_nk_minimal(preset_data, shot_name, paths, nk_version), [
                "⚠ shot_node_template.nk 를 찾지 못해 최소 NK로 생성되었습니다."
            ]
        body = tpl_path.read_text(encoding="utf-8", errors="replace")

    shot_root_norm = _to_nk_path(paths["shot_root"])
    body = body.replace(_TEMPLATE_SAMPLE_SHOT_ROOT, shot_root_norm)
    body = body.replace(_TEMPLATE_SAMPLE_SHOT_ROOT.replace("/", "\\"), shot_root_norm)
    body = body.replace(_TEMPLATE_SAMPLE_SHOT_NAME, shot_name)
    # Fix legacy typo paths
    body = body.replace("/palte/", "/plate/")
    body = body.replace("\\palte\\", "\\plate\\")

    # Patch comp version in Viewer NDISender etc.
    body = re.sub(
        rf"(monitorOutNDISenderName \"NukeX - {re.escape(shot_name)}_comp_)v\d+",
        rf"\g<1>{nk_version}",
        body,
        count=1,
    )

    fps = str(preset_data.get("fps", "23.976"))
    width = int(float(preset_data.get("plate_width", 1920)))
    height = int(float(preset_data.get("plate_height", 1080)))
    ocio_path = _nk_escape_quotes((preset_data.get("ocio_path", "") or "").replace("\\", "/"))
    format_name = f"SP_{width}x{height}"
    fmt_str = f"{width} {height} 0 0 {width} {height} 1 {_nk_escape_quotes(format_name)}"

    # Patch Read node format (plate)
    body = re.sub(
        r'format "\d+ \d+ \d+ \d+ \d+ \d+ \d+ plate"',
        f'format "{width} {height} 0 0 {width} {height} 1 plate"',
        body,
    )

    # Patch Reformat/Crop box size
    body = re.sub(
        r" box_width \d+\n box_height \d+",
        f" box_width {width}\n box_height {height}",
        body,
        count=1,
    )

    # Read node input transform
    read_cs = (preset_data.get("read_input_transform", "") or "").strip()
    if read_cs:
        body = _patch_read_colorspace(body, read_cs)

    body, w2_ok = _patch_write2_from_preset(body, preset_data)
    if not w2_ok:
        warnings.append(
            "⚠ Write2 노드 패치 실패: 템플릿 포맷이 변경되었을 수 있습니다.\n"
            "  Write 설정(compression/datatype/colorspace)이 적용되지 않았습니다."
        )

    body, eo7_ok = _patch_eo7_mov_write(body, preset_data)
    if not eo7_ok:
        warnings.append("⚠ eo7Write1 MOV 노드 패치 실패: display/view 설정이 적용되지 않았습니다.")

    body = _patch_viewer_fps(body, fps)

    # Root block override (inserted after version line)
    root_block = (
        "Root {\n"
        " inputs 0\n"
        f" fps {fps}\n"
        f' format "{fmt_str}"\n'
        " colorManagement OCIO\n"
        " OCIO_config custom\n"
        f' customOCIOConfigPath "{ocio_path}"\n'
        "}\n"
    )

    ver_m = re.search(r"^version [\d.]+ v\d+\s*$", body, re.MULTILINE)
    if ver_m:
        insert_pos = ver_m.end()
        if insert_pos < len(body) and body[insert_pos] == "\n":
            insert_pos += 1
    else:
        second_nl = body.find("\n", body.find("\n") + 1)
        insert_pos = (second_nl + 1) if second_nl != -1 else 0

    return body[:insert_pos] + root_block + body[insert_pos:], warnings
