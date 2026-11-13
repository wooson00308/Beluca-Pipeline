"""컨펌 창의 검사 기준 — 프로젝트 프리셋(납품 프리셋)에서 읽는다.

프리셋 값과 그 프리셋의 누크 틀(template.nk)에서 MOV 가 어떤 규격으로 나와야 하는지를
뽑는다: fps, MOV 크기, 코덱, 입혀지는 룩(뷰), 파일의 색 표시.

읽기만 한다 — 프리셋 폴더(팀 공용 서버일 수 있다)에 아무것도 만들거나 고치지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import bpe.core.config as cfg
import bpe.core.settings as settings_mod
from bpe.core.logging import get_logger
from bpe.core.presets import find_matching_preset_keys

logger = get_logger("core.confirm_standard")

# 누크 mov64_codec 값 → ffprobe 의 코덱 이름
_CODEC_FAMILY = {
    "appr": "prores",
    "apch": "prores",
    "apcn": "prores",
    "apcs": "prores",
    "apco": "prores",
    "ap4h": "prores",
    "ap4x": "prores",
    "prores": "prores",
    "avc1": "h264",
    "h264": "h264",
    "avdn": "dnxhd",
    "dnxhd": "dnxhd",
    "mp4v": "mpeg4",
    "jpeg": "mjpeg",
    "mjpa": "mjpeg",
}
_CODEC_TITLES = {"prores": "ProRes", "h264": "H.264", "dnxhd": "DNxHD", "mpeg4": "MPEG-4"}
_NODE_START = re.compile(r"^(\w+) \{\s*$")
_BRANCH_LINE = re.compile(r"^(push|set) ")
_INT_KNOB = re.compile(r"^\s*(box_width|box_height)\s+(\d+)\s*$")
_FORMAT_KNOB = re.compile(r'^\s*format\s+"?(\d+)\s+(\d+)\b')
_FILE_TYPE = re.compile(r"^\s*file_type\s+(\w+)\s*$")


class ProjectStandard(NamedTuple):
    """프리셋에서 읽은, 컨펌용 MOV 가 맞춰야 할 기준. 모르는 값은 ``None`` / 빈 글."""

    preset: str
    fps: Optional[float]
    mov_size: Optional[Tuple[int, int]]
    plate_size: Optional[Tuple[int, int]]
    codec: str
    look: str
    color_tags: Tuple[str, ...]
    viewer: str

    @property
    def codec_title(self) -> str:
        return _CODEC_TITLES.get(self.codec, self.codec)


# ── 프리셋 읽기 (읽기 전용) ────────────────────────────────────────


def presets_dir() -> Path:
    """프리셋 폴더. 없다고 만들지 않는다 — 못 쓰면 로컬 폴더를 가리킨다."""
    stored = settings_mod.load_settings().get("presets_dir")
    target = (
        Path(stored.strip())
        if isinstance(stored, str) and stored.strip()
        else settings_mod._DEFAULT_PRESETS_DIR
    )
    try:
        if target.exists():
            return target
    except OSError:
        pass
    return cfg.APP_DIR / "presets"


def read_presets() -> Dict[str, Any]:
    path = presets_dir() / "presets.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_template(preset_name: str) -> str:
    path = presets_dir() / f"{preset_name}_template.nk"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def preset_names_for(
    presets: Dict[str, Any], project_code: str, path_parts: Sequence[str] = ()
) -> List[str]:
    """이 샷에 쓸 수 있는 프리셋 이름들. 프로젝트 코드가 없으면 경로의 폴더 이름에서 찾는다."""
    for code in [project_code, *reversed(list(path_parts))]:
        names = find_matching_preset_keys(presets, str(code or ""))
        if names:
            return names
    return []


# ── 풀이 ─────────────────────────────────────────────────────────


def _to_float(value: Any) -> Optional[float]:
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _to_size(width: Any, height: Any) -> Optional[Tuple[int, int]]:
    w, h = _to_float(width), _to_float(height)
    return (int(w), int(h)) if w and h else None


def mov_size_from_template(text: str) -> Optional[Tuple[int, int]]:
    """누크 틀에서 MOV 를 쓰는 Write 바로 앞 Reformat 의 크기.

    가지가 바뀌는 줄(``push``/``set``)을 지나면 앞 가지의 크기는 잊는다 —
    다른 출력(EXR)의 크기를 MOV 크기로 잘못 읽지 않기 위해서다.
    """
    last: Optional[Tuple[int, int]] = None
    node = ""
    knobs: Dict[str, int] = {}
    size: Optional[Tuple[int, int]] = None
    is_mov = False
    for line in text.splitlines():
        if not node:
            if _BRANCH_LINE.match(line):
                last = None
                continue
            m = _NODE_START.match(line)
            if m:
                node, knobs, size, is_mov = m.group(1), {}, None, False
            continue
        if line.strip() == "}":
            if node == "Reformat":
                if "box_width" in knobs and "box_height" in knobs:
                    last = (knobs["box_width"], knobs["box_height"])
                elif size:
                    last = size
            elif node == "Write" and is_mov:
                return last
            node = ""
            continue
        k = _INT_KNOB.match(line)
        if k:
            knobs[k.group(1)] = int(k.group(2))
            continue
        f = _FORMAT_KNOB.match(line)
        if f:
            size = (int(f.group(1)), int(f.group(2)))
            continue
        t = _FILE_TYPE.match(line)
        if t and t.group(1).lower() == "mov":
            is_mov = True
    return None


def _color_tags_for_view(view: str) -> Tuple[str, ...]:
    """뷰 이름으로 미루어, MOV 파일의 색 표시(color_space)로 받아들일 값들."""
    low = view.lower()
    if "2020" in low or "2100" in low or "hlg" in low or "pq" in low:
        return ("bt2020nc", "bt2020c", "bt2020")
    if "709" in low or "srgb" in low:
        return ("bt709",)
    return ()


def build_standard(name: str, preset: Dict[str, Any], template_text: str = "") -> ProjectStandard:
    display = str(preset.get("mov_display") or "").strip()
    view = str(preset.get("mov_view") or "").strip()
    look = " / ".join(x for x in (display, view) if x) if view else ""
    codec = _CODEC_FAMILY.get(str(preset.get("mov_codec") or "").strip().lower(), "")
    return ProjectStandard(
        preset=name,
        fps=_to_float(preset.get("mov_fps")) or _to_float(preset.get("fps")),
        mov_size=mov_size_from_template(template_text) if template_text else None,
        plate_size=_to_size(preset.get("plate_width"), preset.get("plate_height")),
        codec=codec,
        look=look,
        color_tags=_color_tags_for_view(view),
        viewer=str(preset.get("viewer_process") or "").strip(),
    )


def load_standard(preset_name: str) -> Optional[ProjectStandard]:
    preset = read_presets().get(preset_name)
    if not isinstance(preset, dict):
        return None
    return build_standard(preset_name, preset, read_template(preset_name))
