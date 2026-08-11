# @cursor-change: 2026-08-07, 0.11.x, 소스 라이브러리 인덱스 preview_file(팩 프리뷰) 컬럼
"""소스 라이브러리 파일 인덱스 — ``sqlite3`` (표준 라이브러리).

수만 건 규모에서 JSON 파일 하나를 매번 통째로 읽고 쓰는 건 무겁다. 인덱스는
경로·카테고리·프레임 범위·mtime 같은 가벼운 메타데이터만 담고 픽셀 데이터는 없다.

sqlite3 연결은 만든 스레드에서만 쓸 수 있다. 백그라운드 인덱서와 UI는 각자
:func:`connect` 로 자기 연결을 만들어야 한다 (WAL 모드라 동시 읽기/쓰기가 된다).
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import bpe.core.config as cfg
from bpe.core.logging import get_logger
from bpe.core.source_library_scan import (
    KIND_SEQUENCE,
    LibraryItem,
    category_of,
    row_dir_path,
    split_name_ext,
)

_SEQ_TOKEN_RE = re.compile(r"%0\d+d|\d+$")
"""파일명 끝 프레임 번호(``1001``)나 패턴 토큰(``%04d``)을 지운다 — 서로 비교하려고."""

logger = get_logger("core.source_library_db")

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    root         TEXT    NOT NULL,
    dir_rel      TEXT    NOT NULL,
    category     TEXT    NOT NULL DEFAULT '',
    name         TEXT    NOT NULL,
    name_lower   TEXT    NOT NULL DEFAULT '',
    kind         TEXT    NOT NULL,
    ext          TEXT    NOT NULL DEFAULT '',
    seq_pattern  TEXT    NOT NULL DEFAULT '',
    representative TEXT  NOT NULL DEFAULT '',
    preview_file TEXT    NOT NULL DEFAULT '',
    frame_first  INTEGER NOT NULL DEFAULT 0,
    frame_last   INTEGER NOT NULL DEFAULT 0,
    frame_count  INTEGER NOT NULL DEFAULT 1,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    mtime        REAL    NOT NULL DEFAULT 0,
    indexed_at   REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_root_dir ON items(root, dir_rel);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(root, category);
CREATE INDEX IF NOT EXISTS idx_items_name ON items(root, name_lower);
-- 정렬 순서와 같은 인덱스. 커서 페이징이 인덱스만 훑고 끝나게 해준다.
CREATE INDEX IF NOT EXISTS idx_items_order ON items(root, category, name_lower, dir_rel, id);

CREATE TABLE IF NOT EXISTS dirs (
    root       TEXT NOT NULL,
    dir_rel    TEXT NOT NULL,
    mtime      REAL NOT NULL DEFAULT 0,
    indexed_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (root, dir_rel)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


def index_path() -> Path:
    """인덱스 파일 경로 (런타임에 config 를 참조해야 테스트 격리가 된다)."""
    return cfg.SOURCE_LIBRARY_INDEX_FILE


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """인덱스 DB 연결을 만들고 스키마를 보장한다. 호출한 스레드 전용."""
    path = Path(db_path) if db_path is not None else index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    # WAL: 백그라운드 인덱싱 중에도 UI 조회가 막히지 않는다.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:  # 손상된 파일 등 — 아래 init_schema 에서 재시도
        pass
    init_schema(conn)
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute("PRAGMA table_info({})".format(table)).fetchall()
    return [str(r[1]) for r in rows]


def init_schema(conn: sqlite3.Connection) -> None:
    """테이블/인덱스를 만든다. v1→v2 는 ``preview_file`` 컬럼을 추가한다."""
    conn.executescript(_SCHEMA)
    cols = _table_columns(conn, "items")
    if cols and "preview_file" not in cols:
        try:
            conn.execute("ALTER TABLE items ADD COLUMN preview_file TEXT NOT NULL DEFAULT ''")
            logger.info("소스 라이브러리 인덱스 schema v2: preview_file 추가")
        except sqlite3.DatabaseError as exc:
            logger.warning("preview_file 마이그레이션 실패: %s", exc)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()


def normalize_root(root: str) -> str:
    """루트 경로 표기를 통일한다 (슬래시, 끝 슬래시 제거, 대소문자 유지)."""
    return str(root).replace("\\", "/").rstrip("/")


# ── 인덱싱 ────────────────────────────────────────────────────────────


def dir_needs_index(
    conn: sqlite3.Connection,
    root: str,
    dir_rel: str,
    dir_mtime: float,
) -> bool:
    """폴더 mtime 이 지난 인덱싱 때와 같으면 건너뛸 수 있다."""
    row = conn.execute(
        "SELECT mtime FROM dirs WHERE root=? AND dir_rel=?",
        (normalize_root(root), dir_rel),
    ).fetchone()
    if row is None:
        return True
    try:
        return abs(float(row["mtime"]) - float(dir_mtime)) > 1e-6
    except (TypeError, ValueError):
        return True


def replace_dir_items(
    conn: sqlite3.Connection,
    root: str,
    dir_rel: str,
    items: Sequence[LibraryItem],
    dir_mtime: float = 0.0,
) -> int:
    """폴더 하나의 항목을 통째로 갈아끼운다. 커밋은 호출자가 모아서 한다."""
    root_n = normalize_root(root)
    now = time.time()
    category = category_of(dir_rel)
    conn.execute("DELETE FROM items WHERE root=? AND dir_rel=?", (root_n, dir_rel))
    if items:
        conn.executemany(
            "INSERT INTO items("
            "root, dir_rel, category, name, name_lower, kind, ext, seq_pattern,"
            " representative, preview_file, frame_first, frame_last, frame_count,"
            " size_bytes, mtime, indexed_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    root_n,
                    dir_rel,
                    category,
                    it.name,
                    it.name.lower(),
                    it.kind,
                    it.ext,
                    it.seq_pattern,
                    it.representative,
                    str(getattr(it, "preview_file", "") or ""),
                    int(it.frame_first),
                    int(it.frame_last),
                    int(it.frame_count),
                    int(it.size_bytes),
                    float(it.mtime),
                    now,
                )
                for it in items
            ],
        )
    conn.execute(
        "INSERT OR REPLACE INTO dirs(root, dir_rel, mtime, indexed_at) VALUES (?,?,?,?)",
        (root_n, dir_rel, float(dir_mtime), now),
    )
    return len(items)


def known_dirs(conn: sqlite3.Connection, root: str) -> List[str]:
    """인덱스에 기록된 폴더 상대경로 목록."""
    rows = conn.execute("SELECT dir_rel FROM dirs WHERE root=?", (normalize_root(root),)).fetchall()
    return [str(r["dir_rel"]) for r in rows]


def prune_dirs(conn: sqlite3.Connection, root: str, alive_dirs: Iterable[str]) -> int:
    """사라진 폴더의 항목을 인덱스에서 지운다."""
    root_n = normalize_root(root)
    alive = set(alive_dirs)
    gone = [d for d in known_dirs(conn, root_n) if d not in alive]
    for dir_rel in gone:
        conn.execute("DELETE FROM items WHERE root=? AND dir_rel=?", (root_n, dir_rel))
        conn.execute("DELETE FROM dirs WHERE root=? AND dir_rel=?", (root_n, dir_rel))
    if gone:
        conn.commit()
    return len(gone)


def drop_root(conn: sqlite3.Connection, root: str) -> None:
    """루트 하나를 인덱스에서 완전히 제거한다 (설정에서 경로를 뺄 때)."""
    root_n = normalize_root(root)
    conn.execute("DELETE FROM items WHERE root=?", (root_n,))
    conn.execute("DELETE FROM dirs WHERE root=?", (root_n,))
    conn.commit()


# ── 조회 ──────────────────────────────────────────────────────────────


ItemCursor = Tuple[str, str, str, int]
"""페이징 커서 — 마지막으로 읽은 행의 ``(category, name_lower, dir_rel, id)``."""


FolderKey = Tuple[str, str]
"""``(root, dir_rel)`` — 그룹에 묶인 폴더 하나. ``dir_rel`` 은 임의 깊이(1단계 카테고리 포함)."""


def _where_clause(
    roots: Optional[Sequence[str]],
    category: str,
    dir_rel: str,
    query: str,
    after: Optional[ItemCursor] = None,
    folders: Optional[Sequence[FolderKey]] = None,
) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if folders:
        # 그룹 = 여러 (root, dir_rel) OR. roots/category 단일 필터보다 우선.
        # dir_rel prefix 매칭 — 1단계 카테고리든 깊은 하위폴더든 동일하게 그 하위 전체를 포함한다.
        # category_of(dir_rel) == X  ⟺  dir_rel == X or dir_rel.startswith(X + "/") 이므로
        # 기존 1단계 category exact-match와 결과가 100% 동일하다 (하위호환).
        parts: List[str] = []
        for root, rel in folders:
            root_n = normalize_root(root)
            rel_n = str(rel or "")
            if rel_n:
                parts.append("(root=? AND (dir_rel=? OR dir_rel LIKE ?))")
                params.extend([root_n, rel_n, rel_n + "/%"])
            else:
                parts.append("(root=? AND dir_rel=?)")
                params.extend([root_n, ""])
        if parts:
            clauses.append("(" + " OR ".join(parts) + ")")
    elif roots:
        norm = [normalize_root(r) for r in roots]
        clauses.append("root IN ({})".format(",".join("?" for _ in norm)))
        params.extend(norm)
        if category:
            clauses.append("category=?")
            params.append(category)
    elif category:
        clauses.append("category=?")
        params.append(category)
    if dir_rel:
        clauses.append("(dir_rel=? OR dir_rel LIKE ?)")
        params.extend([dir_rel, dir_rel + "/%"])
    q = (query or "").strip().lower()
    if q:
        # LIKE 특수문자를 이스케이프해 사용자가 % 를 입력해도 전체 매치가 되지 않게 한다.
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("name_lower LIKE ? ESCAPE '\\'")
        params.append("%{}%".format(esc))
    if after is not None:
        # 커서(seek) 페이징 — OFFSET 은 뒤 페이지로 갈수록 앞부분을 다시 훑어 급격히 느려진다.
        clauses.append(
            "(category > ? OR (category = ? AND (name_lower > ?"
            " OR (name_lower = ? AND (dir_rel > ? OR (dir_rel = ? AND id > ?))))))"
        )
        cat, name_lower, dir_r, row_id = after
        params.extend([cat, cat, name_lower, name_lower, dir_r, dir_r, int(row_id)])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def count_items(
    conn: sqlite3.Connection,
    roots: Optional[Sequence[str]] = None,
    category: str = "",
    dir_rel: str = "",
    query: str = "",
    folders: Optional[Sequence[FolderKey]] = None,
) -> int:
    where, params = _where_clause(roots, category, dir_rel, query, folders=folders)
    row = conn.execute("SELECT COUNT(*) AS n FROM items" + where, params).fetchone()
    return int(row["n"]) if row else 0


def fetch_items(
    conn: sqlite3.Connection,
    roots: Optional[Sequence[str]] = None,
    category: str = "",
    dir_rel: str = "",
    query: str = "",
    limit: int = 200,
    offset: int = 0,
    after: Optional[ItemCursor] = None,
    folders: Optional[Sequence[FolderKey]] = None,
) -> List[Dict[str, Any]]:
    """항목을 페이지 단위로 가져온다 (그리드가 스크롤하면서 조금씩 요청).

    수만 건에서는 ``offset`` 대신 :func:`cursor_of` 로 만든 ``after`` 를 넘겨야 한다.
    """
    where, params = _where_clause(roots, category, dir_rel, query, after, folders=folders)
    sql = (
        "SELECT id, root, dir_rel, category, name, name_lower, kind, ext, seq_pattern,"
        " representative, preview_file, frame_first, frame_last, frame_count,"
        " size_bytes, mtime FROM items"
        + where
        + " ORDER BY category, name_lower, dir_rel, id LIMIT ? OFFSET ?"
    )
    rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()
    return [dict(r) for r in rows]


def cursor_of(row: Dict[str, Any]) -> ItemCursor:
    """다음 페이지를 요청할 때 쓸 커서를 행에서 만든다."""
    return (
        str(row.get("category") or ""),
        str(row.get("name_lower") or ""),
        str(row.get("dir_rel") or ""),
        int(row.get("id") or 0),
    )


def list_categories(
    conn: sqlite3.Connection,
    roots: Optional[Sequence[str]] = None,
) -> List[Tuple[str, int]]:
    """카테고리(루트 바로 아래 폴더명)와 항목 수. 참고 이미지의 좌측 목록."""
    where, params = _where_clause(roots, "", "", "")
    sql = (
        "SELECT category, COUNT(*) AS n FROM items"
        + where
        + " GROUP BY category ORDER BY category COLLATE NOCASE"
    )
    rows = conn.execute(sql, params).fetchall()
    return [(str(r["category"]), int(r["n"])) for r in rows]


def list_folders(
    conn: sqlite3.Connection,
    roots: Optional[Sequence[str]] = None,
) -> List[Tuple[str, str, int]]:
    """``(root, category, count)`` — 그룹/기타 트리를 만들 때 쓴다."""
    where, params = _where_clause(roots, "", "", "")
    sql = (
        "SELECT root, category, COUNT(*) AS n FROM items"
        + where
        + " GROUP BY root, category ORDER BY root, category COLLATE NOCASE"
    )
    rows = conn.execute(sql, params).fetchall()
    return [(str(r["root"]), str(r["category"]), int(r["n"])) for r in rows]


def total_indexed(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()
    return int(row["n"]) if row else 0


def count_for_root(conn: sqlite3.Connection, root: str) -> int:
    """한 루트에 인덱싱된 항목 수."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE root=?",
        (normalize_root(root),),
    ).fetchone()
    return int(row["n"]) if row else 0


def roots_with_items(conn: sqlite3.Connection) -> List[str]:
    """인덱스에 항목이 1개 이상 있는 루트 목록."""
    rows = conn.execute("SELECT root FROM items GROUP BY root HAVING COUNT(*) > 0").fetchall()
    return [str(r["root"]) for r in rows]


def item_dir_path(row: Dict[str, Any]) -> str:
    """행에서 실제 폴더 절대경로를 복원한다."""
    return row_dir_path(row)


def find_sequence_frame_range(
    conn: sqlite3.Connection, root: str, dir_rel: str, filename: str
) -> Optional[Tuple[int, int]]:
    """``dir_rel`` 폴더의 시퀀스 항목 중 ``filename`` 과 같은 시퀀스로 보이는 것의
    ``(frame_first, frame_last)``. 못 찾으면 ``None``.

    ``filename`` 은 실제 프레임 파일명(``plate.1001.exr``)이든 ``%0Nd`` 패턴
    (``plate.%04d.exr``)이든 상관없다 — 둘 다 프레임 토큰을 지워 비교한다.
    Nuke 가 드래그로 직접 만든 Read 노드의 ``file`` knob 을 BPE 인덱스와 대조해
    정확한 프레임 범위로 사후 교정할 때 쓴다.
    """
    name_base = str(filename or "").rsplit("/", 1)[-1]
    if not name_base:
        return None
    stem, ext = split_name_ext(name_base)
    target = _SEQ_TOKEN_RE.sub("", stem)
    if not target:
        return None
    rows = conn.execute(
        "SELECT seq_pattern, frame_first, frame_last FROM items"
        " WHERE root=? AND dir_rel=? AND kind=?",
        (normalize_root(root), dir_rel, KIND_SEQUENCE),
    ).fetchall()
    for row in rows:
        pattern = str(row["seq_pattern"] or "")
        pbase = pattern.rsplit("/", 1)[-1]
        pstem, pext = split_name_ext(pbase)
        if pext != ext:
            continue
        if _SEQ_TOKEN_RE.sub("", pstem) == target:
            return int(row["frame_first"]), int(row["frame_last"])
    return None
