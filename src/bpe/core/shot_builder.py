"""Shot name parsing and server-path construction."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shot_builder")


def _resolve_plate_hi(shot_root: Path) -> Path:
    """
    ``plate/org/v001`` 아래 ``hi``(EXR 시퀀스) vs ``mov``(단일 클립) 중
    실제로 존재하는 폴더를 고른다. 둘 다 없으면 ``hi``(신규 샷 기본값).
    """
    base = shot_root / "plate" / "org" / "v001"
    for sub in ("hi", "mov"):
        candidate = base / sub
        if candidate.is_dir():
            return candidate
    return base / "hi"


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
    ``plate_hi`` 키는 ``plate/org/v001/hi`` 또는 ``.../mov`` 중 디스크에 있는 쪽을 가리킨다.
    shot_name을 파싱할 수 없으면 None.
    """
    parsed = parse_shot_name(shot_name)
    if not parsed:
        return None
    shot_root = Path(server_root) / project_code / "04_sq" / parsed["ep"] / parsed["full"]
    nuke_dir = shot_root / "comp" / "devl" / "nuke"
    return {
        "shot_root": shot_root,
        "nuke_dir": nuke_dir,
        "plate_hi": _resolve_plate_hi(shot_root),
        "edit": shot_root / "edit",
        "renders": shot_root / "comp" / "devl" / "renders",
        "element": shot_root / "comp" / "devl" / "element",
    }


def comp_devl_structure_exists(paths: Dict[str, Path]) -> bool:
    """``comp/devl`` 아래 nuke·renders·element 폴더가 모두 있으면 True."""
    shot = paths["shot_root"]
    comp = shot / "comp"
    if not comp.is_dir():
        return False
    devl = comp / "devl"
    if not devl.is_dir():
        return False
    return paths["nuke_dir"].is_dir() and paths["renders"].is_dir() and paths["element"].is_dir()


def ensure_comp_folder_structure(paths: Dict[str, Path], nk_version: str = "v001") -> List[str]:
    """
    ``comp/devl/nuke/{nk_version}``, ``renders``, ``element`` 가 없으면 생성한다.

    Returns:
        생성된 디렉터리 경로 문자열 목록 (이미 있던 것은 제외).
    """
    created: List[str] = []
    nuke_v = paths["nuke_dir"] / nk_version
    for d in (nuke_v, paths["renders"], paths["element"]):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    return created
