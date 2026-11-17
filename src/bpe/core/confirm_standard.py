"""컨펌 창의 검사 기준 — 프로젝트 프리셋(납품 프리셋)에서 읽는다.

프리셋 값과 그 프리셋의 누크 틀(template.nk)에서 MOV 가 어떤 규격으로 나와야 하는지를
뽑는다: fps, MOV 크기, 코덱, 입혀지는 룩(뷰), 파일의 색 표시.

읽기만 한다 — 프리셋 폴더(팀 공용 서버일 수 있다)에 아무것도 만들거나 고치지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

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
_SET_LINE = re.compile(r"^set (\w+) \[stack 0\]")
_PUSH_LINE = re.compile(r"^push \$?(\w+)")
_NO_INPUT = re.compile(r"^\s*inputs\s+0\s*$")
_INT_KNOB = re.compile(r"^\s*(box_width|box_height)\s+(\d+)\s*$")
_FORMAT_KNOB = re.compile(r'^\s*format\s+"?(\d+)\s+(\d+)\b')
_FILE_TYPE = re.compile(r"^\s*file_type\s+(\w+)\s*$")


class ProjectStandard(NamedTuple):
    """프리셋에서 읽은, 컨펌용 MOV 가 맞춰야 할 기준. 모르는 값은 ``None`` / 빈 글."""

    preset: str
    fps: Optional[float]
    mov_sizes: Tuple[Tuple[int, int], ...]
    plate_size: Optional[Tuple[int, int]]
    codec: str
    look: str
    color_tags: Tuple[str, ...]
    viewer: str
    lut_path: str = ""  # 프리셋 누크 틀의 룩업 노드가 읽는 .cube (없으면 빈 글)

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


_AI_TOKEN = "AI"
Size = Tuple[int, int]


def pick_preset(
    names: Sequence[str],
    *,
    plate_color: Optional[str] = None,
    work_size: Optional[Size] = None,
    sizes: Optional[Mapping[str, Sequence[Size]]] = None,
) -> Tuple[str, bool]:
    """프리셋이 여러 개인 프로젝트에서 이 샷의 프리셋을 고른다 → ``(이름, 하나로 정해졌나)``.

    이름의 ``REC709``/``GAMMA`` 는 샷 빌더처럼 플레이트 MOV 의 색(자동 인식)으로 가른다.
    AI 프리셋인지 일반 프리셋인지는 샷그리드에서 믿을 만하게 읽을 길이 없어서, 올라온
    영상의 크기(*work_size*)가 어느 프리셋의 MOV 크기(*sizes*)와 같은지로 가른다 — 작업자가
    샷을 만들 때 고른 프리셋이 영상 크기에 그대로 남기 때문이다. 정보가 없는 기준은 건너뛴다.
    """
    cand = list(names)
    if not cand:
        return "", False

    def tokens(name: str) -> List[str]:
        return name.upper().split("_")

    if plate_color:
        hit = [n for n in cand if plate_color.upper() in tokens(n)]
        cand = hit or cand
    if work_size is not None and sizes:
        hit = [n for n in cand if tuple(work_size) in [tuple(x) for x in sizes.get(n, ())]]
        cand = hit or cand
    # 그래도 여럿이면 더 흔한 일반 프리셋을 먼저 내민다
    cand.sort(key=lambda n: _AI_TOKEN in tokens(n))
    return cand[0], len(cand) == 1


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


def mov_sizes_from_template(text: str) -> List[Tuple[int, int]]:
    """누크 틀에서 MOV 를 쓰는 Write 로 들어가는 그림의 크기들(Write 가 여럿이면 여럿).

    누크 스크립트의 줄 순서를 따라가며 "지금 맨 위 그림의 크기"를 센다: Reformat 은 크기를
    정하고, ``set 이름 [stack 0]`` 은 그 그림을 이름으로 적어 두고, ``push $이름`` 은 적어 둔
    그림을 다시 맨 위로 올린다. 크기를 알 수 없는 가지의 MOV 는 넣지 않는다 —
    다른 출력(EXR)의 크기를 MOV 크기로 잘못 읽지 않기 위해서다.
    """
    top: Optional[Tuple[int, int]] = None
    saved: Dict[str, Optional[Tuple[int, int]]] = {}
    out: List[Tuple[int, int]] = []
    node = ""
    knobs: Dict[str, int] = {}
    size: Optional[Tuple[int, int]] = None
    is_mov = no_input = False
    for line in text.splitlines():
        if not node:
            m = _SET_LINE.match(line)
            if m:
                saved[m.group(1)] = top
                continue
            m = _PUSH_LINE.match(line)
            if m:
                top = saved.get(m.group(1))
                continue
            m = _NODE_START.match(line)
            if m:
                node, knobs, size, is_mov, no_input = m.group(1), {}, None, False, False
            continue
        if line.strip() == "}":
            if node == "Reformat":
                if "box_width" in knobs and "box_height" in knobs:
                    top = (knobs["box_width"], knobs["box_height"])
                else:
                    top = size
            elif node == "Read" or no_input:
                top = None  # 새 그림이 시작된다 — 크기는 모른다
            elif node == "Write" and is_mov and top is not None and top not in out:
                out.append(top)
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
        if _NO_INPUT.match(line):
            no_input = True
            continue
        t = _FILE_TYPE.match(line)
        if t and t.group(1).lower() == "mov":
            is_mov = True
    return out


def mov_size_from_template(text: str) -> Optional[Tuple[int, int]]:
    """MOV 크기 하나(여럿이면 첫째). 없으면 ``None``."""
    sizes = mov_sizes_from_template(text)
    return sizes[0] if sizes else None


_LUT_NODE = re.compile(r"^(Vectorfield|OCIOFileTransform) \{\n(.*?)^\}", re.M | re.S)
_LUT_FILE_KNOB = re.compile(
    r'^\s*(?:vfield_file|file)\s+(?:"([^"\n]+)"|\{([^}\n]+)\}|(\S+))\s*$', re.M
)


def lut_path_from_template(text: str) -> str:
    """프리셋 누크 틀의 룩업 노드(Vectorfield·OCIOFileTransform)가 읽는 ``.cube`` 경로.

    여러 개면 틀에 먼저 나오는 것. 식(``[...]``·``$``)이 든 경로와 .cube 가 아닌 것은 건너뛴다.
    """
    for node in _LUT_NODE.finditer(text or ""):
        for m in _LUT_FILE_KNOB.finditer(node.group(2)):
            path = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if path.lower().endswith(".cube") and "[" not in path and "$" not in path:
                return path
    return ""


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
        mov_sizes=tuple(mov_sizes_from_template(template_text)) if template_text else (),
        plate_size=_to_size(preset.get("plate_width"), preset.get("plate_height")),
        codec=codec,
        look=look,
        color_tags=_color_tags_for_view(view),
        viewer=str(preset.get("viewer_process") or "").strip(),
        lut_path=lut_path_from_template(template_text) if template_text else "",
    )


def load_standard(preset_name: str) -> Optional[ProjectStandard]:
    preset = read_presets().get(preset_name)
    if not isinstance(preset, dict):
        return None
    return build_standard(preset_name, preset, read_template(preset_name))
