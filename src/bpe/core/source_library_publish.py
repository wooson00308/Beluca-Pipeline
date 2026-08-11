# @cursor-change: 2026-08-09, 0.13.x, pull 판정에 items·루트 커버리지 추가
"""소스 라이브러리 인덱스 게시·수신.

쓰는 곳은 공유 설정 폴더(``BPE_SourceLibrary/index/``)와 로컬 캐시뿐이다.
등록된 소스 미디어 루트 아래에는 어떤 파일도 만들거나 지우지 않는다.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bpe.core.config as cfg
from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core.atomic_io import read_json_file, write_json_file
from bpe.core.logging import get_logger

logger = get_logger("core.source_library_publish")

_META_NAME = "index.json"
_DB_NAME = "library.sqlite"
_LOCAL_MARKER = "source_library_pulled.json"


def shared_index_dir() -> Path:
    return libcfg.config_dir() / "index"


def shared_db_path() -> Path:
    return shared_index_dir() / _DB_NAME


def shared_meta_path() -> Path:
    return shared_index_dir() / _META_NAME


def local_marker_path() -> Path:
    return cfg.CACHE_DIR / _LOCAL_MARKER


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_shared_meta() -> Dict[str, Any]:
    return read_json_file(shared_meta_path(), {})


def read_local_marker() -> Dict[str, Any]:
    return read_json_file(local_marker_path(), {})


def publish_index(conn: sqlite3.Connection) -> Dict[str, Any]:
    """로컬 인덱스 연결을 공유 폴더에 게시한다. 원본 미디어는 건드리지 않는다.

    ``sqlite3.Connection.backup`` 으로 깨끗한 복사본을 만든 뒤 ``os.replace`` 로
    공유 폴더 안에서만 원자 교체한다.
    """
    out_dir = shared_index_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = shared_db_path()
    fd, tmp_name = tempfile.mkstemp(prefix=".library.", suffix=".sqlite.tmp", dir=str(out_dir))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        dest_conn = sqlite3.connect(str(tmp_path))
        try:
            conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
        os.replace(str(tmp_path), str(dest))
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

    items = db.total_indexed(conn)
    meta = {
        "published_at": _utc_now(),
        "items": int(items),
        "db": _DB_NAME,
    }
    write_json_file(shared_meta_path(), meta)
    write_json_file(
        local_marker_path(),
        {"published_at": meta["published_at"], "items": meta["items"]},
    )
    logger.info("소스 라이브러리 인덱스 게시: %s (%s개)", dest, items)
    return meta


def _local_total_safe() -> int:
    path = db.index_path()
    if not path.is_file():
        return 0
    conn = None
    try:
        conn = db.connect(path)
        return db.total_indexed(conn)
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.debug("로컬 인덱스 건수 조회 실패: %s", exc)
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _open_ro(path: Path) -> Optional[sqlite3.Connection]:
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect("file:{}?mode=ro".format(path.as_posix()), uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.debug("인덱스 읽기 실패 (%s): %s", path, exc)
        return None


def _shared_has_root(root: str) -> bool:
    conn = _open_ro(shared_db_path())
    if conn is None:
        return False
    try:
        return db.count_for_root(conn, root) > 0
    finally:
        conn.close()


def roots_missing_from_local(
    roots: Optional[List[str]] = None,
) -> List[str]:
    """library 등록 루트 중 로컬 인덱스에 항목이 없는 것."""
    if roots is None:
        try:
            library = libcfg.load_library()
            roots = libcfg.roots_for_view(library)
        except Exception as exc:
            logger.debug("library 로드 실패(커버리지): %s", exc)
            return []
    missing: List[str] = []
    path = db.index_path()
    if not path.is_file():
        return [libcfg.normalize_path(r) for r in roots if r]
    conn = None
    try:
        conn = db.connect(path)
        for root in roots:
            root_n = libcfg.normalize_path(root)
            if not root_n:
                continue
            if db.count_for_root(conn, root_n) <= 0:
                missing.append(root_n)
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.debug("로컬 루트 커버리지 조회 실패: %s", exc)
        return [libcfg.normalize_path(r) for r in roots if r]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return missing


def groups_with_empty_index(
    library: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, List[str]]]:
    """배정 루트가 있지만 로컬 인덱스가 0인 그룹 ``(name, roots)``."""
    if library is None:
        library = libcfg.load_library()
    out: List[Tuple[str, List[str]]] = []
    path = db.index_path()
    conn = None
    try:
        if path.is_file():
            conn = db.connect(path)
        for g in libcfg.view_groups(library):
            gname = str(g.get("name") or "")
            grows = libcfg.group_roots(g)
            if not grows:
                continue
            empty: List[str] = []
            for root in grows:
                n = db.count_for_root(conn, root) if conn is not None else 0
                if n <= 0:
                    empty.append(root)
            if empty and len(empty) == len(grows):
                out.append((gname, empty))
            elif empty:
                # 일부 루트만 비어도 경고 대상
                out.append((gname, empty))
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.debug("그룹 인덱스 커버리지 실패: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out


def needs_pull_reason() -> Optional[str]:
    """pull 이 필요하면 사유 문자열, 아니면 None."""
    shared = read_shared_meta()
    published_at = str(shared.get("published_at") or "")
    if not published_at:
        return None
    if not shared_db_path().is_file():
        return None
    local = read_local_marker()
    local_at = str(local.get("published_at") or "")
    if published_at > local_at:
        return "shared_newer ({} > {})".format(published_at, local_at or "-")

    shared_items = int(shared.get("items") or 0)
    local_count = _local_total_safe()
    marker_items = int(local.get("items") or 0)
    # 로컬이 공유보다 적으면 마커가 같아도 강제 pull (MMK 누락 케이스)
    if shared_items > 0 and local_count < shared_items:
        return "items_mismatch local={} shared={} marker={}".format(
            local_count, shared_items, marker_items
        )
    if marker_items > 0 and local_count < marker_items:
        return "marker_items_mismatch local={} marker={}".format(local_count, marker_items)

    missing_local = roots_missing_from_local()
    for root in missing_local:
        if _shared_has_root(root):
            return "missing_root_in_local present_in_shared:{}".format(root)
    return None


def needs_pull() -> bool:
    """공유 인덱스를 로컬로 받을 필요가 있으면 True."""
    reason = needs_pull_reason()
    if reason:
        logger.info("인덱스 pull 필요: %s", reason)
        return True
    return False


def pull_index() -> Optional[Dict[str, Any]]:
    """공유 인덱스를 로컬 캐시로 복사한다. 더 새롭지 않으면 None.

    원본 미디어 루트에는 쓰지 않는다. 대상은 ``SOURCE_LIBRARY_INDEX_FILE`` 뿐.
    """
    reason = needs_pull_reason()
    if not reason:
        logger.info("인덱스 pull 스킵 (이미 일치)")
        return None
    before = _local_total_safe()
    src = shared_db_path()
    dest = db.index_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".source_library.",
        suffix=".sqlite.tmp",
        dir=str(dest.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(str(src), str(tmp_path))
        os.replace(str(tmp_path), str(dest))
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    meta = read_shared_meta()
    write_json_file(
        local_marker_path(),
        {
            "published_at": str(meta.get("published_at") or ""),
            "items": int(meta.get("items") or 0),
        },
    )
    after = _local_total_safe()
    logger.info(
        "소스 라이브러리 인덱스 동기: %s (%s → %s개, 사유: %s)",
        dest,
        before,
        after,
        reason,
    )
    return meta


def try_pull_index() -> Optional[Dict[str, Any]]:
    """동기 실패해도 예외를 밖으로 던지지 않는다."""
    meta, _err = try_pull_index_with_status()
    return meta


def try_pull_index_with_status() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(meta, error)``.

    * ``(meta, None)`` — pull 성공
    * ``(None, None)`` — 이미 최신(또는 공유 인덱스 없음)
    * ``(None, error)`` — pull 필요했는데 실패
    """
    try:
        reason = needs_pull_reason()
        if not reason:
            logger.info("인덱스 pull 불필요 (공유 없음 또는 일치)")
            return None, None
        meta = pull_index()
        return meta, None
    except Exception as exc:
        logger.warning("인덱스 동기 실패: %s", exc)
        return None, str(exc)
