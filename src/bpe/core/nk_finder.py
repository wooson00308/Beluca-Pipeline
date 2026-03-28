"""NK file discovery — find the latest .nk for a given shot."""

from __future__ import annotations

import os
import re
import shutil
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

# Start Menu: "Nuke 14.1v4" 만 허용 (Hiero/Nuke Studio 등 다른 메뉴 제외)
_NUKE_START_MENU_FOLDER_RE = re.compile(r"^Nuke\s+(\d+\.\d+(?:v\d+)?)$", re.I)


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


def _is_nukex_executable_basename(filename: str, *, require_exe_suffix: bool) -> bool:
    """일반 Nuke가 아니라 NukeX 바이너리 이름인지 (소문자 ``nukex`` 로 시작)."""
    el = filename.lower()
    if "studio" in el or "hiero" in el:
        return False
    if not el.startswith("nukex"):
        return False
    if require_exe_suffix:
        return el.endswith(".exe")
    return True


def _find_nukex_exe_under_roots(search_roots: List[Path]) -> Optional[Path]:
    """search_roots 아래 ``Nuke*`` 폴더에서 ``nukex*.exe`` 만 고른다 (일반 Nuke 제외)."""
    candidates: List[Tuple[Tuple[int, int, int], Path]] = []
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
                for exe in exes:
                    if _is_nukex_executable_basename(exe.name, require_exe_suffix=True):
                        nukex_exe = exe
                        break
                if nukex_exe is None:
                    continue
                candidates.append((ver_t, nukex_exe))
        except OSError:
            continue

    if not candidates:
        return None

    best = max(candidates, key=lambda x: (x[0], str(x[1]).lower()))
    return best[1]


def find_nukex_exe() -> Optional[Path]:
    """설치된 NukeX 실행 파일 경로(Windows: ``nukex*.exe``). 없으면 ``None``.

    ``BPE_NUKEX_EXE`` 환경 변수가 있으면 해당 파일이 NukeX 이름일 때만 반환.
    """
    override = (os.environ.get("BPE_NUKEX_EXE") or "").strip()
    if override:
        p = Path(override).expanduser()
        try:
            req_exe = sys.platform == "win32"
            if p.is_file() and _is_nukex_executable_basename(p.name, require_exe_suffix=req_exe):
                return p.resolve()
            if p.is_file():
                logger.warning(
                    "BPE_NUKEX_EXE는 NukeX 바이너리만 지정하세요 — 무시함: %s",
                    p,
                )
        except OSError:
            return None
        return None
    prog_dirs = _nuke_program_dirs()
    return _find_nukex_exe_under_roots(prog_dirs)


def find_nukex_install_dir() -> Optional[Path]:
    """``find_nukex_exe()``의 부모 디렉터리(설치 폴더). 실행 파일 없으면 ``None``."""
    exe = find_nukex_exe()
    if exe is None:
        return None
    return exe.parent


def _start_menu_foundry_root() -> Path:
    """The Foundry Start Menu 프로그램 폴더 (테스트에서 monkeypatch 가능)."""
    pd = (os.environ.get("ProgramData") or r"C:\ProgramData").strip() or r"C:\ProgramData"
    return Path(pd) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "The Foundry"


def _parse_nuke_version_suffix(ver_suffix: str) -> Optional[Tuple[int, int, int]]:
    """``14.1v4`` 또는 ``15.0`` 형태를 (major, minor, patch)로 파싱. patch 없으면 0."""
    s = (ver_suffix or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d+)\.(\d+)(?:v(\d+))?$", s, re.I)
    if not m:
        return None
    patch_s = m.group(3)
    return (int(m.group(1)), int(m.group(2)), int(patch_s) if patch_s else 0)


def _program_files_nuke_exe_path(major: int, minor: int, patch: int) -> List[Path]:
    """``Nuke14.1v4`` / ``Nuke14.1.exe`` 규칙으로 Program Files 후보 경로."""
    if patch > 0:
        inst = f"Nuke{major}.{minor}v{patch}"
    else:
        inst = f"Nuke{major}.{minor}"
    exe_name = f"Nuke{major}.{minor}.exe"
    return [root / inst / exe_name for root in _nuke_program_dirs()]


def _find_nukex_via_start_menu() -> Optional[Tuple[Path, List[str]]]:
    """Start Menu의 The Foundry / ``Nuke x.xvx`` + ``NukeX x.xvx.lnk``로 Nuke 14+ 실행 경로 탐색.

    Nuke 14+ 는 ``Nuke14.1.exe --nukex`` 형태이며 ``nukex*.exe`` 단일 파일이 없을 수 있다.
    """
    if sys.platform != "win32":
        return None
    root = _start_menu_foundry_root()
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None

    candidates: List[Tuple[Tuple[int, int, int], Path]] = []
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            mdir = _NUKE_START_MENU_FOLDER_RE.match(child.name)
            if not mdir:
                continue
            ver_suffix = (mdir.group(1) or "").strip()
            lnk = child / f"NukeX {ver_suffix}.lnk"
            try:
                if not lnk.is_file():
                    continue
            except OSError:
                continue
            vt = _parse_nuke_version_suffix(ver_suffix)
            if vt is None:
                continue
            major, minor, patch = vt
            for exe_path in _program_files_nuke_exe_path(major, minor, patch):
                try:
                    if exe_path.is_file():
                        candidates.append((vt, exe_path))
                        break
                except OSError:
                    continue
    except OSError:
        return None

    if not candidates:
        return None
    best = max(candidates, key=lambda x: (x[0], str(x[1]).lower()))
    return (best[1], ["--nukex"])


def find_nukex_exe_and_args() -> Tuple[Optional[Path], List[str]]:
    """NukeX로 NK를 열 때 사용할 실행 파일과 추가 인자.

    Windows: Start Menu 기반 ``NukeX.exe`` + ``--nukex`` 우선, 없으면 legacy ``nukex*.exe``.
    ``BPE_NUKEX_EXE``가 있으면 ``find_nukex_exe()`` 규칙만 사용 (추가 인자 없음).
    """
    override = (os.environ.get("BPE_NUKEX_EXE") or "").strip()
    if override:
        legacy = find_nukex_exe()
        if legacy is not None:
            return (legacy, [])
        return (None, [])

    sm = _find_nukex_via_start_menu()
    if sm is not None:
        return (sm[0], sm[1])

    legacy = find_nukex_exe()
    if legacy is not None:
        return (legacy, [])
    return (None, [])


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


def _resolve_shot_root(server_root: str, project_code: str, shot_name: str) -> Optional[Path]:
    """``find_latest_nk_path`` / ``find_shot_folder``와 동일한 방식으로 샷 루트를 구한다."""
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
    return shot_root


def find_shot_folder(shot_name: str, project_code: str, server_root: str) -> Optional[Path]:
    """샷 작업 폴더 경로: ``comp/devl/nuke`` 가 있으면 그 경로, 없으면 ``shot_root``."""
    sn = (shot_name or "").strip()
    pc = (project_code or "").strip()
    sr = (server_root or "").strip()
    if not sn or not sr:
        return None

    shot_root = _resolve_shot_root(sr, pc, sn)
    if shot_root is None:
        return None

    nuke_dir = shot_root / "comp" / "devl" / "nuke"
    try:
        if nuke_dir.is_dir():
            return nuke_dir.resolve()
    except OSError:
        pass
    try:
        return shot_root.resolve()
    except OSError:
        return shot_root


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


def _version_ints_from_nk_path(p: Path) -> List[int]:
    """파일명과 직계 부모 폴더명에서 ``v###`` 숫자 목록 (``find_latest_nk_path`` 정렬과 동일)."""
    name_nums = [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.name)]
    parent_nums = [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.parent.name)]
    return name_nums + parent_nums


def find_latest_comp_version_display(
    shot_name: str, project_code: str, server_root: str
) -> Optional[str]:
    """``find_latest_nk_path``와 동일한 NK를 기준으로 표시용 ``v###`` 문자열을 반환한다.

    NK가 없거나 파일/부모에 ``v###``가 없으면 ``None`` (UI는 ``—`` 유지).
    """
    p = find_latest_nk_path(shot_name, project_code, server_root)
    if p is None:
        return None
    merged = _version_ints_from_nk_path(p)
    if not merged:
        return None
    return f"v{max(merged):03d}"


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

    shot_root = _resolve_shot_root(sr, pc, sn)
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
            merged = _version_ints_from_nk_path(p)
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
    """최신 NK를 찾아 연다.

    Windows: NukeX 실행 파일로만 연다. 일반 Nuke나 파일 연결 프로그램으로는 열지 않는다.
    """
    path = find_latest_nk_path(shot_name, project_code, server_root)
    if path is None:
        return None
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform == "win32":
            exe, extra_args = find_nukex_exe_and_args()
            if exe is not None:
                subprocess.Popen([str(exe), *extra_args, str(path)], close_fds=True)
            else:
                logger.warning(
                    "NukeX 실행 파일을 찾지 못해 NK를 열지 않음: %s",
                    path,
                )
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        logger.warning("NK 파일 열기 실패: %s", path)
    return path


# ---------------------------------------------------------------------------
# Plate MOV + RV
# ---------------------------------------------------------------------------

_PLATE_VERSION_DIR_RE = re.compile(r"^v\d+$", re.IGNORECASE)


def _find_rv_exe() -> Optional[str]:
    """RV 실행 파일 경로 탐색 (PATH → 공통 설치 경로 → Program Files glob 순)."""
    rv = shutil.which("rv") or shutil.which("rv.exe")
    if rv:
        return rv
    if sys.platform == "win32":
        for c in (
            r"C:\Program Files\RV\bin\rv.exe",
            r"C:\Program Files\Autodesk\RV\bin\rv.exe",
            r"C:\Program Files\ShotGrid\RV\bin\rv.exe",
        ):
            p = Path(c)
            if p.is_file():
                return str(p)
        for pf in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            root = Path(pf)
            try:
                if not root.is_dir():
                    continue
                hits = sorted(root.glob("**/bin/rv.exe"))
                if hits:
                    return str(hits[0])
            except OSError:
                continue
    elif sys.platform == "darwin":
        for c in (
            "/Applications/RV.app/Contents/MacOS/RV",
            "/Applications/Autodesk RV.app/Contents/MacOS/RV",
        ):
            p = Path(c)
            if p.is_file():
                return str(p)
    return None


def find_plate_mov(shot_name: str, project_code: str, server_root: str) -> Optional[Path]:
    """plate/org/vXXX/mov/*.mov 중 최신 버전의 첫 파일 반환.

    버전 내림차순 탐색; mov 폴더가 없거나 비어 있으면 이전 버전으로 폴백.
    """
    paths = build_shot_paths(server_root, project_code, shot_name)
    if paths is None:
        return None
    plate_org = paths["shot_root"] / "plate" / "org"
    if not plate_org.is_dir():
        return None
    try:
        children = list(plate_org.iterdir())
    except OSError:
        return None
    version_dirs = sorted(
        [d for d in children if d.is_dir() and _PLATE_VERSION_DIR_RE.match(d.name)],
        key=lambda d: int(d.name[1:]),
        reverse=True,
    )
    for vdir in version_dirs:
        mov_dir = vdir / "mov"
        if not mov_dir.is_dir():
            continue
        try:
            movs = [p for p in mov_dir.glob("*.mov") if p.is_file()]
        except OSError:
            continue
        if movs:
            return sorted(movs)[0]
    return None


def open_plate_in_rv(shot_name: str, project_code: str, server_root: str) -> bool:
    """플레이트 MOV를 RV로 실행. RV 없거나 MOV 없으면 False."""
    mov = find_plate_mov(shot_name, project_code, server_root)
    if mov is None:
        logger.warning(
            "RV: plate/org 아래 .mov 없음 또는 샷 경로 없음 (shot=%s project=%s root=%s)",
            shot_name,
            project_code,
            server_root,
        )
        return False
    rv_exe = _find_rv_exe()
    if rv_exe is None:
        logger.warning(
            "RV 실행 파일을 찾지 못함 — PATH·Program Files 확인 (mov=%s)",
            mov,
        )
        return False
    try:
        subprocess.Popen([rv_exe, str(mov)], close_fds=True)
    except OSError as e:
        logger.warning("RV 실행 실패: %s", e)
        return False
    return True


def _version_ints_from_mov_filename(p: Path) -> List[int]:
    """렌더 MOV 파일명에서 ``v###`` 숫자 목록."""
    return [int(m.group(1)) for m in _NK_VERSION_RE.finditer(p.name)]


def find_comp_render_mov(
    shot_name: str,
    project_code: str,
    server_root: str,
    *,
    version_code: Optional[str] = None,
) -> Optional[Path]:
    """``comp/devl/renders`` 아래에서 렌더 MOV를 찾는다.

    Parameters
    ----------
    version_code : str | None
        ShotGrid Version 엔티티의 ``code`` 값 (예: ``"S100_0140_comp_v007"``).
        지정하면 해당 버전 파일만 반환 — stem 완전 일치 우선, 포함 일치 폴백.
        None이면 버전 번호 최대(동률 시 mtime) 파일을 반환.

    샷 루트는 ``_resolve_shot_root`` (``build_shot_paths`` → BFS 휴리스틱)로 구한다.
    """
    shot_root = _resolve_shot_root(server_root, project_code, shot_name)
    if shot_root is None:
        return None
    renders = shot_root / "comp" / "devl" / "renders"
    if not renders.is_dir():
        return None
    try:
        movs = [p for p in renders.glob("*.mov") if p.is_file()]
    except OSError:
        return None
    if not movs:
        return None

    if version_code is not None:
        vc_lower = version_code.strip().lower()
        exact = [p for p in movs if p.stem.lower() == vc_lower]
        if exact:
            return exact[0]
        contained = [p for p in movs if vc_lower in p.stem.lower()]
        if contained:
            return contained[0]
        return None

    def _sort_key(p: Path) -> Tuple[int, float]:
        try:
            merged = _version_ints_from_mov_filename(p)
            vmax = max(merged) if merged else -1
            mt = os.path.getmtime(p)
        except OSError:
            vmax, mt = -1, 0.0
        return (vmax, mt)

    return max(movs, key=_sort_key)


def open_comp_render_in_rv(
    shot_name: str,
    project_code: str,
    server_root: str,
    *,
    version_code: Optional[str] = None,
) -> bool:
    """comp 렌더 MOV를 RV로 실행. RV 없거나 MOV 없으면 False.

    version_code 지정 시 해당 버전 파일만 열며, 파일이 없으면 False를 반환한다.
    """
    mov = find_comp_render_mov(shot_name, project_code, server_root, version_code=version_code)
    if mov is None:
        logger.warning(
            "RV: comp/devl/renders 아래 .mov 없음 또는 샷 경로 없음 "
            "(shot=%s project=%s root=%s version_code=%s)",
            shot_name,
            project_code,
            server_root,
            version_code,
        )
        return False
    rv_exe = _find_rv_exe()
    if rv_exe is None:
        logger.warning(
            "RV 실행 파일을 찾지 못함 — PATH·Program Files 확인 (mov=%s)",
            mov,
        )
        return False
    try:
        subprocess.Popen([rv_exe, str(mov)], close_fds=True)
    except OSError as e:
        logger.warning("RV 실행 실패: %s", e)
        return False
    return True
