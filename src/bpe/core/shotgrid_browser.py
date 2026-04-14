"""ShotGrid 웹 URL을 Chrome 앱 창으로 여는 헬퍼 (표준 라이브러리만)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

ShotGridPageId = Union[str, int]


def build_shot_canvas_url(base_url: str, page_id: ShotGridPageId, shot_id: int) -> str:
    """``{base}/page/{page_id}#Shot_{shot_id}`` 형태의 Canvas 딥링크 URL."""
    base = (base_url or "").strip().rstrip("/")
    pid = str(page_id).strip()
    sid = int(shot_id)
    if not base or not pid or sid <= 0:
        raise ValueError("base_url, page_id, and positive shot_id are required")
    parsed = urlparse(base)
    if (parsed.scheme or "").lower() != "https":
        raise ValueError("base_url must use https")
    if not (parsed.netloc or "").strip():
        raise ValueError("base_url must include a host")
    return f"{base}/page/{pid}#Shot_{sid}"


def build_project_overview_url(base_url: str, project_id: int) -> str:
    """``{base}/page/project_overview?project_id=…`` — Flow 웹 프로젝트 오버뷰."""
    base = (base_url or "").strip().rstrip("/")
    pid = int(project_id)
    if not base or pid <= 0:
        raise ValueError("base_url and positive project_id are required")
    parsed = urlparse(base)
    if (parsed.scheme or "").lower() != "https":
        raise ValueError("base_url must use https")
    if not (parsed.netloc or "").strip():
        raise ValueError("base_url must include a host")
    return f"{base}/page/project_overview?project_id={pid}"


def _explicit_chrome_paths(explicit: str) -> List[Path]:
    out: List[Path] = []
    ex = (explicit or "").strip()
    if ex:
        out.append(Path(ex))
    envp = (os.environ.get("BPE_CHROME_PATH") or "").strip()
    if envp:
        out.append(Path(envp))
    return out


def _standard_chrome_install_paths() -> List[Path]:
    out: List[Path] = []
    if sys.platform == "win32":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        la = os.environ.get("LOCALAPPDATA", "")
        out.append(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe")
        out.append(Path(pfx86) / "Google" / "Chrome" / "Application" / "chrome.exe")
        if la:
            out.append(Path(la) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        out.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    return out


def _chrome_from_path_env() -> Optional[Path]:
    if sys.platform == "win32":
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chrome"):
        w = shutil.which(name)
        if w:
            return Path(w)
    return None


def resolve_chrome_executable(explicit: str = "") -> Optional[Path]:
    """Chrome 실행 파일 경로. 없으면 None."""
    for p in _explicit_chrome_paths(explicit):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    for p in _standard_chrome_install_paths():
        try:
            if p.parts and p.is_file():
                return p
        except OSError:
            continue
    return _chrome_from_path_env()


def try_launch_chrome_app_url(url: str, *, chrome_executable: str = "") -> bool:
    """Chrome ``--app=<url>`` 로 실행. 성공 시 True (Popen 호출됨).

    False이면 호출 측에서 ``QDesktopServices.openUrl`` 등으로 폴백.
    """
    if not (url or "").strip():
        return False
    parsed = urlparse(url)
    if (parsed.scheme or "").lower() != "https":
        return False
    chrome = resolve_chrome_executable(chrome_executable)
    if not chrome:
        return False
    flag = f"--app={url}"
    popen_kwargs: Dict[str, Any] = {"shell": False, "close_fds": True}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen([str(chrome), flag], **popen_kwargs)  # noqa: S603
    except OSError:
        return False
    return True
