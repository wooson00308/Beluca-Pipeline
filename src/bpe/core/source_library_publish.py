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
_REFRESH_BASELINE = "source_library_refresh_baseline.json"

# 새로고침 「크게 줄어듦」 판정 — 루트 하나에서 이만큼 넘게 줄면 팀 공유 보류.
REFRESH_BIG_LOSS_MIN = 200
REFRESH_BIG_LOSS_RATIO = 0.02

# refresh_publish_decision 사유 코드
REFRESH_UNKNOWN = "unknown"
REFRESH_READ_ERROR = "read_error"
REFRESH_UNCHANGED = "unchanged"
REFRESH_SHARED_NEWER_FORMAT = "shared_newer_format"
REFRESH_SHARED_MOVED = "shared_moved"
REFRESH_BIG_LOSS = "big_loss"
REFRESH_CHANGED = "changed"

# 스캔(그룹핑) 로직 세대. PNG/TGA 시퀀스 묶기(3D·ball_pass 한정)가 v2.
# 구버전 BPE 가 게시한 공유 인덱스(값 없음=0 또는 더 낮음)는 pull 하지 않는다 —
# 낱장 인덱스가 신버전 사용자의 묶인 인덱스를 되돌리는 왕복(flip-flop) 방지.
GROUPING_VERSION = 2


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


# ── 설정 「새로고침」 (바뀐 부분만 반영) ────────────────────────────────


def refresh_baseline_path() -> Path:
    """새로고침 비교 기준선 — 로컬 캐시 전용(공유 형식 무관)."""
    return cfg.CACHE_DIR / _REFRESH_BASELINE


def read_refresh_baseline() -> Dict[str, Any]:
    data = read_json_file(refresh_baseline_path(), {})
    return data if isinstance(data, dict) else {}


def write_refresh_baseline(data: Dict[str, Any]) -> None:
    write_json_file(refresh_baseline_path(), data)


def merge_refresh_baseline(
    baseline: Optional[Dict[str, Any]],
    shared_published_at: str,
    current: Optional[Dict[str, Any]],
    roots: List[str],
) -> Optional[Dict[str, Any]]:
    """새로고침 시작 시 비교 기준선("마지막으로 팀 장부와 맞춘 상태")을 정한다.

    * 기준선의 ``published_at`` 이 현재 공유본과 다르면(누가 게시했거나 pull 함)
      지금 로컬 스냅샷(= 방금 받은 팀 장부)으로 새로 시작한다.
    * 같으면 기존 기준선을 유지하고, 기준선에 없는 루트만 지금 값으로 채운다 —
      보류된 새로고침을 다시 눌러도 "이미 반영됨"으로 오판하지 않게.

    ``current`` 가 None(스냅샷 실패)이면 None — 호출부는 게시를 보류한다.
    """
    if current is None:
        return None
    cur_roots = current.get("roots") or {}
    cur_cats = current.get("categories") or {}
    base: Dict[str, Any] = baseline if isinstance(baseline, dict) else {}
    if not shared_published_at or str(base.get("published_at") or "") != shared_published_at:
        base = {}
    b_roots: Dict[str, Any] = dict(base.get("roots") or {})
    b_cats: Dict[str, Any] = dict(base.get("categories") or {})
    for root in roots:
        if root not in b_roots and root in cur_roots:
            b_roots[root] = cur_roots[root]
            b_cats[root] = dict(cur_cats.get(root) or {})
    return {"published_at": shared_published_at, "roots": b_roots, "categories": b_cats}


def refresh_publish_decision(
    baseline: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
    *,
    read_failures: int,
    shared_grouping_version: int,
    shared_moved: bool,
) -> Tuple[bool, str]:
    """새로고침 결과를 팀 공유 목록에 게시할지 ``(게시 여부, 사유 코드)``.

    판정 순서: 상태 모름 → 폴더 읽기 실패 → 기준선과 내용 동일 → 공유본이 더 새
    형식 → 그사이 남이 게시 → 크게 줄어듦 → 변경(게시).
    """
    if not baseline or not after:
        return False, REFRESH_UNKNOWN
    if int(read_failures) > 0:
        return False, REFRESH_READ_ERROR
    b_roots = baseline.get("roots") or {}
    a_roots = after.get("roots") or {}
    targets = list(a_roots.keys())
    if not targets or any(r not in b_roots for r in targets):
        return False, REFRESH_UNKNOWN
    if all(
        str((a_roots[r] or {}).get("digest") or "") == str((b_roots[r] or {}).get("digest") or "")
        for r in targets
    ):
        return False, REFRESH_UNCHANGED
    if int(shared_grouping_version or 0) > GROUPING_VERSION:
        return False, REFRESH_SHARED_NEWER_FORMAT
    if shared_moved:
        return False, REFRESH_SHARED_MOVED
    for r in targets:
        before_n = int((b_roots[r] or {}).get("items") or 0)
        after_n = int((a_roots[r] or {}).get("items") or 0)
        allowed = max(REFRESH_BIG_LOSS_MIN, int(before_n * REFRESH_BIG_LOSS_RATIO))
        if before_n - after_n > allowed:
            return False, REFRESH_BIG_LOSS
    return True, REFRESH_CHANGED


def new_top_folders(
    baseline: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
) -> List[str]:
    """기준선에는 없고(0개) 이번에 항목이 생긴 최상위 폴더 이름(정렬)."""
    if not baseline or not after:
        return []
    b_cats = baseline.get("categories") or {}
    out: List[str] = []
    for root, cats in (after.get("categories") or {}).items():
        before_cats = b_cats.get(root) or {}
        for cat, n in (cats or {}).items():
            if not cat or int(n) <= 0:
                continue
            if int(before_cats.get(cat) or 0) <= 0:
                out.append(str(cat))
    return sorted(set(out), key=str.lower)


def shared_grouping_outdated() -> bool:
    """공유 인덱스가 존재하는데 구버전 그룹핑 로직으로 게시된 상태인지."""
    shared = read_shared_meta()
    if not str(shared.get("published_at") or ""):
        return False
    return int(shared.get("grouping_version") or 0) < GROUPING_VERSION


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
        "grouping_version": GROUPING_VERSION,
    }
    write_json_file(shared_meta_path(), meta)
    write_json_file(
        local_marker_path(),
        {"published_at": meta["published_at"], "items": meta["items"]},
    )
    logger.info("소스 라이브러리 인덱스 게시: %s (%s개)", dest, items)
    return meta


def _local_total_safe() -> Optional[int]:
    """로컬 인덱스 건수. 파일 없음=0, 열기/조회 실패는 "모름"(None).

    실패를 0으로 돌려주면 "로컬이 비었다"로 오판해 건수 비교 pull 이 로컬
    인덱스를 공유본으로 되돌리는 사고가 난다(예: 다른 인스턴스가 잡은 DB 락).
    모르면 모른다고 반환하고, 호출부는 건수 비교를 건너뛴다.
    """
    path = db.index_path()
    if not path.is_file():
        return 0
    conn = None
    try:
        conn = db.connect(path)
        return db.total_indexed(conn)
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.debug("로컬 인덱스 건수 조회 실패(모름 처리): %s", exc)
        return None
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
        # 조회 실패(락 등)를 "전부 빠짐"으로 돌려주면 폴백 스캔·게시가 오발된다.
        # 모르면 빠진 것 없음으로 취급하고 다음 기회에 다시 본다 (fail-closed).
        logger.debug("로컬 루트 커버리지 조회 실패(빠짐 없음 처리): %s", exc)
        return []
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
    # published_at 비교보다 먼저 — 구버전(낱장) 게시본은 어떤 사유로도 pull 하지 않는다.
    if int(shared.get("grouping_version") or 0) < GROUPING_VERSION:
        logger.warning(
            "공유 인덱스가 구버전 그룹핑(v%s < v%s) — pull 건너뜀. 전체 재스캔·게시 필요",
            int(shared.get("grouping_version") or 0),
            GROUPING_VERSION,
        )
        return None
    local = read_local_marker()
    local_at = str(local.get("published_at") or "")
    if published_at > local_at:
        return "shared_newer ({} > {})".format(published_at, local_at or "-")

    shared_items = int(shared.get("items") or 0)
    local_count = _local_total_safe()
    marker_items = int(local.get("items") or 0)
    # 로컬 건수를 모르면(DB 락 등) 건수 비교로 pull 을 강제하지 않는다 —
    # "모름"을 0으로 취급하면 멀쩡한 로컬 인덱스를 공유본으로 되돌린다.
    if local_count is not None:
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

    로컬 DB 를 ``os.replace`` 로 파일째 갈아끼우면 GUI 가 열어둔 sqlite 핸들
    때문에 Windows 에서 ``PermissionError`` 로 실패한다(실측 — 신규 PC 가
    라이브러리를 영영 못 받던 원인). 그래서 공유본을 임시 파일로 받아온 뒤
    ``sqlite3.Connection.backup`` 으로 로컬 DB "내용"만 교체한다 —
    ``publish_index`` 가 쓰는 것과 같은 패턴이라 열린 핸들과 공존한다.
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
        src_conn = sqlite3.connect(str(tmp_path))
        try:
            dest_conn = db.connect(dest)
            try:
                src_conn.backup(dest_conn)
                dest_conn.commit()
            finally:
                dest_conn.close()
        finally:
            src_conn.close()
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
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
