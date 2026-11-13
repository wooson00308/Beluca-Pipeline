"""컨펌 창용 재료 찾기 — 샷 폴더에서 원본·편집본·버전 영상을 찾는다 (읽기만).

외주 납품 모양(``comp/v002/<샷>_comp_v002.mov``)과 내부 모양
(``comp/devl/renders/<샷>_comp_v017.mov``)을 둘 다 본다. 기존 ``nk_finder`` 의
찾기 규칙(RV 열기·업로드가 같이 씀)은 건드리지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

VIDEO_EXTS = (".mov", ".mp4", ".mxf", ".mkv", ".m4v")
_VERSION_RE = re.compile(r"[_.\-]v(\d{2,4})(?=[_.\-]|$)", re.IGNORECASE)
_VERSION_DIR_RE = re.compile(r"^v(\d{2,4})$", re.IGNORECASE)
_LUT_RE = re.compile(r"[_.\-]lut(?=[_.\-]|$)", re.IGNORECASE)
_COMP_DIRS = ("comp/devl/renders", "comp/renders", "comp/devl/review", "comp/review", "comp")


class VersionMovie(NamedTuple):
    version: int
    path: Path
    has_lut_baked: bool

    @property
    def label(self) -> str:
        return f"v{self.version:03d}"


class ShotMedia(NamedTuple):
    shot_root: Optional[Path]
    current: Optional[VersionMovie]
    previous: Optional[VersionMovie]
    versions: List[VersionMovie]
    org: Optional[Path]
    edit: Optional[Path]


def parse_version(name: str) -> Optional[int]:
    """파일·폴더 이름의 마지막 ``v###`` 번호."""
    found = _VERSION_RE.findall(Path(name).stem if "." in name else name)
    if not found:
        m = _VERSION_DIR_RE.match(name)
        return int(m.group(1)) if m else None
    return int(found[-1])


def is_lut_baked(name: str) -> bool:
    """이름에 ``_lut`` 가 붙은(룩업이 이미 입혀진) 영상인가."""
    return bool(_LUT_RE.search(Path(name).stem))


def shot_root_from_movie(movie: Path) -> Optional[Path]:
    """작업본 경로에서 샷 폴더(``comp`` 의 부모)를 찾는다."""
    parts = movie.parts
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower() == "comp":
            return Path(*parts[:i])
    return None


def _videos_in(folder: Path) -> List[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    except OSError:
        return []


def _version_dirs(folder: Path) -> List[Path]:
    """``v###`` 하위 폴더 — 번호 큰 것부터."""
    try:
        dirs = [d for d in folder.iterdir() if d.is_dir() and _VERSION_DIR_RE.match(d.name)]
    except OSError:
        return []
    return sorted(dirs, key=lambda d: int(d.name[1:]), reverse=True)


def find_versions(shot_root: Path) -> List[VersionMovie]:
    """샷의 comp 버전 영상 — 번호 순. 같은 번호는 룩업 안 입힌 것을 우선한다."""
    best: Dict[int, VersionMovie] = {}

    def offer(path: Path, version: Optional[int]) -> None:
        if version is None:
            return
        cand = VersionMovie(version, path, is_lut_baked(path.name))
        cur = best.get(version)
        if cur is None or (cur.has_lut_baked and not cand.has_lut_baked):
            best[version] = cand

    for rel in _COMP_DIRS:
        folder = shot_root / rel
        for p in _videos_in(folder):
            offer(p, parse_version(p.name))
    for vdir in _version_dirs(shot_root / "comp"):
        dir_version = parse_version(vdir.name)
        for p in _videos_in(vdir):
            offer(p, parse_version(p.name) or dir_version)
    return [best[k] for k in sorted(best)]


def _subdirs(folder: Path) -> List[str]:
    try:
        return sorted(d.name for d in folder.iterdir() if d.is_dir())
    except OSError:
        return []


def _latest_in_versioned(
    folder: Path, subdirs: tuple, *, any_subdir: bool = False
) -> Optional[Path]:
    """``folder/v###[/sub]`` 에서 가장 최신 버전의 첫 영상. 없으면 ``folder`` 바로 아래.

    *subdirs* 는 먼저 볼 하위 폴더 이름(빈 글 = 버전 폴더 바로 아래). *any_subdir* 면
    거기에 없을 때 버전 폴더의 다른 하위 폴더도 이름순으로 찾아본다 — 프로젝트마다
    영상을 두는 폴더 이름(mov / hi / lo …)이 달라서다.
    """
    for vdir in _version_dirs(folder):
        names = list(subdirs)
        if any_subdir:
            names += [n for n in _subdirs(vdir) if n not in names]
        for sub in names:
            vids = _videos_in(vdir / sub) if sub else _videos_in(vdir)
            vids = [v for v in vids if not is_lut_baked(v.name)] or vids
            if vids:
                return vids[0]
    vids = _videos_in(folder)
    vids = [v for v in vids if not is_lut_baked(v.name)] or vids
    return vids[-1] if vids else None


def find_org(shot_root: Path) -> Optional[Path]:
    """원본 플레이트 영상. 최신 버전 폴더에서 ``mov`` → ``hi`` → 바로 아래 → ``lo`` → 그 밖의

    하위 폴더 순으로 찾고, 없으면 이전 버전, 그래도 없으면 ``plate/org`` 바로 아래.
    """
    return _latest_in_versioned(
        shot_root / "plate" / "org", ("mov", "hi", "", "lo"), any_subdir=True
    )


def find_edit(shot_root: Path) -> Optional[Path]:
    """편집본 영상: ``edit/v###`` → ``edit``."""
    return _latest_in_versioned(shot_root / "edit", ("",))


def find_shot_media(current_movie: Path, shot_root: Optional[Path] = None) -> ShotMedia:
    """지금 보는 작업본에서 출발해 같은 샷의 재료를 모은다."""
    root = shot_root or shot_root_from_movie(current_movie)
    cur_version = parse_version(current_movie.name)
    if cur_version is None:
        cur_version = parse_version(current_movie.parent.name)
    current = VersionMovie(cur_version or 0, current_movie, is_lut_baked(current_movie.name))
    if root is None:
        return ShotMedia(None, current, None, [current], None, None)

    versions = find_versions(root)
    if not any(v.path == current_movie for v in versions):
        versions = [v for v in versions if v.version != current.version] + [current]
        versions.sort(key=lambda v: v.version)
    else:
        current = next(v for v in versions if v.path == current_movie)
    older = [v for v in versions if v.version < current.version]
    previous = older[-1] if older else None
    return ShotMedia(root, current, previous, versions, find_org(root), find_edit(root))
