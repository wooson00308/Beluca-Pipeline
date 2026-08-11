# @cursor-change: 2026-08-09, 0.13.x, 탐색기 하이라이트 경로·Windows /select argv
"""Source Library 「폴더 열기」용 경로·Explorer argv 헬퍼.

미디어 파일은 읽기만 한다. OS 탐색기를 띄울 뿐 서버 원본을 수정하지 않는다.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.source_library_scan import (
    KIND_SEQUENCE,
    row_dir_path,
    row_first_frame_path,
    row_pattern_path,
    row_representative_path,
)


def row_reveal_path(row: Dict[str, Any]) -> str:
    """탐색기에서 선택할 경로. 가능하면 실존 파일, 아니면 폴더.

    * 팩(``preview_file`` 있음): JPG representative → first frame → dir
    * 일반 시퀀스: first frame → dir
    * movie/still: 파일 자신 → dir
    """
    preview = str(row.get("preview_file") or "").strip()
    kind = str(row.get("kind") or "")

    candidates: List[str] = []
    if preview:
        candidates.append(row_representative_path(row))
        candidates.append(row_first_frame_path(row))
    elif kind == KIND_SEQUENCE:
        candidates.append(row_first_frame_path(row))
    else:
        candidates.append(row_pattern_path(row))

    for raw in candidates:
        path = normalize_path_str(raw)
        if path and os.path.isfile(path):
            return path

    return normalize_path_str(row_dir_path(row))


def windows_explorer_select_args(path: str) -> List[str]:
    """``explorer /select,`` 와 경로를 분리한 argv (공백 경로 안전)."""
    win = normalize_path_str(path).replace("/", "\\")
    return ["explorer", "/select,", win]
