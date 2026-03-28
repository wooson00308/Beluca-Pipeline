"""GitHub Releases 기반 업데이트 체크 및 에셋 다운로드."""

from __future__ import annotations

import json
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from bpe.core.logging import get_logger


def _make_ssl_context() -> ssl.SSLContext:
    """certifi 인증서가 있으면 사용, 없으면 기본 context."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


logger = get_logger("update_checker")

GITHUB_REPO_OWNER = "wooson00308"
GITHUB_REPO_NAME = "Beluca-Pipeline"
RELEASES_LATEST_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
)

_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


@dataclass
class UpdateInfo:
    """업데이트 정보를 담는 데이터 클래스."""

    latest_version: str
    download_url: str
    release_notes: str
    html_url: str


def _parse_version(v: str) -> Tuple[int, ...]:
    """버전 문자열을 정수 튜플로 변환한다."""
    return tuple(int(x) for x in v.split("."))


def compare_versions(current: str, latest: str) -> bool:
    """*latest*가 *current*보다 새로운 버전이면 ``True``."""
    return _parse_version(latest) > _parse_version(current)


def _pick_asset_url(assets: list, platform: str) -> Optional[str]:
    """플랫폼에 맞는 에셋 다운로드 URL을 반환한다."""
    name_map = {
        "darwin": "BPE-macOS.dmg",
        "win32": "BPE-Windows.zip",
    }
    target = name_map.get(platform)
    if target is None:
        return None
    for asset in assets:
        if asset.get("name") == target:
            return asset.get("browser_download_url")
    return None


def check_latest_release(current_version: str) -> Optional[UpdateInfo]:
    """GitHub Releases API에서 최신 릴리즈를 조회한다.

    새 버전이 있으면 ``UpdateInfo``, 아니면 ``None``.
    네트워크 에러 등 모든 예외는 잡아서 ``None`` 반환.
    """
    try:
        req = urllib.request.Request(
            RELEASES_LATEST_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "BPE-UpdateChecker",
            },
        )
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")

        if not compare_versions(current_version, latest):
            return None

        download_url = _pick_asset_url(data.get("assets", []), sys.platform) or ""
        return UpdateInfo(
            latest_version=latest,
            download_url=download_url,
            release_notes=data.get("body", "") or "",
            html_url=data.get("html_url", ""),
        )
    except Exception:
        logger.debug("업데이트 확인 실패", exc_info=True)
        return None


def download_release_asset(
    url: str,
    dest: Path,
    *,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> Path:
    """릴리즈 에셋을 *dest* 경로에 다운로드한다.

    *progress_cb* 가 주어지면 0.0 ~ 1.0 범위로 진행률을 보고한다.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "BPE-UpdateChecker"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctx = _make_ssl_context()

    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        with open(dest, "wb") as fp:
            while True:
                chunk = resp.read(_CHUNK_SIZE)
                if not chunk:
                    break
                fp.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(downloaded / total)

    return dest


def extract_windows_exe(zip_path: Path) -> Path:
    """BPE-Windows.zip에서 ``BPE.exe``를 임시 폴더에 풀어 경로를 반환한다.

    zip 루트 또는 하위 경로에 ``BPE.exe``가 있으면 첫 일치 항목을 사용한다.
    없으면 ``FileNotFoundError``를 발생시킨다.
    """
    dest_dir = Path(tempfile.mkdtemp(prefix="bpe_update_"))
    dest_exe = dest_dir / "BPE_new.exe"

    with zipfile.ZipFile(zip_path, "r") as zf:
        member: Optional[str] = None
        for name in zf.namelist():
            norm = name.replace("\\", "/").rstrip("/")
            if norm.endswith("BPE.exe") or norm == "BPE.exe":
                member = name
                break
        if member is None:
            raise FileNotFoundError("ZIP에 BPE.exe가 없습니다")

        with zf.open(member) as src, open(dest_exe, "wb") as out:
            while True:
                chunk = src.read(_CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)

    return dest_exe
