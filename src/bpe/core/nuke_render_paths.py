# @cursor-change: 2026-08-06, 0.2.x, 태스크별 샷 빌드 — rnd 등 renders 경로 폴백
"""NK ``root.name`` 에서 comp/devl/renders 경로 계산 (UNC ``//`` 보존).

``pathlib.Path`` / ``str().replace("\\\\", "/")`` 는 UNC 선행 ``//`` 를 잃어
Nuke가 상대경로로 해석하는 문제가 있어, 슬래시로 ``split``/``join`` 한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

_VERSION_DIR_RE = re.compile(r"^v\d+$", re.IGNORECASE)


def comp_devl_dir_from_nk_path(root_name: str) -> Optional[str]:
    """``.../comp/devl/nuke/v###/shot.nk`` 에서 ``.../comp/devl`` 까지 경로.

    ``dirname`` 을 세 번 적용한 것과 동일 (파일명, ``v###``, ``nuke`` 제거).

    UNC (``//server/share/...``) 이면 ``//`` 가 유지된다.
    """
    s = (root_name or "").strip()
    if not s:
        return None
    normalized = s.replace("\\", "/")
    parts = normalized.split("/")
    # 마지막 세 구간: ``shot.nk``, ``v###``, ``nuke`` 제거
    if len(parts) < 4:
        return None
    comp_devl = "/".join(parts[:-3])
    if not comp_devl or comp_devl.strip("/") == "":
        return None
    return comp_devl


def renders_dir_from_nk_path_robust(root_name: str) -> Optional[str]:
    """``root.name`` 에서 ``.../{task}/devl/renders`` 경로를 반환한다.

    ``comp/devl/nuke/v###/shot.nk`` 표준 구조뿐 아니라 ``comp/nuke/v###/shot.nk`` 처럼
    ``devl`` 이 빠진 비표준 구조에서도 ``comp`` 세그먼트를 찾아 ``comp/devl/renders`` 로 고정한다.

    ``/comp/`` 가 없을 때(``rnd/devl/nuke/v###`` 등)는 표준 ``{task}/devl/nuke/v###`` 모양일
    때만 ``{task}/devl/renders`` 를 반환한다.

    UNC 선행 ``//`` 는 보존된다.
    """
    s = (root_name or "").strip()
    if not s:
        return None
    normalized = s.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) < 5:
        return None

    # 1) 표준 ``.../{task}/devl/nuke/v###/file.nk`` 를 **먼저** 본다.
    #    이걸 뒤로 미루면 프로젝트/부서 이름에 ``comp`` 가 섞인 경로
    #    (예: ``W:/comp/proj/seq/SHOT/lighting/devl/nuke/v003/s.nk``) 에서
    #    엉뚱한 ``W:/comp/devl/renders`` 로 탈출한다.
    if (
        parts[-4].lower() == "devl"
        and parts[-3].lower() == "nuke"
        and _VERSION_DIR_RE.match(parts[-2])
    ):
        return "/".join(parts[:-3]) + "/renders"

    # 2) ``devl`` 이 빠진 비표준 구조 — 가장 **오른쪽** ``comp`` 세그먼트 기준.
    for i in range(len(parts) - 2, 0, -1):
        if parts[i].lower() == "comp":
            return "/".join(parts[: i + 1]) + "/devl/renders"
    return None


def normalize_unc_to_drive(path: str, unc_mappings: Dict[str, str]) -> str:
    """UNC 접두사를 ``unc_mappings`` 에 따라 드라이브 문자 경로로 바꾼다.

    ``unc_mappings`` 키는 ``//server/share`` 형태(슬래시), 값은 ``W:`` 또는 ``W:/`` 형태.
    매칭은 키 길이 내림차순(가장 긴 접두사 우선). 이미 드라이브 문자이거나 매핑 없으면 그대로.
    """
    if not path or not unc_mappings:
        return path
    s = path.replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return s
    items = sorted(
        ((k.strip().replace("\\", "/"), v.strip()) for k, v in unc_mappings.items()),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for unc_prefix, drive in items:
        if not unc_prefix or not drive:
            continue
        pfx = unc_prefix if unc_prefix.startswith("//") else "//" + unc_prefix.lstrip("/")
        if s.startswith(pfx):
            suffix = s[len(pfx) :].lstrip("/")
            d = drive.rstrip("/")
            if len(d) == 2 and d[1] == ":":
                return f"{d}/{suffix}" if suffix else d
            return f"{d}/{suffix}" if suffix else d
    return path


def normalize_path_str(path: Union[str, Path]) -> str:
    """UNC(``//zeus...`` / ``\\\\zeus...``) 를 ``get_unc_mappings()`` 기준 드라이브 경로로 바꾼다.

    BPE·Nuke 전 구간에서 경로를 사용자에게 보이거나 외부 프로세스에 넘기기 직전에 호출한다.
    """
    from bpe.core.settings import get_unc_mappings

    s = str(path).replace("\\", "/")
    return normalize_unc_to_drive(s, get_unc_mappings())


def _renders_base(root_name: str) -> Optional[Tuple[str, str]]:
    """``root.name`` 에서 ``(renders_dir, shot_ver_name)`` 반환. 실패 시 ``None``."""
    comp_devl = comp_devl_dir_from_nk_path(root_name)
    if comp_devl is None:
        return None
    normalized = str(root_name).replace("\\", "/")
    nk_basename = os.path.basename(normalized)
    shot_ver_name = os.path.splitext(nk_basename)[0]
    renders_dir = f"{comp_devl}/renders"
    return renders_dir, shot_ver_name


def render_path_for_extension(
    root_name: str,
    ext: str,
    frame_pattern: str = "",
) -> Optional[str]:
    """임의 확장자·프레임 패턴에 대한 ``renders`` 절대 경로 (UNC ``//`` 보존).

    Args:
        root_name: Nuke ``root.name`` 값.
        ext: 확장자 (``exr``, ``dpx``, ``tiff`` 등, 점 없이).
        frame_pattern: 시퀀스이면 ``%04d`` / ``####`` 등, 단일 파일이면 ``""``.

    Returns:
        절대 경로 문자열. 시퀀스이면 서브 디렉터리 포함.
    """
    base = _renders_base(root_name)
    if base is None:
        return None
    renders_dir, shot_ver_name = base
    ext = (ext or "").lstrip(".").strip()
    if not ext:
        return None
    if frame_pattern:
        return f"{renders_dir}/{shot_ver_name}/{shot_ver_name}.{frame_pattern}.{ext}"
    return f"{renders_dir}/{shot_ver_name}.{ext}"


def write_file_paths_from_nk_root_name(root_name: str) -> Optional[Tuple[str, str, str]]:
    """Write2 / eo7Write1 용 절대 경로 문자열 (슬래시, UNC ``//`` 보존).

    Returns:
        ``(renders_dir, exr_path, mov_path)`` — EXR 은 시퀀스 패턴 포함.
    """
    base = _renders_base(root_name)
    if base is None:
        return None
    renders_dir, shot_ver_name = base
    exr_path = f"{renders_dir}/{shot_ver_name}/{shot_ver_name}.%04d.exr"
    mov_path = f"{renders_dir}/{shot_ver_name}.mov"
    return renders_dir, exr_path, mov_path


# ══════════════════════════════════════════════════════════════════════
# Write 경로 보정/복구 판정 (tool_hooks 에서 사용, pytest 대상)
# ══════════════════════════════════════════════════════════════════════

_VERSION_SUFFIX_RE = re.compile(r"_v\d+$", re.IGNORECASE)
_ZEROLESS_PAD_RE = re.compile(r"%[1-9]\d*d")
_FRAME_TOKEN_IN_NAME_RE = re.compile(r"\.(%\d*d|#+)\.(\w+)")
_TRAILING_EXT_RE = re.compile(r"\.([A-Za-z0-9]+)\s*[\"\]]?\s*$")

# 레거시 Write 템플릿에 등장하는 Tcl 표현식 — 정확 치환용.
# base: ``.../{task}/devl`` (renders 의 부모), shot_ver: nk 파일명(확장자 제외).
_TCL_BASE_EXPRS = (
    "[string trim [value root.name] nuke/[file tail [value root.name]]]",
    "[file dirname [file dirname [file dirname [value root.name]]]]",
)
_TCL_SHOTVER_EXPRS = (
    "[string trim [file tail [value root.name]] .nk]",
    "[file rootname [file tail [value root.name]]]",
)


def canonical_frame_pattern(fp: str) -> str:
    """프레임 패턴 표기를 교정한다.

    - ``####`` → ``%04d`` (해시 개수만큼 폭)
    - ``%4d`` 류(0 없는 폭 지정) → ``%04d`` — 과거 프레임 패턴 추출 버그 산물 교정.
      공백 패딩 파일명(``shot.   1.exr``)은 정상 워크플로에서 나올 수 없다.
    - 그 외(``%04d``, ``%d``)는 그대로 반환.
    """
    fp = (fp or "").strip()
    if fp.startswith("#"):
        return f"%0{len(fp)}d"
    m = re.fullmatch(r"%([1-9]\d*)d", fp)
    if m:
        return f"%0{m.group(1)}d"
    return fp


def extract_frame_pattern_from_write_script(script_text: str) -> str:
    """Write ``file`` Tcl/평문 값에서 프레임 패턴 추출 (기본 ``%04d``). 표기 교정 포함."""
    t = (script_text or "").replace("\\", "")
    m = _FRAME_TOKEN_IN_NAME_RE.search(t)
    if m:
        return canonical_frame_pattern(m.group(1))
    return "%04d"


def ext_from_write_script_text(script_text: str) -> Optional[str]:
    """Write ``file`` Tcl/평문 값에서 확장자 추출. 못 찾으면 ``None``.

    과거 ext 추론 버그 산물 ``name`` (``[value root.name]`` 의 ``.name]`` 매칭, 또는
    그 결과로 저장된 평문 ``...%04d.name``)은 유효 확장자로 취급하지 않는다.
    """
    t = (script_text or "").replace("\\", "")
    m = _FRAME_TOKEN_IN_NAME_RE.search(t)
    if m and m.group(2).lower() != "name":
        return m.group(2).lower()
    m2 = _TRAILING_EXT_RE.search(t.strip())
    if m2 and m2.group(1).lower() != "name":
        return m2.group(1).lower()
    return None


def eval_managed_write_tcl(
    script_text: str,
    root_name: str,
    unc_mappings: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """레거시 Write Tcl 템플릿을 ``root.name`` 기준으로 정확히 평가한다.

    표준 템플릿의 두 표현식(base / shot_ver)만 치환하고 **나머지 리터럴은 그대로
    보존**한다 — 커스텀 접미사(``_lut`` 등), 하위 폴더, 확장자, 프레임 패딩이
    작성자가 넣은 그대로 남는다. Write 노드가 여러 개여도 각자의 템플릿 원문이
    평가되므로 서로 다른 이름이 유지된다.

    알 수 없는 Tcl 이 남으면 ``None`` (호출부는 표준 재구성으로 폴백).
    """
    rn = (root_name or "").strip()
    if not rn:
        return None
    renders_dir = renders_dir_from_nk_path_robust(rn)
    if not renders_dir or not renders_dir.endswith("/renders"):
        return None
    mappings = unc_mappings or {}
    base = normalize_unc_to_drive(renders_dir[: -len("/renders")], mappings)
    shot_ver = os.path.splitext(os.path.basename(rn.replace("\\", "/")))[0]
    if not shot_ver:
        return None

    t = (script_text or "").replace("\\", "").strip().strip('"').strip()
    if not t or "[" not in t:
        return None
    for expr in _TCL_BASE_EXPRS:
        t = t.replace(expr, base)
    for expr in _TCL_SHOTVER_EXPRS:
        t = t.replace(expr, shot_ver)
    if "[" in t or "]" in t or '"' in t:
        return None
    t = normalize_unc_to_drive(t.replace("\\", "/"), mappings)
    # 치환 결과가 base 로 시작하지 않으면 미지의 템플릿 — 안전하게 포기.
    if not t.startswith(base + "/"):
        return None
    return t


def _path_root_key(path: str) -> str:
    """드라이브(``w:``) 또는 UNC 루트(``//server/share``) 소문자 키. 없으면 ``""``."""
    s = (path or "").replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return s[:2].lower()
    if s.startswith("//"):
        parts = [p for p in s[2:].split("/") if p]
        if len(parts) >= 2:
            return f"//{parts[0]}/{parts[1]}".lower()
    return ""


def classify_recoverable_write_path(
    plain_path: str,
    root_name: str,
    unc_mappings: Optional[Dict[str, str]] = None,
    allow_version_mismatch: bool = False,
) -> Optional[str]:
    """평문(비 Tcl) Write 경로가 과거 BPE 버그로 깨져 저장된 것인지 판정한다.

    복구 대상이면 로그용 사유 문자열, 아니면 ``None``.
    ``None`` 이면 아티스트 커스텀 경로로 간주하고 **절대 덮어쓰지 말 것**.

    모든 규칙은 ``/renders/`` 세그먼트가 있어야 발동한다 (개인 경로 보호):
      a1. ``%4d`` 류 0 없는 폭 지정 패딩 — 과거 프레임 패턴 추출 버그 산물.
      a2. 확장자 ``.name`` — 과거 ext 추론 버그 산물.
      b.  파일명이 ``root.name`` 샷버전 이름 + ``(.<pad>)?.<ext>`` 규칙과 일치
          — UNC 미정규화·comp 세그먼트 탈출 등으로 디렉터리만 어긋난 산물.
          로컬 사본 보호를 위해 드라이브/UNC 루트가 ``root.name`` 과 같아야 한다.
      b'. ``allow_version_mismatch=True`` 이면 버전 접미사(``_v###``)만 다른
          파일명도 (b) 로 인정 — 버전업 후 다시 연 깨진 스크립트 복구용.
    """
    s = (plain_path or "").strip().replace("\\", "/")
    if not s or "[" in s or "$" in s:
        return None
    low = s.lower()
    if "/renders/" not in low:
        return None

    # (a1) 정상 워크플로/템플릿에서 생성 불가능한 패딩
    if _ZEROLESS_PAD_RE.search(s):
        return "0 없는 프레임 패딩(%4d 류) - 과거 프레임 패턴 버그"
    # (a2) 실존하지 않는 포맷 — 렌더 자체가 불가능한 경로
    if low.endswith(".name"):
        return "확장자 .name - 과거 ext 추론 버그"

    # (b) root.name 기대 파일명 규칙과 대조
    rn = (root_name or "").strip().replace("\\", "/")
    if not rn:
        return None
    shot_ver = os.path.splitext(os.path.basename(rn))[0].lower()
    if not shot_ver:
        return None
    fname = low.rsplit("/", 1)[-1]
    reason = "샷버전 파일명 일치 - 디렉터리 복구"
    stem_ok = fname.startswith(shot_ver + ".")
    rest = fname[len(shot_ver) + 1 :] if stem_ok else ""
    if not stem_ok and allow_version_mismatch:
        base = _VERSION_SUFFIX_RE.sub("", shot_ver)
        m = re.match(re.escape(base) + r"_v\d+\.", fname) if base else None
        if m:
            stem_ok = True
            rest = fname[m.end() :]
            reason = "샷 이름 일치(버전 불일치) - 구버전 평문 경로 복구"
    if not stem_ok:
        return None
    if not re.fullmatch(r"(?:(?:%0?\d*d|#+)\.)?[a-z0-9]+", rest):
        return None
    mappings = unc_mappings or {}
    if _path_root_key(normalize_unc_to_drive(s, mappings)) != _path_root_key(
        normalize_unc_to_drive(rn, mappings)
    ):
        return None
    return reason
