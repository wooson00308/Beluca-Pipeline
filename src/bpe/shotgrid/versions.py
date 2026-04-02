"""ShotGrid Version create / movie upload / thumbnail."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
        "project": {"type": "Project", "id": int(project_id)},
        "entity": {"type": "Shot", "id": int(shot_id)},
        "code": version_name,
        "description": (description or "").strip(),
    }
    if task_id is not None:
        data["sg_task"] = {"type": "Task", "id": int(task_id)}
    if artist_id is not None:
        data["user"] = {"type": "HumanUser", "id": int(artist_id)}
    if sg_status:
        data["sg_status_list"] = sg_status.strip()

    return sg.create("Version", data)


def list_versions_for_shot(
    sg: Any,
    shot_id: int,
    *,
    limit: int = 80,
) -> List[Dict[str, Any]]:
    """Versions linked to a Shot, newest first (code, artist, status, created_at, description)."""
    sid = int(shot_id)
    filters = [["entity", "is", {"type": "Shot", "id": sid}]]
    fields = ["id", "code", "user", "sg_status_list", "created_at", "image", "description"]
    order = [{"field_name": "created_at", "direction": "desc"}]
    try:
        raw = list(sg.find("Version", filters, fields, limit=int(limit), order=order) or [])
    except Exception as exc:
        logger.warning("list_versions_for_shot find failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for row in raw:
        user_ent = row.get("user") or {}
        artist_name = ""
        if isinstance(user_ent, dict):
            artist_name = (user_ent.get("name") or "").strip()
        code = (row.get("code") or "").strip()
        status = (row.get("sg_status_list") or "").strip()
        created = row.get("created_at")
        if hasattr(created, "strftime"):
            ts_str = created.strftime("%Y-%m-%d %H:%M")
        else:
            ts_str = str(created or "—")
        vid = row.get("id")
        try:
            vid_i = int(vid) if vid is not None else 0
        except (TypeError, ValueError):
            vid_i = 0
        thumb_url = ""
        img = row.get("image")
        if isinstance(img, str):
            thumb_url = img.strip()
        elif isinstance(img, dict):
            thumb_url = (img.get("url") or "").strip()
        desc_raw = row.get("description")
        if desc_raw is None:
            description = ""
        else:
            description = str(desc_raw).strip()
        out.append(
            {
                "version_id": vid_i,
                "code": code,
                "artist": artist_name or "—",
                "status": status,
                "created_at_display": ts_str,
                "thumb_url": thumb_url,
                "description": description,
            }
        )
    return out


def list_shots_uploaded_by_user_on_date(
    sg: Any,
    *,
    user_id: int,
    target_date: date,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Shots the user uploaded Versions for on *target_date* (local calendar day).

    One row per Shot (newest matching Version per shot). All projects.
    """
    uid = int(user_id)
    day_start = datetime.combine(target_date, dt_time.min)
    day_end = datetime.combine(target_date + timedelta(days=1), dt_time.min)
    filters = [
        ["user", "is", {"type": "HumanUser", "id": uid}],
        ["created_at", "greater_than", day_start],
        ["created_at", "less_than", day_end],
    ]
    fields = ["id", "code", "created_at", "entity", "image", "sg_task", "project", "description"]
    order = [{"field_name": "created_at", "direction": "desc"}]
    try:
        raw = list(sg.find("Version", filters, fields, limit=int(limit), order=order) or [])
    except Exception as exc:
        logger.warning("list_shots_uploaded_by_user_on_date find failed: %s", exc)
        return []

    seen_shot_ids: set[int] = set()
    out: List[Dict[str, Any]] = []
    for row in raw:
        ent = row.get("entity") or {}
        if (ent.get("type") or "").lower() != "shot":
            continue
        sid = ent.get("id")
        try:
            sid_i = int(sid) if sid is not None else 0
        except (TypeError, ValueError):
            continue
        if sid_i <= 0 or sid_i in seen_shot_ids:
            continue
        seen_shot_ids.add(sid_i)
        shot_code = (ent.get("code") or ent.get("name") or "").strip() or f"Shot #{sid_i}"
        proj = row.get("project") or {}
        try:
            proj_id = int(proj.get("id")) if proj.get("id") is not None else 0
        except (TypeError, ValueError):
            proj_id = 0
        proj_name = (proj.get("name") or proj.get("code") or "").strip() or "—"
        thumb_url = ""
        img = row.get("image")
        if isinstance(img, str):
            thumb_url = img.strip()
        elif isinstance(img, dict):
            thumb_url = (img.get("url") or "").strip()
        sg_task = row.get("sg_task") or {}
        default_task_id = 0
        if isinstance(sg_task, dict) and sg_task.get("id") is not None:
            try:
                default_task_id = int(sg_task["id"])
            except (TypeError, ValueError):
                pass
        try:
            vid_i = int(row.get("id") or 0)
        except (TypeError, ValueError):
            vid_i = 0
        desc_raw = row.get("description")
        ver_desc = (str(desc_raw).strip() if desc_raw is not None else "").strip()
        out.append(
            {
                "shot_id": sid_i,
                "shot_code": shot_code,
                "project_id": proj_id,
                "project_name": proj_name,
                "thumb_url": thumb_url,
                "default_task_id": default_task_id,
                "version_id": vid_i,
                "version_description": ver_desc,
            }
        )
    return out


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
        version_id,
        file_size,
        stage_local,
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
                _up_ret = sg.upload("Version", int(version_id), upload_src, "sg_uploaded_movie")
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
                    attempt_idx,
                    upload_rounds,
                    type(round_e).__name__,
                    retryable,
                )
                if not retryable or attempt_idx >= upload_rounds:
                    raise
                _wait = min(60.0, 10.0 * attempt_idx)
                logger.info("업로드 재시도 대기 %.0f초 (%d/%d)", _wait, attempt_idx, upload_rounds)
                time.sleep(_wait)

        # ── 검증 1: sg.upload() 반환값 ────────────────────────────
        if _up_ret is None:
            raise ShotGridError(
                "sg.upload()가 None을 반환했습니다. "
                "파일이 ShotGrid에 전송되지 않았습니다.\n"
                f"version_id={version_id}, file={Path(upload_src).name}"
            )
        try:
            attach_id = int(_up_ret)
        except (TypeError, ValueError):
            raise ShotGridError(
                f"sg.upload()가 비정상 값을 반환했습니다: {_up_ret!r}\n"
                f"version_id={version_id}, file={Path(upload_src).name}"
            )
        logger.debug("sg.upload returned attach_id=%d", attach_id)

        _overall(0.92)

        # ── 검증 2: 즉시 find_one으로 sg_uploaded_movie 확인 ─────
        vf = sg.find_one(
            "Version",
            [["id", "is", int(version_id)]],
            ["id", "sg_uploaded_movie"],
        )
        if vf is None:
            raise ShotGridError(
                f"업로드 후 Version #{version_id}을 조회할 수 없습니다.\n"
                "ShotGrid 연결 상태를 확인하세요."
            )
        mov_field = vf.get("sg_uploaded_movie")

        # ── 검증 3: 필드가 비어있으면 2초 대기 후 재확인 ──────────
        if mov_field is None:
            logger.info(
                "sg_uploaded_movie 비어있음 (attach_id=%d) — 2초 대기 후 재확인...",
                attach_id,
            )
            time.sleep(2.0)
            vf2 = sg.find_one(
                "Version",
                [["id", "is", int(version_id)]],
                ["id", "sg_uploaded_movie"],
            )
            mov_field = (vf2 or {}).get("sg_uploaded_movie")
            if mov_field is None:
                raise ShotGridError(
                    f"ShotGrid API가 업로드 성공을 반환했지만(attach_id={attach_id}), "
                    "Version의 sg_uploaded_movie 필드가 비어 있습니다.\n"
                    "ShotGrid 관리자에게 문의하거나 수동으로 MOV를 재업로드하세요."
                )

        logger.info(
            "upload verified: version_id=%d attach_id=%d movie=%s",
            version_id,
            attach_id,
            mov_field.get("name", "") if isinstance(mov_field, dict) else mov_field,
        )
        _overall(1.0)

    except Exception as e:
        if isinstance(e, ShotGridError):
            raise
        err_lower = str(e).lower()
        err_s = str(e)
        if "timed out" in err_lower or "timeout" in err_lower or "max attempts" in err_lower:
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
                "-i",
                movie_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
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
