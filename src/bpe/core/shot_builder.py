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


def _ep_dirs_containing_shot_folder(sq_dir: Path, shot_full: str) -> List[str]:
    """``04_sq`` 직계 자식 에피소드 폴더 중 ``shot_full`` 이름의 샷 디렉터리가 있는 것들."""
    want = (shot_full or "").strip().upper()
    if not want:
        return []
    matches: List[str] = []
    try:
        if not sq_dir.is_dir():
            return []
        for ep_dir in sq_dir.iterdir():
            if not ep_dir.is_dir():
                continue
            found = False
            try:
                for child in ep_dir.iterdir():
                    if child.is_dir() and child.name.upper() == want:
                        found = True
                        break
            except OSError:
                continue
            if found:
                matches.append(ep_dir.name)
    except OSError:
        return []
    return matches


def _resolve_ep_segment_for_disk(
    server_root: str, project_code: str, parsed_ep: str, shot_full: str
) -> str:
    """디스크에 샷 폴더가 있으면 그 상위 에피소드 폴더명을 쓴다. 없으면 ``parsed_ep``."""
    sr = Path(server_root)
    pc = project_code.strip()
    if not pc:
        return parsed_ep
    sq_dir = sr / pc / "04_sq"
    candidates = _ep_dirs_containing_shot_folder(sq_dir, shot_full)
    if not candidates:
        return parsed_ep
    if len(candidates) == 1:
        return candidates[0]

    # Prefer parsed token when it matches a real folder case-insensitively
    for c in candidates:
        if c.lower() == (parsed_ep or "").lower():
            return c

    candidates_sorted = sorted(candidates, key=lambda x: x.lower())
    logger.warning(
        "04_sq 아래 동일 샷 폴더가 여러 에피소드에 있습니다: shot=%s eps=%s → %s 사용",
        shot_full,
        candidates_sorted,
        candidates_sorted[0],
    )
    return candidates_sorted[0]


def build_shot_paths(
    server_root: str, project_code: str, shot_name: str
) -> Optional[Dict[str, Path]]:
    """샷의 서버 경로 딕셔너리를 반환한다.

    구조: server_root / project_code / 04_sq / EP / shot_name / ...
    ``04_sq`` 아래에 실제 샷 폴더가 있으면 그 부모를 EP로 쓴다(프로젝트별 네이밍 대응).
    없으면 ``parse_shot_name``의 첫 토큰 EP로 폴백(신규 샷).
    ``plate_hi`` 키는 ``plate/org/v001/hi`` 또는 ``.../mov`` 중 디스크에 있는 쪽을 가리킨다.
    shot_name을 파싱할 수 없으면 None.
    """
    parsed = parse_shot_name(shot_name)
    if not parsed:
        return None
    ep_seg = _resolve_ep_segment_for_disk(server_root, project_code, parsed["ep"], parsed["full"])
    shot_root = Path(server_root) / project_code / "04_sq" / ep_seg / parsed["full"]
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
