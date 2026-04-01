"""Generate and patch Nuke .nk script content from presets."""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bpe.core.nk_parser import _get_knob
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


_SHOT_CODE_TOKEN = re.compile(r"^E\d+_S\d+_\d+")

# 플레이트 파일명 정규화: EXR·DPX 등은 ####, MOV·MP4 등은 단일 클립으로 취급
_PLATE_SEQUENCE_EXTS = frozenset({"exr", "dpx", "tif", "tiff"})
_PLATE_VIDEO_EXTS = frozenset({"mov", "mp4", "mxf", "m4v"})


def _is_plate_read_file_path(file_path: str) -> bool:
    """``.../plate/...`` 경로면 플레이트 Read로 간주한다."""
    p = (file_path or "").replace("\\", "/").lower()
    return "/plate/" in p


def _normalize_plate_basename(
    basename: str, shot_name: str, force_ext: Optional[str] = None
) -> str:
    """
    다른 샷 템플릿의 플레이트 파일명을 현재 샷에 맞긴다.

    - ``force_ext`` 가 있으면(``plate_hi`` 폴더명 ``mov``/``exr`` 등) 템플릿 확장자보다
      실제 플레이트 폴더 종류를 우선한다.
    - 파일명이 ``E###_S###_####`` 로 시작하면 샷 코드만 바꾼 뒤, 프레임 번호는
      시퀀스/영상 모두 ``1001`` → ``####`` 로 통일한다.
    - 샷 코드가 없으면: EXR·DPX 등은 ``{shot}_org_v001.####.ext``, MOV·MP4 등은
      ``{shot}_org_v001.ext`` (단일 클립, ``####`` 없음).
    """
    base = basename.strip()

    if force_ext:
        fe = force_ext.lower().lstrip(".")
        if fe in _PLATE_VIDEO_EXTS:
            return f"{shot_name}_org_v001.{fe}"
        if fe in _PLATE_SEQUENCE_EXTS:
            return f"{shot_name}_org_v001.####.{fe}"
        return f"{shot_name}_org_v001.####.exr"

    if _SHOT_CODE_TOKEN.match(base):
        base = _SHOT_CODE_TOKEN.sub(shot_name, base, count=1)
        base = re.sub(
            r"\.(\d{4})\.(exr|dpx|tif|tiff|mov|mp4|mxf|m4v)$",
            r".####.\2",
            base,
            flags=re.IGNORECASE,
        )
        # Nuke 저장 형식 ``.%04d.exr`` (따옴표 없는 file 노브에서 흔함)
        base = re.sub(
            r"\.%0\d*d\.(exr|dpx|tif|tiff|mov|mp4|mxf|m4v)$",
            r".####.\1",
            base,
            flags=re.IGNORECASE,
        )
        return base

    if "." not in base:
        return f"{shot_name}_org_v001.####.exr"

    ext = base.rsplit(".", 1)[-1].lower()
    if ext in _PLATE_VIDEO_EXTS:
        return f"{shot_name}_org_v001.{ext}"
    if ext in _PLATE_SEQUENCE_EXTS:
        return f"{shot_name}_org_v001.####.{ext}"
    return f"{shot_name}_org_v001.####.exr"


def _patch_read_plate_file_paths(body: str, shot_name: str, paths: Dict[str, Path]) -> str:
    """
    프리셋 템플릿이 E107 고정 문자열이 아닌 *다른 샷* 경로로 저장된 경우,
    ``W:.../E107/...`` 치환이 되지 않아 Read ``file`` 이 옛 샷을 가리킨다.

    ``/plate/`` 가 포함된 Read 노드 ``file`` 을 ``paths['plate_hi']`` + 현재 샷
    파일명으로 다시 쓴다 (EXR 시퀀스·MOV 단일/시퀀스 모두
    :func:`_normalize_plate_basename` 규칙). ``file "..."``·``{...}``·따옴표 없는
    ``file W:/...``·``%04d`` 시퀀스 모두 처리. colorspace 등 다른 노브는 건드리지 않는다.
    """
    plate_hi = _to_nk_path(paths["plate_hi"])
    plate_folder = Path(paths["plate_hi"]).name.lower()
    _allowed = _PLATE_VIDEO_EXTS | _PLATE_SEQUENCE_EXTS
    force_ext: Optional[str] = plate_folder if plate_folder in _allowed else None

    blocks = _find_blocks_with_positions(body, "Read")
    result = body
    for start, end, inner in reversed(blocks):
        m = re.search(r'(?m)^( file )"([^"]*)"', inner)
        if m:
            old_path = m.group(2)
        else:
            m2 = re.search(r"(?m)^( file )\{([^}]*)\}", inner)
            if m2:
                old_path = m2.group(2).strip()
            else:
                # 따옴표 없이 `` file W:/path/...`` 만 있는 NK (Nuke가 이렇게 저장하는 경우)
                m3 = re.search(r"(?m)^( file )(\S+)", inner)
                if m3:
                    old_path = m3.group(2)
                else:
                    continue

        if not _is_plate_read_file_path(old_path):
            continue

        norm = old_path.replace("\\", "/")
        basename = norm.split("/")[-1] if norm else ""
        if not basename:
            continue

        new_base = _normalize_plate_basename(basename, shot_name, force_ext=force_ext)
        new_path = f"{plate_hi}/{new_base}"
        new_inner = _replace_knob_in_block(inner, "file", new_path)
        if new_inner != inner:
            result = result[:start] + f"Read {{{new_inner}}}" + result[end:]

    return result


# ---------------------------------------------------------------------------
# Plate frame range (Read + Viewer)
# ---------------------------------------------------------------------------

_EXR_FRAME_NUM_RE = re.compile(r"\.(\d{4})\.exr$", re.IGNORECASE)
_PLATE_VIDEO_GLOBS = ("*.mov", "*.mp4", "*.m4v")
_DEFAULT_FRAME_FIRST = 1001
_DEFAULT_FRAME_LAST = 1123


def _parse_stts_inner(body: bytes) -> int:
    """MP4 ``stts`` box inner (version+flags+entries) 에서 총 샘플 수 합산."""
    if len(body) < 8:
        return 0
    entry_count = struct.unpack_from(">I", body, 4)[0]
    offset = 8
    total = 0
    for _ in range(min(entry_count, 10_000_000)):
        if offset + 8 > len(body):
            break
        sample_count = struct.unpack_from(">I", body, offset)[0]
        total += sample_count
        offset += 8
    return total


def _find_stts_sample_total(data: bytes, start: int, end: int) -> Optional[int]:
    """ISO BMFF 트리에서 첫 ``stts`` 의 총 샘플 수 (일반적으로 비디오 트랙)."""
    pos = start
    containers = {
        b"moov",
        b"trak",
        b"mdia",
        b"minf",
        b"stbl",
        b"edts",
        b"moof",
        b"traf",
        b"meta",
    }
    while pos + 8 <= end:
        size = struct.unpack_from(">I", data, pos)[0]
        typ = data[pos + 4 : pos + 8]
        if size < 8:
            break
        if size == 1:
            if pos + 16 > end:
                break
            box_len = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            box_len = end - pos
            header = 8
        else:
            box_len = size
            header = 8
        box_end = pos + box_len
        if box_end > end:
            box_end = end
        content_start = pos + header
        if typ == b"stts":
            n = _parse_stts_inner(data[content_start:box_end])
            return n if n > 0 else None
        if typ in containers:
            sub = _find_stts_sample_total(data, content_start, box_end)
            if sub is not None:
                return sub
        pos = box_end
    return None


def _count_mov_frames(path: Path) -> Optional[int]:
    """MOV/MP4/M4V 파일에서 비디오 샘플 수(프레임 수)를 순수 Python으로 읽는다."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 32:
        return None
    total = _find_stts_sample_total(data, 0, len(data))
    return total if total is not None and total > 0 else None


def _scan_plate_frame_range(plate_hi: Path) -> Optional[Tuple[int, int]]:
    """EXR 시퀀스면 파일명 min/max, 없으면 MOV/MP4/M4V 첫 파일로 ``1001`` 기준 길이 반영."""
    nums: List[int] = []
    try:
        if not plate_hi.is_dir():
            return None
        for p in plate_hi.glob("*.exr"):
            m = _EXR_FRAME_NUM_RE.search(p.name)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            return (min(nums), max(nums))
        for pattern in _PLATE_VIDEO_GLOBS:
            candidates = sorted(plate_hi.glob(pattern))
            for p in candidates:
                if not p.is_file():
                    continue
                n = _count_mov_frames(p)
                if n is not None and n > 0:
                    last = _DEFAULT_FRAME_FIRST + n - 1
                    return (_DEFAULT_FRAME_FIRST, last)
    except OSError:
        return None
    return None


def _read_file_path_from_inner(inner: str) -> Optional[str]:
    """Read 블록 inner 에서 ``file`` 노브 경로 문자열을 꺼낸다."""
    m = re.search(r'(?m)^( file )"([^"]*)"', inner)
    if m:
        return m.group(2)
    m2 = re.search(r"(?m)^( file )\{([^}]*)\}", inner)
    if m2:
        return m2.group(2).strip()
    m3 = re.search(r"(?m)^( file )(\S+)", inner)
    if m3:
        return m3.group(2)
    return None


def _patch_read_frame_range(body: str, first: int, last: int) -> str:
    """
    ``/plate/`` 경로 Read 의 first/last/orig* 및 ``origset`` 을 맞추고,
    첫 번째 Viewer 의 ``frame_range`` 를 갱신한다.
    """
    blocks = _find_blocks_with_positions(body, "Read")
    result = body
    for start, end, inner in reversed(blocks):
        fp = _read_file_path_from_inner(inner)
        if not fp or not _is_plate_read_file_path(fp):
            continue
        new_inner = inner
        new_inner = re.sub(r"(?m)^ first \d+$", f" first {first}", new_inner)
        new_inner = re.sub(r"(?m)^ last \d+$", f" last {last}", new_inner)
        new_inner = re.sub(r"(?m)^ origfirst \d+$", f" origfirst {first}", new_inner)
        new_inner = re.sub(r"(?m)^ origlast \d+$", f" origlast {last}", new_inner)
        new_inner = re.sub(r"(?m)^ origset true$", " origset false", new_inner)
        if new_inner != inner:
            result = result[:start] + f"Read {{{new_inner}}}" + result[end:]

    result = re.sub(
        r"(Viewer \{\n frame_range )\d+-\d+",
        rf"\g<1>{first}-{last}",
        result,
        count=1,
    )
    return result


def strip_eo7_mov_problem_knobs_from_nk_body(body: str) -> str:
    """
    eo7Write1(MOV 프리뷰) 블록에서 멀티프레임 렌더를 막는 노브를 제거한다.

    ``raw true`` + ``in/out_colorspace scene_linear`` 등은 Nuke 가 MOV Write 를
    단일 프레임 통과로 처리하게 해 ``cannot be executed for multiple frames`` 를
    유발할 수 있다.
    """
    blocks = _find_blocks_with_positions(body, "Write")
    for start, end, inner in reversed(blocks):
        if not re.search(r"(?m)^ name eo7Write1\s*$", inner):
            continue
        new_inner = inner
        for pat in (
            r"(?m)^ raw true\s*\n",
            r"(?m)^ colorspace qc_interchange\s*\n",
            r"(?m)^ in_colorspace scene_linear\s*\n",
            r"(?m)^ out_colorspace scene_linear\s*\n",
        ):
            new_inner = re.sub(pat, "", new_inner)
        if new_inner != inner:
            return body[:start] + f"Write {{{new_inner}}}" + body[end:]
    return body


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


def _write2_inner_is_exr_delivery_target(inner: str) -> bool:
    """
    Whether the Write2 block should receive EXR preset patching.

    If ``file_type`` is absent or blank, treat as EXR (stock / legacy templates).
    Values are parsed like ``nk_parser._get_knob`` (quoted, braced, or bare).
    """
    raw = _get_knob(inner, "file_type")
    if raw is None or not str(raw).strip():
        return True
    norm = str(raw).strip().lower()
    return norm in ("exr", "openexr")


def _patch_write2_from_preset(body: str, preset_data: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Patch the Write2 node with preset compression/metadata/datatype/channels/OCIO
    when its ``file_type`` is EXR (or unspecified).

    MOV/MP4/DPX/etc. Write2 blocks are left unchanged so per-preset NK templates
    are preserved. Skips return ``(body, True)`` so shot build does not show a
    false \"patch failed\" warning.

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

        if not _write2_inner_is_exr_delivery_target(inner):
            return body, True

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
    # MOV/QuickTime은 단일 파일 — #### 시퀀스 접미사를 쓰면 Nuke가 멀티프레임 Write로
    # 처리하려다 "cannot be executed for multiple frames" 오류가 난다.
    renders = _to_nk_path(paths["renders"])
    if write_file_type == "mov":
        write_file = f"{renders}/{shot_name}_comp_{nk_version}.{write_ext}"
    else:
        write_file = f"{renders}/{shot_name}_comp_{nk_version}.####.{write_ext}"
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
    fr = _scan_plate_frame_range(paths["plate_hi"])
    first_fr, last_fr = fr if fr else (_DEFAULT_FRAME_FIRST, _DEFAULT_FRAME_LAST)
    lines = [
        "set cut_paste_input [stack 0]",
        "version 14.1 v4",
        "Root {",
        " inputs 0",
        f" fps {fps}",
        f' format "{fmt_str}"',
        f" first_frame {first_fr}",
        f" last_frame {last_fr}",
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

    # 템플릿이 E107 고정값이 아닌 다른 샷(E102 등)으로 저장된 경우 Read file 경로가 남는 문제
    body = _patch_read_plate_file_paths(body, shot_name, paths)

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

    body, _ = _patch_eo7_mov_write(body, preset_data)
    body = strip_eo7_mov_problem_knobs_from_nk_body(body)

    fr = _scan_plate_frame_range(paths["plate_hi"])
    first_fr, last_fr = fr if fr else (_DEFAULT_FRAME_FIRST, _DEFAULT_FRAME_LAST)

    body = _patch_viewer_fps(body, fps)
    if fr is not None:
        body = _patch_read_frame_range(body, fr[0], fr[1])

    # Root block override (inserted after version line)
    root_block = (
        "Root {\n"
        " inputs 0\n"
        f" fps {fps}\n"
        f' format "{fmt_str}"\n'
        f" first_frame {first_fr}\n"
        f" last_frame {last_fr}\n"
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

    final_body = body[:insert_pos] + root_block + body[insert_pos:]
    warnings.extend(_template_sample_path_warnings(final_body))
    return final_body, warnings


def _template_sample_path_warnings(body: str) -> List[str]:
    """템플릿 샘플 경로가 그대로 남아 있으면 경고를 반환한다."""
    out: List[str] = []
    if _TEMPLATE_SAMPLE_SHOT_ROOT in body:
        out.append(
            "⚠ NK에 템플릿 샘플 경로(W:/vfx/...)가 남아 있습니다. "
            "Read/Write file 경로를 수동으로 확인하세요."
        )
    bs = _TEMPLATE_SAMPLE_SHOT_ROOT.replace("/", "\\")
    if bs in body:
        out.append(
            "⚠ NK에 템플릿 샘플 경로(백슬래시)가 남아 있습니다. "
            "Read/Write file 경로를 수동으로 확인하세요."
        )
    return out
