# @cursor-change: 2026-08-09, 0.13.x, BPE 기동 시 ~/.nuke/bpe 슬림 동기화
"""BPE Nuke 플러그인을 ``~/.nuke/bpe`` 에 가볍게 맞춘다.

원본 미디어와 무관. ``core/`` + ``nuke_plugin/`` 만 복사하고 스탬프가 같으면 즉시 반환.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from bpe.core.logging import get_logger

logger = get_logger("nuke_plugin_install")

STAMP_NAME = ".bpe_nuke_stamp"
HOOK_MARKER = "# BPE_HOOK_START"
HOOK_END = "# BPE_HOOK_END"

_HOOK_BLOCK = """
# BPE_HOOK_START
try:
    from bpe.nuke_plugin.menu_setup import add_setup_pro_menu
    add_setup_pro_menu()
    from bpe.nuke_plugin.tool_hooks import reload_tool_hooks
    reload_tool_hooks()
except Exception as _bpe_err:
    import nuke
    nuke.tprint("[BPE] menu.py hook 로드 실패: " + str(_bpe_err))
# BPE_HOOK_END
"""


def nuke_home() -> Path:
    return Path.home() / ".nuke"


def nuke_bpe_dir(nuke_dir: Optional[Path] = None) -> Path:
    return (nuke_dir or nuke_home()) / "bpe"


def find_bpe_package_src() -> Optional[Path]:
    """번들 또는 소스 트리에서 ``bpe`` 패키지 루트를 찾는다."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "bpe"
        if (bundled / "__init__.py").is_file():
            return bundled
    # src/bpe/core/nuke_plugin_install.py → parents[1] == bpe
    here = Path(__file__).resolve()
    pkg = here.parents[1]
    if (pkg / "__init__.py").is_file() and (pkg / "nuke_plugin").is_dir():
        return pkg
    return None


def _package_version(src: Path) -> str:
    try:
        from bpe import __version__

        if __version__:
            return str(__version__).strip()
    except Exception:
        pass
    for candidate in (
        src.parent.parent / "VERSION.txt",
        Path(getattr(sys, "_MEIPASS", "") or ".") / "VERSION.txt",
    ):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip() or "0.0.0"
        except OSError:
            continue
    return "0.0.0"


def _fingerprint(src: Path) -> str:
    """nuke_plugin + core 의 py 파일 mtime/size 짧은 해시."""
    parts: List[str] = []
    for name in ("nuke_plugin", "core"):
        base = src / name
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            try:
                st = p.stat()
                rel = p.relative_to(src).as_posix()
                parts.append("{}:{}:{}".format(rel, st.st_mtime_ns, st.st_size))
            except OSError:
                continue
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def compute_stamp(src: Path) -> str:
    return "{}|{}".format(_package_version(src), _fingerprint(src))


def read_stamp(dest: Path) -> str:
    stamp_path = dest / STAMP_NAME
    try:
        if stamp_path.is_file():
            return stamp_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def write_stamp(dest: Path, stamp: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / STAMP_NAME).write_text(stamp + "\n", encoding="utf-8")


def ensure_menu_hook(nuke_dir: Optional[Path] = None) -> bool:
    """menu.py 에 BPE hook 이 없으면 추가. 추가했으면 True."""
    nd = nuke_dir or nuke_home()
    nd.mkdir(parents=True, exist_ok=True)
    menu_py = nd / "menu.py"
    if menu_py.is_file():
        try:
            text = menu_py.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if HOOK_MARKER in text:
            return False
        try:
            suffix = _HOOK_BLOCK if text.endswith("\n") else "\n" + _HOOK_BLOCK.lstrip("\n")
            with menu_py.open("a", encoding="utf-8") as fh:
                fh.write(suffix)
            return True
        except OSError as exc:
            logger.warning("menu.py hook 추가 실패: %s", exc)
            return False
    try:
        menu_py.write_text(_HOOK_BLOCK.lstrip("\n"), encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("menu.py 생성 실패: %s", exc)
        return False


def _copy_slim(src: Path, dest: Path) -> None:
    """dest 를 비우고 __init__.py / nuke_plugin / core 만 복사."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    init_py = src / "__init__.py"
    if init_py.is_file():
        shutil.copy2(init_py, dest / "__init__.py")
    for name in ("nuke_plugin", "core"):
        src_dir = src / name
        if not src_dir.is_dir():
            continue
        shutil.copytree(
            src_dir,
            dest / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )


def ensure_nuke_plugin(
    *,
    src: Optional[Path] = None,
    nuke_dir: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """스탬프가 다르면 ``~/.nuke/bpe`` 를 슬림 복사로 맞춘다.

    Returns:
        updated / stamp / error / skipped 키를 담은 dict.
    """
    result: Dict[str, Any] = {
        "updated": False,
        "stamp": "",
        "error": None,
        "skipped": False,
        "hook_added": False,
    }
    package = src or find_bpe_package_src()
    if package is None or not (package / "nuke_plugin").is_dir():
        result["error"] = "bpe 패키지 소스를 찾을 수 없습니다"
        logger.warning(result["error"])
        return result

    stamp = compute_stamp(package)
    result["stamp"] = stamp
    dest = nuke_bpe_dir(nuke_dir)
    existing = read_stamp(dest)

    try:
        if not force and existing == stamp and (dest / "nuke_plugin").is_dir():
            result["skipped"] = True
            hook = ensure_menu_hook(nuke_dir)
            result["hook_added"] = hook
            return result

        _copy_slim(package, dest)
        write_stamp(dest, stamp)
        hook = ensure_menu_hook(nuke_dir)
        result["hook_added"] = hook
        result["updated"] = True
        logger.info("Nuke 플러그인 동기화 완료 (stamp=%s)", stamp)
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("Nuke 플러그인 동기화 실패: %s", exc, exc_info=True)
    return result
