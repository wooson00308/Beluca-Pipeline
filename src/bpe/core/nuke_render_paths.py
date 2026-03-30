"""NK ``root.name`` 에서 comp/devl/renders 경로 계산 (UNC ``//`` 보존).

``pathlib.Path`` / ``str().replace("\\\\", "/")`` 는 UNC 선행 ``//`` 를 잃어
Nuke가 상대경로로 해석하는 문제가 있어, 슬래시로 ``split``/``join`` 한다.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


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


def write_file_paths_from_nk_root_name(root_name: str) -> Optional[Tuple[str, str, str]]:
    """Write2 / eo7Write1 용 절대 경로 문자열 (슬래시, UNC ``//`` 보존).

    Returns:
        ``(renders_dir, exr_path, mov_path)`` — EXR 은 시퀀스 패턴 포함.
    """
    comp_devl = comp_devl_dir_from_nk_path(root_name)
    if comp_devl is None:
        return None
    normalized = str(root_name).replace("\\", "/")
    nk_basename = os.path.basename(normalized)
    shot_ver_name = os.path.splitext(nk_basename)[0]
    renders_dir = f"{comp_devl}/renders"
    exr_path = f"{renders_dir}/{shot_ver_name}/{shot_ver_name}.%04d.exr"
    mov_path = f"{renders_dir}/{shot_ver_name}.mov"
    return renders_dir, exr_path, mov_path
