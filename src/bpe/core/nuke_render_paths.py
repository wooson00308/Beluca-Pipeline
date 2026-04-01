"""NK ``root.name`` 에서 comp/devl/renders 경로 계산 (UNC ``//`` 보존).

``pathlib.Path`` / ``str().replace("\\\\", "/")`` 는 UNC 선행 ``//`` 를 잃어
Nuke가 상대경로로 해석하는 문제가 있어, 슬래시로 ``split``/``join`` 한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


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
    """``root.name`` 에서 ``.../comp/devl/renders`` 경로를 반환한다.

    ``comp/devl/nuke/v###/shot.nk`` 표준 구조뿐 아니라 ``comp/nuke/v###/shot.nk`` 처럼
    ``devl`` 이 빠진 비표준 구조에서도 ``comp`` 세그먼트를 찾아 ``comp/devl/renders`` 로 고정한다.

    UNC 선행 ``//`` 는 보존된다.
    """
    s = (root_name or "").strip()
    if not s:
        return None
    normalized = s.replace("\\", "/")
    lower = normalized.lower()
    key = "/comp/"
    idx = lower.find(key)
    if idx == -1:
        return None
    # ``.../comp`` 까지 (``/comp/`` 의 선행 ``/`` 위치 ``idx`` 에서 ``/comp`` 5글자)
    base = normalized[: idx + len("/comp")]
    return f"{base}/devl/renders"


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
