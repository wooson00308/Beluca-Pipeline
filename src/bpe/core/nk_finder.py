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

# project_2026 등 — 마이 태스크 서버 루트 자동 탐색용
_PROJECT_YEAR_DIR_RE = re.compile(r"^project_(\d{4})$", re.I)

# Nuke15.1v4 폴더명에서 버전 추출
_NUKE_FOLDER_VER_RE = re.compile(r"Nuke(\d+)\.(\d+)(?:v(\d+))?", re.I)


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
        import ctypes  # Windows 전용 (순환/플랫폼 의존 지연 import)

        drive = os.path.splitdrive(s)[0]
        if drive and len(drive) == 2 and drive[1] == ":":
            DRIVE_REMOTE = 4
            dtype = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")  # type: ignore[union-attr]
            return dtype == DRIVE_REMOTE
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Auto-detect VFX server root (Windows: drive:\vfx\project_YYYY\)
# ---------------------------------------------------------------------------


def _windows_drive_roots() -> List[Path]:
    """각 드라이브 루트 경로 (테스트에서 monkeypatch 가능)."""
    return [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]


def _find_server_root_from_drive_roots(
    project_code: str,
    drive_roots: List[Path],
) -> Optional[str]:
    """``drive_roots`` 각각에 대해 ``vfx/project_YYYY/<project_code>`` 탐색, 최신 연도 경로 반환."""
    pc = (project_code or "").strip()
    if not pc:
        return None

    best_year = -1
    best: Optional[str] = None

    for drive_root in drive_roots:
        vfx = drive_root / "vfx"
        try:
            if not vfx.is_dir():
                continue
            for child in vfx.iterdir():
                if not child.is_dir():
                    continue
                m = _PROJECT_YEAR_DIR_RE.match(child.name)
                if not m:
                    continue
                year = int(m.group(1))
                proj_dir = child / pc
                try:
                    if not proj_dir.is_dir():
                        continue
                except OSError:
                    continue
                if year > best_year:
                    best_year = year
                    best = str(child.resolve())
        except OSError:
            continue

    return best


def find_server_root_auto(project_code: str) -> Optional[str]:
    """드라이브를 스캔해 ``vfx/project_YYYY/<project_code>`` 가 있는 최신 연도 루트를 반환.

    예: ``W:\\vfx\\project_2026`` (아래에 ``SBS_030`` 폴더가 있으면 선택)

    Windows 전용. 다른 OS는 ``None``.
    """
    if sys.platform != "win32":
        return None
    return _find_server_root_from_drive_roots(project_code, _windows_drive_roots())


# ---------------------------------------------------------------------------
# Find NukeX executable (Windows Program Files)
# ---------------------------------------------------------------------------


def _nuke_program_dirs() -> List[Path]:
    """Nuke 설치 상위 디렉터리 후보 (예: C:\\Program Files)."""
    roots: List[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            roots.append(Path(raw))
    return roots


def _parse_nuke_folder_version(name: str) -> Tuple[int, int, int]:
    m = _NUKE_FOLDER_VER_RE.search(name)
    if not m:
        return (0, 0, 0)
    patch_s = m.group(3)
    return (int(m.group(1)), int(m.group(2)), int(patch_s) if patch_s else 0)


def _find_nukex_exe_under_roots(search_roots: List[Path]) -> Optional[Path]:
    """search_roots 아래 ``Nuke*`` 폴더에서 NukeX 우선 실행 파일을 고른다."""
    candidates: List[Tuple[Tuple[int, int, int], int, Path]] = []
    # tuple: (version, prefer_nukex_flag 1=nukeX in name, path)
    for base in search_roots:
        try:
            if not base.is_dir():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                cname = child.name
                if not cname.lower().startswith("nuke"):
                    continue
                ver_t = _parse_nuke_folder_version(cname)
                low = cname.lower()
                if "studio" in low or "hiero" in low or "indie" in low:
                    continue
                try:
                    exes = sorted(child.glob("*.exe"))
                except OSError:
                    continue
                nukex_exe: Optional[Path] = None
                nuke_exe: Optional[Path] = None
                for exe in exes:
                    el = exe.name.lower()
                    if "studio" in el or "hiero" in el:
                        continue
                    if el.startswith("nukex") and el.endswith(".exe"):
                        nukex_exe = exe
                        break
                    if el.startswith("nuke") and el.endswith(".exe") and nuke_exe is None:
                        nuke_exe = exe
                chosen = nukex_exe or nuke_exe
                if chosen is None:
                    continue
                prefer = 1 if nukex_exe is not None else 0
                candidates.append((ver_t, prefer, chosen))
        except OSError:
            continue

    if not candidates:
        return None

    # 최신 버전 폴더, 같은 버전이면 NukeX 이름 우선
    best = max(candidates, key=lambda x: (x[0], x[1], str(x[2]).lower()))
    return best[2]


def find_nukex_exe() -> Optional[Path]:
    """설치된 NukeX(또는 Nuke) 실행 파일 경로. 없으면 ``None``.

    ``BPE_NUKEX_EXE`` 환경 변수가 있으면 그 경로를 그대로 반환(파일이 존재할 때만).
    """
    override = (os.environ.get("BPE_NUKEX_EXE") or "").strip()
    if override:
        p = Path(override).expanduser()
        try:
            if p.is_file():
                return p.resolve()
        except OSError:
            return None
        return None
    return _find_nukex_exe_under_roots(_nuke_program_dirs())


def find_nukex_install_dir() -> Optional[Path]:
    """``find_nukex_exe()``의 부모 디렉터리(설치 폴더). 실행 파일 없으면 ``None``."""
    exe = find_nukex_exe()
    if exe is None:
        return None
    return exe.parent


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


def find_latest_nk_path(shot_name: str, project_code: str, server_root: str) -> Optional[Path]:
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
    matched = [p for p in nk_files if needle in p.stem.lower() or needle in p.name.lower()]
    pool = matched if matched else nk_files

    def _sort_key(p: Path) -> Tuple[int, float]:
        try:
            name_nums = [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.name)]
            parent_nums = [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.parent.name)]
            merged = name_nums + parent_nums
            vmax = max(merged) if merged else -1
            mt = os.path.getmtime(p)
        except OSError:
            vmax, mt = -1, 0.0
        return (vmax, mt)

    return max(pool, key=_sort_key)


# ---------------------------------------------------------------------------
# Open with NukeX / OS default
# ---------------------------------------------------------------------------


def find_latest_nk_and_open(shot_name: str, project_code: str, server_root: str) -> Optional[Path]:
    """최신 NK를 찾아 연다. Windows에서는 NukeX(또는 Nuke) 실행 파일로 연 뒤, 실패 시 기본 앱."""
    path = find_latest_nk_path(shot_name, project_code, server_root)
    if path is None:
        return None
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform == "win32":
            exe = find_nukex_exe()
            if exe is not None:
                subprocess.Popen([str(exe), str(path)], close_fds=True)
            else:
                logger.warning("NukeX 실행 파일을 찾지 못함 — 기본 앱으로 연다: %s", path)
                os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        logger.warning("NK 파일 열기 실패: %s", path)
    return path
