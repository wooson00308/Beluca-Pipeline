"""Shot name parsing and server-path construction."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from bpe.core.logging import get_logger

logger = get_logger("shot_builder")


def parse_shot_name(shot_name: str) -> Optional[Dict[str, str]]:
    """샷 이름에서 에피소드 폴더명을 추출한다.

    예) E107_S022_0080 → {"ep": "E107", "full": "E107_S022_0080"}
    서버 경로: 04_sq / EP / SHOT_NAME
    """
    s = (shot_name or "").strip().upper()
    if not s:
        return None
    parts = s.split("_")
    if len(parts) < 2:
        return None
    return {"ep": parts[0], "full": s}


def build_shot_paths(
    server_root: str, project_code: str, shot_name: str
) -> Optional[Dict[str, Path]]:
    """샷의 서버 경로 딕셔너리를 반환한다.

    구조: server_root / project_code / 04_sq / EP / shot_name / ...
    shot_name을 파싱할 수 없으면 None.
    """
    parsed = parse_shot_name(shot_name)
    if not parsed:
        return None
    shot_root = (
        Path(server_root) / project_code / "04_sq" / parsed["ep"] / parsed["full"]
    )
    nuke_dir = shot_root / "comp" / "devl" / "nuke"
    return {
        "shot_root": shot_root,
        "nuke_dir": nuke_dir,
        "plate_hi": shot_root / "plate" / "org" / "v001" / "hi",
        "edit": shot_root / "edit",
        "renders": shot_root / "comp" / "devl" / "renders",
        "element": shot_root / "comp" / "devl" / "element",
    }
