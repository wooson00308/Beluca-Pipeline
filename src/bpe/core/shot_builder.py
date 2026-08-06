# @cursor-change: 2026-08-06, 0.2.x, 태스크별 샷 빌드 — task slug·경로
"""Shot name parsing and server-path construction."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shot_builder")

_PLATE_VERSION_DIR_RE = re.compile(r"^v\d+$", re.IGNORECASE)

DEFAULT_TASK_FOLDER = "comp"
_COMP_ALIASES = frozenset(
    {
        "comp",
        "compositing",
        "composite",
        "comp2d",
        "comp_2d",
        "2dcomp",
    }
)
_EXCLUDED_TASKS = frozenset({"fx", "matte"})
_WIN_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
_NON_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def canonical_task_slug(task_content: str) -> str:
    """SG Task Name → 샷 폴더 아래 작업 폴더 이름.

    판단 불가·제외·예약어·comp 별칭이면 ``comp`` (기존 동작과 동일).
    """
    raw = unicodedata.normalize("NFKC", task_content or "").strip().lower()
    if not raw:
        return DEFAULT_TASK_FOLDER
    slug = _NON_SLUG_RE.sub("_", raw)
    slug = _MULTI_UNDERSCORE_RE.sub("_", slug).strip("_.")
    if not slug:
        return DEFAULT_TASK_FOLDER
    if slug in _COMP_ALIASES or slug in _EXCLUDED_TASKS or slug in _WIN_RESERVED:
        return DEFAULT_TASK_FOLDER
    return slug


def _resolve_plate_hi(shot_root: Path) -> Path:
    """
    ``plate/org/v###`` 중 최신 버전 아래 ``hi`` 또는 ``h`` 폴더를 반환.
    EXR 시퀀스와 MOV 클립 모두 hi/h 폴더에 위치한다.
    버전 폴더가 없으면 ``v001/hi``(신규 샷 기본값).
    """
    plate_org = shot_root / "plate" / "org"
    if plate_org.is_dir():
        try:
            version_dirs = sorted(
                [
                    d
                    for d in plate_org.iterdir()
                    if d.is_dir() and _PLATE_VERSION_DIR_RE.match(d.name)
                ],
                key=lambda d: int(d.name[1:]),
                reverse=True,
            )
            for vdir in version_dirs:
                for sub in ("hi", "h"):
                    candidate = vdir / sub
                    if candidate.is_dir():
                        return candidate
        except OSError:
            pass
    return shot_root / "plate" / "org" / "v001" / "hi"


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


def _resolve_task_segment_for_disk(shot_root: Path, task_slug: str) -> str:
    """샷 루트 직계 자식 중 대소문자만 다른 폴더가 있으면 그 실제 이름을 쓴다."""
    want = (task_slug or "").strip().lower()
    if not want or want == DEFAULT_TASK_FOLDER:
        return DEFAULT_TASK_FOLDER
    try:
        if not shot_root.is_dir():
            return want
        for child in shot_root.iterdir():
            if child.is_dir() and child.name.lower() == want:
                return child.name
    except OSError:
        pass
    return want


def build_shot_paths(
    server_root: str,
    project_code: str,
    shot_name: str,
    task: str = DEFAULT_TASK_FOLDER,
) -> Optional[Dict[str, Path]]:
    """샷의 서버 경로 딕셔너리를 반환한다.

    구조: server_root / project_code / 04_sq / EP / shot_name / {task} / devl / ...
    ``04_sq`` 아래에 실제 샷 폴더가 있으면 그 부모를 EP로 쓴다(프로젝트별 네이밍 대응).
    없으면 ``parse_shot_name``의 첫 토큰 EP로 폴백(신규 샷).
    ``task`` 가 ``comp`` 이면 리터럴 ``comp`` 경로를 쓰고(기존과 동일),
    그 외에는 디스크에 대소문자만 다른 폴더가 있으면 그 이름을 재사용한다.
    ``plate_hi`` 키는 ``plate/org`` 아래 최신 ``v###/hi`` 또는 ``.../mov`` 중
    디스크에 있는 쪽을 가리킨다.
    shot_name을 파싱할 수 없으면 None.
    """
    parsed = parse_shot_name(shot_name)
    if not parsed:
        return None
    ep_seg = _resolve_ep_segment_for_disk(server_root, project_code, parsed["ep"], parsed["full"])
    shot_root = Path(server_root) / project_code / "04_sq" / ep_seg / parsed["full"]
    task_raw = (task or DEFAULT_TASK_FOLDER).strip() or DEFAULT_TASK_FOLDER
    if task_raw == DEFAULT_TASK_FOLDER:
        task_seg = DEFAULT_TASK_FOLDER
    else:
        task_seg = _resolve_task_segment_for_disk(shot_root, task_raw)
    task_root = shot_root / task_seg
    nuke_dir = task_root / "devl" / "nuke"
    return {
        "shot_root": shot_root,
        "task_root": task_root,
        "nuke_dir": nuke_dir,
        "plate_hi": _resolve_plate_hi(shot_root),
        "edit": shot_root / "edit",
        "renders": task_root / "devl" / "renders",
        "element": task_root / "devl" / "element",
    }


def comp_devl_structure_exists(paths: Dict[str, Path]) -> bool:
    """작업 폴더(``task_root`` 또는 ``comp``) 아래 nuke·renders·element 가 모두 있으면 True."""
    shot = paths["shot_root"]
    task_root = paths.get("task_root") or (shot / DEFAULT_TASK_FOLDER)
    if not task_root.is_dir():
        return False
    devl = task_root / "devl"
    if not devl.is_dir():
        return False
    return paths["nuke_dir"].is_dir() and paths["renders"].is_dir() and paths["element"].is_dir()


def ensure_comp_folder_structure(paths: Dict[str, Path], nk_version: str = "v001") -> List[str]:
    """
    ``{task}/devl/nuke/{nk_version}``, ``renders``, ``element`` 가 없으면 생성한다.

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
