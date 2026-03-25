"""NK file discovery — find the latest .nk for a given shot."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import List, Optional, Tuple

from bpe.core.logging import get_logger
from bpe.core.shot_builder import build_shot_paths

logger = get_logger("nk_finder")

# ---------------------------------------------------------------------------
# Version regex — matches v001, V12, etc.
# ---------------------------------------------------------------------------
_NK_VERSION_RE = re.compile(r"[vV](\d+)")


# ---------------------------------------------------------------------------
# Junk-file filter
# ---------------------------------------------------------------------------

def _nk_is_junk_file(path: Path) -> bool:
    """autosave / backup 등 무시해야 할 NK 파일인지 판별."""
    name = path.name
    low = name.lower()
    if "~" in name:
        return True
    if ".autosave" in low or low.endswith(".nk.autosave"):
        return True
    if "autosave" in low:
        return True
    return False


# ---------------------------------------------------------------------------
# Network drive detection (Windows only)
# ---------------------------------------------------------------------------

def _path_is_likely_network(path: Path) -> bool:
    """Windows 네트워크 드라이브(UNC 경로 또는 매핑 드라이브) 여부를 추정한다."""
    if sys.platform != "win32":
        return False
    s = str(path)
    if s.startswith("\\\\"):
        return True
    try:
        import ctypes  # noqa: local import — Windows 전용
        drive = os.path.splitdrive(s)[0]
        if drive and len(drive) == 2 and drive[1] == ":":
            DRIVE_REMOTE = 4
            dtype = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")  # type: ignore[union-attr]
            return dtype == DRIVE_REMOTE
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Heuristic shot-root finder (BFS)
# ---------------------------------------------------------------------------

def _find_shot_root_heuristic(
    server_root: str,
    project_code: str,
    shot_name: str,
    *,
    max_depth: int = 10,
) -> Optional[Path]:
    """build_shot_paths가 실패할 때 BFS로 샷 폴더를 탐색한다."""
    sr = Path(server_root).expanduser()
    pc = (project_code or "").strip()
    needle = (shot_name or "").strip()
    if not needle:
        return None

    if pc:
        base = sr / pc
        if not base.is_dir():
            base = sr
    else:
        base = sr
    if not base.is_dir():
        return None

    nlow = needle.lower()
    q: deque[Tuple[Path, int]] = deque([(base, 0)])
    seen: set = set()

    while q:
        p, depth = q.popleft()
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen:
            continue
        seen.add(rp)
        try:
            if p.name.lower() == nlow:
                return p
        except OSError:
            continue
        if depth >= max_depth:
            continue
        try:
            for ch in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                if ch.is_dir():
                    q.append((ch, depth + 1))
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# NK search-root candidates
# ---------------------------------------------------------------------------

def _nk_search_roots_from_shot_root(shot_root: Path) -> List[Path]:
    """shot_root 하위에서 NK 파일을 찾아볼 디렉토리 목록을 반환한다."""
    roots: List[Path] = []
    for rel in (
        shot_root / "comp" / "devl" / "nuke",
        shot_root / "comp",
        shot_root / "comp" / "devl",
        shot_root / "work",
        shot_root / "scripts",
    ):
        try:
            p = Path(rel).resolve()
            if p.is_dir():
                roots.append(p)
        except OSError:
            continue
    if not roots:
        try:
            roots = [shot_root.resolve()]
        except OSError:
            pass
    return roots


# ---------------------------------------------------------------------------
# Core finder
# ---------------------------------------------------------------------------

def find_latest_nk_path(
    shot_name: str, project_code: str, server_root: str
) -> Optional[Path]:
    """샷 폴더 하위에서 최신 .nk 경로를 탐색한다.

    버전 접미사(v###)가 있으면 최대 버전, 없으면 mtime 기준.
    build_shot_paths 실패 시 BFS 휴리스틱으로 폴백.
    """
    sn = (shot_name or "").strip()
    pc = (project_code or "").strip()
    sr = (server_root or "").strip()
    if not sn or not sr:
        return None

    shot_root: Optional[Path] = None
    if pc:
        bp = build_shot_paths(sr, pc, sn)
        if bp:
            cand = bp["shot_root"]
            try:
                if cand.exists():
                    shot_root = cand
            except OSError:
                shot_root = None
    if shot_root is None:
        shot_root = _find_shot_root_heuristic(sr, pc, sn)
    if shot_root is None:
        return None

    roots = _nk_search_roots_from_shot_root(shot_root)
    if not roots:
        return None

    seen: set = set()
    nk_files: List[Path] = []
    for root in roots:
        try:
            for p in root.rglob("*.nk"):
                if not p.is_file():
                    continue
                if _nk_is_junk_file(p):
                    continue
                try:
                    rp = p.resolve()
                except OSError:
                    rp = p
                if rp in seen:
                    continue
                seen.add(rp)
                nk_files.append(p)
        except OSError:
            continue

    if not nk_files:
        return None

    needle = sn.lower()
    matched = [
        p for p in nk_files
        if needle in p.stem.lower() or needle in p.name.lower()
    ]
    pool = matched if matched else nk_files

    def _sort_key(p: Path) -> Tuple[int, float]:
        try:
            name_nums = [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.name)]
            parent_nums = [
                int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.parent.name)
            ]
            merged = name_nums + parent_nums
            vmax = max(merged) if merged else -1
            mt = os.path.getmtime(p)
        except OSError:
            vmax, mt = -1, 0.0
        return (vmax, mt)

    return max(pool, key=_sort_key)


# ---------------------------------------------------------------------------
# Open in OS default app
# ---------------------------------------------------------------------------

def find_latest_nk_and_open(
    shot_name: str, project_code: str, server_root: str
) -> Optional[Path]:
    """최신 NK를 찾아 OS 기본 앱으로 연다. 읽기 전용 — 파일을 수정하지 않는다."""
    path = find_latest_nk_path(shot_name, project_code, server_root)
    if path is None:
        return None
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        logger.warning("NK 파일 열기 실패: %s", path)
    return path
