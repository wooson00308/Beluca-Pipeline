# @cursor-change: 2026-08-07, 0.10.x, ffmpeg 썸네일 디스크 캐시 — 빠른 탐색 방식
"""소스 라이브러리 썸네일 — 이미 번들된 ffmpeg 하나로 EXR/DPX/MOV/MP4를 모두 처리한다.

가벼움 원칙:

* 원본 해상도와 무관하게 긴 변 기준 작은 JPEG 로만 만든다.
* 한 번 만들면 디스크에 캐시하고 (경로+크기+mtime) 해시로 재사용한다.
* 실패한 파일은 ``.fail`` 표시를 남겨 스크롤할 때마다 ffmpeg 를 다시 띄우지 않는다.
* 동영상은 ``thumbnail=100`` 같은 무거운 필터 대신 ``-ss`` 빠른 탐색으로 한 장만 뽑는다.

PySide6 를 import 하지 않는다 — 파일만 만들고, 화면 표시는 GUI 쪽에서 한다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import bpe.core.config as cfg
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs

logger = get_logger("core.media_thumbs")

THUMB_PX_DEFAULT = 256
_THUMB_QUALITY = "5"  # ffmpeg -q:v (2=최상, 31=최저). 브라우징용이라 5로 충분히 작고 선명
_THUMB_TIMEOUT_SEC = 30.0
# 동영상 썸네일: 앞부분이 검은 소스가 많아 2초 지점을 먼저 시도한다.
_MOVIE_SEEK_SEC = "2"

# EXR 은 리니어라 그대로 뽑으면 새까맣게 나온다. 디코더 단계에서 sRGB 로 변환한다.
# (브라우징용 근사치이며 색 검증용이 아니다.)
_DECODER_INPUT_ARGS: Dict[str, List[str]] = {
    ".exr": ["-apply_trc", "iec61966_2_1"],
}


def cache_dir() -> Path:
    """썸네일 캐시 루트 (런타임에 config 참조 — 테스트 격리 때문)."""
    return cfg.MEDIA_THUMBS_DIR


def make_key(src_path: str, size_bytes: int = 0, mtime: float = 0.0, tag: str = "") -> str:
    """캐시 키 — 경로/크기/수정시각이 바뀌면 새 썸네일을 만든다."""
    raw = "{}|{}|{:.3f}|{}".format(
        str(src_path).replace("\\", "/").lower(), int(size_bytes), float(mtime), tag
    )
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _key_dir(key: str) -> Path:
    """해시 앞 2자리로 폴더를 나눠 한 폴더에 파일이 수만 개 쌓이지 않게 한다."""
    return cache_dir() / key[:2]


def thumb_file(key: str) -> Path:
    return _key_dir(key) / "{}.jpg".format(key)


def _fail_marker(key: str) -> Path:
    return _key_dir(key) / "{}.fail".format(key)


def has_thumbnail(key: str) -> bool:
    return thumb_file(key).is_file()


def is_failed(key: str) -> bool:
    """이전에 썸네일 생성이 실패한 파일인지 (재시도 폭주 방지)."""
    return _fail_marker(key).is_file()


def _mark_failed(key: str) -> None:
    try:
        _key_dir(key).mkdir(parents=True, exist_ok=True)
        _fail_marker(key).write_text("", encoding="utf-8")
    except OSError:
        pass


def clear_failed_marker(key: str) -> None:
    """사용자가 재시도를 요청했을 때 이전 실패 표시를 지운다."""
    try:
        _fail_marker(key).unlink(missing_ok=True)
    except OSError:
        pass


def ffmpeg_available() -> bool:
    """번들 ffmpeg 를 찾을 수 있는지 (원인 안내용 — resolve_ffmpeg 자체는 안 건드림)."""
    return bool(resolve_ffmpeg())


def _scale_filter(thumb_px: int) -> str:
    """원본보다 크게 늘리지 않으면서 긴 변을 ``thumb_px`` 로 맞춘다.

    필터 문자열 안의 콤마는 ffmpeg 가 필터 구분자로 보므로 반드시 이스케이프한다.
    """
    px = max(32, int(thumb_px))
    return "scale=w=min({0}\\,iw):h=-2".format(px)


def _run_ffmpeg(args: Sequence[str], timeout_sec: float) -> bool:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return False
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
            **no_console_subprocess_kwargs(),
        )
    except Exception as exc:
        logger.debug("ffmpeg 실행 실패: %s", exc)
        return False
    if proc.returncode != 0:
        logger.debug("ffmpeg 코드 %s: %s", proc.returncode, (proc.stderr or b"")[:200])
        return False
    return True


def _decode_still(src_path: str, out_path: Path, thumb_px: int, timeout_sec: float) -> bool:
    """이미지 파일(EXR/DPX/PNG…) 한 장을 JPEG 썸네일로 만든다."""
    ext = Path(src_path).suffix.lower()
    decoder_args = _DECODER_INPUT_ARGS.get(ext, [])
    base_tail = [
        "-i",
        str(src_path),
        "-frames:v",
        "1",
        "-vf",
        _scale_filter(thumb_px),
        "-q:v",
        _THUMB_QUALITY,
        str(out_path),
    ]
    if decoder_args and _run_ffmpeg(decoder_args + base_tail, timeout_sec):
        return True
    # 디코더 옵션을 지원하지 않는 변종(멀티파트 EXR 등)은 옵션 없이 한 번 더 시도한다.
    return _run_ffmpeg(base_tail, timeout_sec)


def ensure_still_thumbnail(
    src_path: str,
    key: str,
    thumb_px: int = THUMB_PX_DEFAULT,
) -> Optional[Path]:
    """이미지 한 장(또는 시퀀스의 대표 프레임)의 썸네일 경로. 실패하면 ``None``."""
    out = thumb_file(key)
    if out.is_file():
        return out
    if is_failed(key):
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if _decode_still(src_path, out, thumb_px, _THUMB_TIMEOUT_SEC) and out.is_file():
        return out
    _mark_failed(key)
    return None


def ensure_movie_thumbnail(
    src_path: str,
    key: str,
    thumb_px: int = THUMB_PX_DEFAULT,
) -> Optional[Path]:
    """동영상 썸네일 — ``-ss`` 빠른 탐색으로 한 장만 뽑는다 (4K 100프레임 디코드 금지)."""
    out = thumb_file(key)
    if out.is_file():
        return out
    if is_failed(key):
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = _scale_filter(thumb_px)
    # 입력 앞 -ss: 키프레임 근처로 점프해 디코드를 최소화한다.
    seek_args = [
        "-ss",
        _MOVIE_SEEK_SEC,
        "-i",
        str(src_path),
        "-frames:v",
        "1",
        "-vf",
        vf,
        "-q:v",
        _THUMB_QUALITY,
        "-an",
        "-sn",
        str(out),
    ]
    if _run_ffmpeg(seek_args, _THUMB_TIMEOUT_SEC) and out.is_file():
        return out
    # 2초보다 짧은 클립은 처음부터 한 장.
    fallback = [
        "-ss",
        "0",
        "-i",
        str(src_path),
        "-frames:v",
        "1",
        "-vf",
        vf,
        "-q:v",
        _THUMB_QUALITY,
        "-an",
        "-sn",
        str(out),
    ]
    if _run_ffmpeg(fallback, _THUMB_TIMEOUT_SEC) and out.is_file():
        return out
    _mark_failed(key)
    return None


def ensure_preview_frame(
    src_path: str,
    key: str,
    preview_px: int,
) -> Optional[Path]:
    """프리뷰 패널용 큰 프레임 한 장 (썸네일과 별도 키로 캐시)."""
    return ensure_still_thumbnail(src_path, key, preview_px)


# ── 캐시 용량 관리 ────────────────────────────────────────────────────


def cache_size_bytes() -> int:
    """캐시 총 용량. 폴더가 없으면 0."""
    root = cache_dir()
    total = 0
    if not root.is_dir():
        return 0
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                continue
    return total


def enforce_cache_limit(max_bytes: int) -> int:
    """캐시가 상한을 넘으면 오래 안 쓴 파일부터 지운다. 지운 바이트 수 반환."""
    limit = max(0, int(max_bytes))
    root = cache_dir()
    if limit <= 0 or not root.is_dir():
        return 0
    entries: List[tuple] = []
    total = 0
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, fp))
            total += st.st_size
    if total <= limit:
        return 0
    entries.sort(key=lambda it: it[0])  # 오래된 것 먼저
    freed = 0
    for _mt, size, fp in entries:
        if total - freed <= limit:
            break
        try:
            os.remove(fp)
            freed += size
        except OSError:
            continue
    logger.info("썸네일 캐시 정리: %.1fMB 삭제", freed / (1024.0 * 1024.0))
    return freed


def clear_cache() -> None:
    """캐시 전체 삭제 (설정에서 수동으로 비울 때)."""
    import shutil

    root = cache_dir()
    if root.is_dir():
        shutil.rmtree(str(root), ignore_errors=True)
