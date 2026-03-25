"""ShotGrid Version create / movie upload / thumbnail."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.versions")

# ── staging helpers ──────────────────────────────────────────────────

_UPLOAD_STAGE_MIN_BYTES = 64 * 1024 * 1024  # 64 MiB


def _path_is_likely_network(path: str) -> bool:
    """Detect UNC paths and mapped network drives on Windows."""
    p = (path or "").strip()
    if not p:
        return False
    if p.startswith("\\\\"):
        return True
    if sys.platform != "win32":
        return p.startswith("//")
    try:
        import ctypes
        drive = Path(p).drive
        if not drive:
            return False
        root = drive + "\\"
        DRIVE_REMOTE = 4
        t = int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
        return t == DRIVE_REMOTE
    except Exception:
        return False


def _should_stage_movie_locally(movie_path: str, file_size: int) -> bool:
    if _path_is_likely_network(movie_path):
        return True
    if file_size >= _UPLOAD_STAGE_MIN_BYTES:
        return True
    flag = (os.environ.get("BPE_SG_UPLOAD_ALWAYS_LOCAL_COPY") or "").strip().lower()
    if flag in ("1", "true", "yes", "y", "on"):
        return True
    return False


def _copy_file_chunked_with_progress(
    src: str,
    dst: str,
    total: int,
    on_frac: Optional[Callable[[float], None]],
    chunk: int = 8 * 1024 * 1024,
) -> None:
    """Copy with progress callback (0-1)."""
    done = 0
    with open(src, "rb") as rf, open(dst, "wb") as wf:
        while True:
            b = rf.read(chunk)
            if not b:
                break
            wf.write(b)
            done += len(b)
            if on_frac and total > 0:
                try:
                    on_frac(min(1.0, done / float(total)))
                except Exception:
                    pass


# ── Version entity ───────────────────────────────────────────────────


def create_version(
    sg: Any,
    *,
    project_id: int,
    shot_id: int,
    task_id: Optional[int],
    version_name: str,
    description: str = "",
    artist_id: Optional[int] = None,
    sg_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a ShotGrid Version entity."""
    version_name = (version_name or "").strip()
    if not version_name:
        raise ShotGridError("Version Name이 비어 있습니다.")

    data: Dict[str, Any] = {
        "project":     {"type": "Project", "id": int(project_id)},
        "entity":      {"type": "Shot",    "id": int(shot_id)},
        "code":        version_name,
        "description": (description or "").strip(),
    }
    if task_id is not None:
        data["sg_task"] = {"type": "Task", "id": int(task_id)}
    if artist_id is not None:
        data["user"] = {"type": "HumanUser", "id": int(artist_id)}
    if sg_status:
        data["sg_status_list"] = sg_status.strip()

    return sg.create("Version", data)


# ── movie upload ─────────────────────────────────────────────────────


def upload_movie_to_version(
    sg: Any,
    version_id: int,
    movie_path: str,
    *,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> None:
    """Upload a movie file to a Version entity (sg_uploaded_movie).

    Retry logic: up to 3 rounds for retryable errors (timeout, max attempts,
    connection reset).  Wait ``min(60, 10*attempt)`` seconds between retries.
    """
    movie_path = (movie_path or "").strip()
    if not movie_path or not Path(movie_path).is_file():
        raise ShotGridError(f"파일을 찾을 수 없습니다: {movie_path}")

    file_size = os.path.getsize(movie_path)
    stage_local = _should_stage_movie_locally(movie_path, file_size)

    def _overall(frac_0_1: float) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(max(0.0, min(1.0, float(frac_0_1))))
        except Exception:
            pass

    logger.debug(
        "upload_movie_to_version: version_id=%d size=%d stage_local=%s",
        version_id, file_size, stage_local,
    )

    _overall(0.02)
    upload_src = movie_path
    tmp_copy: Optional[str] = None

    if stage_local:
        try:
            suf = Path(movie_path).suffix or ".mov"
            fd, tmp_copy = tempfile.mkstemp(prefix="bpe_sg_upload_", suffix=suf)
            os.close(fd)

            def _stage_frac(local_f: float) -> None:
                _overall(0.05 + 0.13 * max(0.0, min(1.0, local_f)))

            if progress_cb is not None:
                _copy_file_chunked_with_progress(movie_path, tmp_copy, file_size, _stage_frac)
            else:
                shutil.copy2(movie_path, tmp_copy)
            upload_src = tmp_copy
            _overall(0.18)
            logger.debug("staged to temp: %s (%d bytes)", Path(tmp_copy).name, file_size)
        except Exception as e:
            if tmp_copy and os.path.isfile(tmp_copy):
                try:
                    os.unlink(tmp_copy)
                except OSError:
                    pass
            raise ShotGridError(
                "업로드 전 로컬 임시 폴더로 복사하지 못했습니다. "
                "디스크 여유 공간과 경로 접근 권한을 확인하세요."
            ) from e
    else:
        _overall(0.18)

    sg_logger = logging.getLogger("shotgun_api3")
    _old_level = sg_logger.level
    attach_id: Optional[int] = None

    try:
        upload_rounds = 3
        _overall(0.55)
        for attempt_idx in range(1, upload_rounds + 1):
            try:
                logger.debug("sg.upload attempt %d/%d", attempt_idx, upload_rounds)
                _up_ret = sg.upload(
                    "Version", int(version_id), upload_src, "sg_uploaded_movie"
                )
                try:
                    attach_id = int(_up_ret) if _up_ret is not None else None
                except (TypeError, ValueError):
                    attach_id = None
                break
            except Exception as round_e:
                msg = str(round_e)
                _msg_lower = msg.lower()
                retryable = (
                    "timed out" in _msg_lower
                    or "timeout" in _msg_lower
                    or "max attempts" in _msg_lower
                    or "Connection reset" in msg
                    or "Connection aborted" in msg
                    or "URLError" in type(round_e).__name__
                )
                logger.warning(
                    "upload round %d/%d failed: %s (retryable=%s)",
                    attempt_idx, upload_rounds, type(round_e).__name__, retryable,
                )
                if not retryable or attempt_idx >= upload_rounds:
                    raise
                _wait = min(60.0, 10.0 * attempt_idx)
                logger.info("업로드 재시도 대기 %.0f초 (%d/%d)", _wait, attempt_idx, upload_rounds)
                time.sleep(_wait)

        _overall(0.92)

        # verify upload attached
        vf: Optional[Dict[str, Any]] = None
        try:
            vf = sg.find_one(
                "Version",
                [["id", "is", int(version_id)]],
                ["id", "sg_uploaded_movie"],
            )
        except Exception as ve:
            logger.debug("post-upload verify failed: %s", ve)
        mov_field = (vf or {}).get("sg_uploaded_movie")
        if vf is not None and mov_field is None:
            raise ShotGridError(
                "ShotGrid API가 업로드 성공을 반환했지만, "
                "Version의 sg_uploaded_movie 필드가 비어 있습니다.\n"
                "ShotGrid 관리자에게 문의하거나 수동으로 MOV를 재업로드하세요."
            )
        logger.debug("upload ok: version_id=%d attach_id=%s", version_id, attach_id)
        _overall(1.0)

    except Exception as e:
        if isinstance(e, ShotGridError):
            raise
        err_lower = str(e).lower()
        err_s = str(e)
        if (
            "timed out" in err_lower
            or "timeout" in err_lower
            or "max attempts" in err_lower
        ):
            raise ShotGridError(
                "S3 클라우드 스토리지 업로드 타임아웃(또는 재시도 한도 초과)입니다.\n"
                "• 회사 방화벽이 ShotGrid S3 엔드포인트를 차단할 수 있습니다. IT에 확인해 보세요.\n"
                "• 64MB 이상·네트워크 경로는 로컬 임시 복사 후 올립니다. "
                "항상 복사하려면 환경 변수 BPE_SG_UPLOAD_ALWAYS_LOCAL_COPY=1 을 설정해 보세요.\n"
                "• PUT 소켓 타임아웃은 환경 변수 BPE_SG_PUT_TIMEOUT_SECS(초)로 조정할 수 있습니다. "
                "(값을 너무 작게 하면 느린 회선에서 실패할 수 있습니다.)\n"
                f"(원본 오류: {err_s[:400]})"
            ) from e
        raise
    finally:
        try:
            sg_logger.setLevel(_old_level)
        except Exception:
            pass
        if tmp_copy and os.path.isfile(tmp_copy):
            try:
                os.unlink(tmp_copy)
            except OSError:
                pass


# ── thumbnail ────────────────────────────────────────────────────────


def _extract_first_frame(
    movie_path: str,
    dest_path: str,
    *,
    timeout_sec: float = 30.0,
) -> bool:
    """Extract the first frame of a movie as JPEG via ffmpeg."""
    import subprocess as _sp

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.debug("ffmpeg not found — skip first-frame extraction")
        return False
    try:
        _sp.run(
            [
                ffmpeg_bin,
                "-y",
                "-i", movie_path,
                "-vframes", "1",
                "-q:v", "2",
                dest_path,
            ],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            timeout=timeout_sec,
            check=True,
        )
        return Path(dest_path).is_file() and Path(dest_path).stat().st_size > 0
    except Exception as e:
        logger.debug("ffmpeg first-frame extraction failed: %s", e)
        return False


def upload_thumbnail_to_version(
    sg: Any,
    version_id: int,
    image_path: Optional[str] = None,
    movie_path: Optional[str] = None,
) -> bool:
    """Upload a thumbnail to a Version entity.

    Uses *image_path* directly if given, otherwise extracts first frame
    from *movie_path* via ffmpeg.
    """
    tmp_thumb: Optional[str] = None
    upload_src: Optional[str] = None

    try:
        if image_path and Path(image_path).is_file():
            upload_src = image_path

        if upload_src is None and movie_path and Path(movie_path).is_file():
            fd, tmp_thumb = tempfile.mkstemp(prefix="bpe_thumb_", suffix=".jpg")
            os.close(fd)
            if _extract_first_frame(movie_path, tmp_thumb):
                upload_src = tmp_thumb
            else:
                try:
                    os.unlink(tmp_thumb)
                except OSError:
                    pass
                tmp_thumb = None

        if upload_src is None:
            logger.debug("upload_thumbnail_to_version: no image source available")
            return False

        sg.upload_thumbnail("Version", int(version_id), upload_src)
        logger.info("Thumbnail uploaded for Version %d from %s", version_id, Path(upload_src).name)
        return True

    except Exception as e:
        logger.warning("upload_thumbnail_to_version failed: %s", e)
        return False
    finally:
        if tmp_thumb and os.path.isfile(tmp_thumb):
            try:
                os.unlink(tmp_thumb)
            except OSError:
                pass
