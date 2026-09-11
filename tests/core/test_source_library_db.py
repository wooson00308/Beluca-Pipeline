"""소스 라이브러리 SQLite 인덱스 — upsert/조회/정리 테스트."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from bpe.core import source_library_db as db
from bpe.core.source_library_scan import FileEntry, group_entries

_ROOT = "W:/lib"


def _items(names: List[str]):
    return group_entries([FileEntry(n, 100, 10.0) for n in names])


@pytest.fixture()
def conn(tmp_path: Path):
    c = db.connect(tmp_path / "idx.sqlite")
    yield c
    c.close()


def test_connect_creates_file_and_schema(tmp_path: Path):
    p = tmp_path / "sub" / "idx.sqlite"
    c = db.connect(p)
    try:
        assert p.is_file()
        names = {
            r["name"]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"items", "dirs", "meta"} <= names
    finally:
        c.close()


def test_index_path_follows_config(tmp_app_dir: Path):
    assert db.index_path().parent == tmp_app_dir / "cache"


def test_replace_dir_items_and_fetch(conn):
    n = db.replace_dir_items(conn, _ROOT, "Fire", _items(["f.1001.exr", "f.1002.exr", "x.mov"]))
    conn.commit()
    assert n == 2
    rows = db.fetch_items(conn, roots=[_ROOT])
    assert [r["name"] for r in rows] == ["f", "x"]
    assert all(r["category"] == "Fire" for r in rows)
    assert db.count_items(conn, roots=[_ROOT]) == 2


def test_replace_dir_items_is_idempotent(conn):
    for _ in range(3):
        db.replace_dir_items(conn, _ROOT, "Fire", _items(["f.1001.exr", "f.1002.exr"]))
    conn.commit()
    assert db.count_items(conn, roots=[_ROOT]) == 1


def test_replace_dir_items_removes_deleted_files(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    conn.commit()
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]))
    conn.commit()
    assert [r["name"] for r in db.fetch_items(conn, roots=[_ROOT])] == ["a"]


def test_dir_needs_index_uses_mtime(conn):
    assert db.dir_needs_index(conn, _ROOT, "Fire", 100.0) is True
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]), dir_mtime=100.0)
    conn.commit()
    assert db.dir_needs_index(conn, _ROOT, "Fire", 100.0) is False
    assert db.dir_needs_index(conn, _ROOT, "Fire", 200.0) is True


def _snap(conn, roots=None):
    return db.refresh_snapshot(conn, roots or [_ROOT])


def test_refresh_snapshot_counts_and_categories(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    db.replace_dir_items(conn, _ROOT, "Rain/sub", _items(["c.mov"]))
    db.replace_dir_items(conn, "W:/other", "X", _items(["z.mov"]))
    conn.commit()
    snap = _snap(conn)
    assert list(snap["roots"].keys()) == [_ROOT]
    assert snap["roots"][_ROOT]["items"] == 3
    assert snap["categories"][_ROOT] == {"Fire": 2, "Rain": 1}


def test_refresh_snapshot_empty_root(conn):
    snap = _snap(conn)
    assert snap["roots"][_ROOT]["items"] == 0
    assert snap["categories"][_ROOT] == {}


def test_refresh_snapshot_digest_stable_on_reindex(conn, monkeypatch):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]), dir_mtime=1.0)
    conn.commit()
    before = _snap(conn)
    # 같은 내용으로 다시 인덱싱(재인덱싱 시각·폴더 mtime 만 바뀜) → 변경 아님
    monkeypatch.setattr(db.time, "time", lambda: 9_999_999.0)
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]), dir_mtime=2.0)
    conn.commit()
    assert _snap(conn) == before


def test_refresh_snapshot_digest_detects_add_rename_size(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]))
    conn.commit()
    base = _snap(conn)["roots"][_ROOT]["digest"]

    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    conn.commit()
    added = _snap(conn)["roots"][_ROOT]["digest"]
    assert added != base

    db.replace_dir_items(conn, _ROOT, "Fire", _items(["c.mov"]))
    conn.commit()
    renamed = _snap(conn)["roots"][_ROOT]["digest"]
    assert renamed not in (base, added)

    db.replace_dir_items(conn, _ROOT, "Fire", group_entries([FileEntry("c.mov", 999, 10.0)]))
    conn.commit()
    assert _snap(conn)["roots"][_ROOT]["digest"] != renamed


def test_refresh_snapshot_digest_detects_frame_range_growth(conn):
    seq = ["f.1001.exr", "f.1002.exr"]
    db.replace_dir_items(conn, _ROOT, "Fire", _items(seq))
    conn.commit()
    before = _snap(conn)
    db.replace_dir_items(conn, _ROOT, "Fire", _items(seq + ["f.1003.exr"]))
    conn.commit()
    after = _snap(conn)
    assert after["roots"][_ROOT]["items"] == before["roots"][_ROOT]["items"] == 1
    assert after["roots"][_ROOT]["digest"] != before["roots"][_ROOT]["digest"]


def test_refresh_snapshot_deterministic_with_same_stem(tmp_path: Path):
    """``a.mov`` + ``a.mp4`` 처럼 이름이 같은 항목도 삽입 순서와 무관하게 같은 digest."""
    digests = []
    for i, order in enumerate((["a.mov", "a.mp4"], ["a.mp4", "a.mov"])):
        c = db.connect(tmp_path / "idx{}.sqlite".format(i))
        try:
            # 삽입 순서(id)만 다르게 — 정렬이 모든 컬럼 기준이면 digest 가 같아야 한다
            for name in order:
                c.execute(
                    "INSERT INTO items(root, dir_rel, category, name, name_lower, kind, ext)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (_ROOT, "Fire", "Fire", "a", "a", "movie", name[-4:]),
                )
            c.commit()
            digests.append(db.refresh_snapshot(c, [_ROOT])["roots"][_ROOT]["digest"])
        finally:
            c.close()
    assert digests[0] == digests[1]


def test_fetch_items_paging(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov", "c.mov", "d.mov"]))
    conn.commit()
    first = db.fetch_items(conn, roots=[_ROOT], limit=2, offset=0)
    second = db.fetch_items(conn, roots=[_ROOT], limit=2, offset=2)
    assert [r["name"] for r in first] == ["a", "b"]
    assert [r["name"] for r in second] == ["c", "d"]


def test_cursor_paging_walks_every_row_once(conn):
    names = ["clip_{:03d}.mov".format(i) for i in range(250)]
    for cat in ("Fire", "Rain"):
        db.replace_dir_items(conn, _ROOT, cat, _items(names))
    conn.commit()

    seen = []
    cursor = None
    while True:
        page = db.fetch_items(conn, roots=[_ROOT], limit=40, after=cursor)
        if not page:
            break
        seen.extend((r["category"], r["name"]) for r in page)
        cursor = db.cursor_of(page[-1])

    assert len(seen) == 500
    assert len(set(seen)) == 500  # 중복/누락 없음
    assert seen == sorted(seen)  # 정렬 순서 유지


def test_cursor_paging_matches_offset_paging(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov", "c.mov", "d.mov"]))
    conn.commit()
    first = db.fetch_items(conn, roots=[_ROOT], limit=2)
    by_offset = db.fetch_items(conn, roots=[_ROOT], limit=2, offset=2)
    by_cursor = db.fetch_items(conn, roots=[_ROOT], limit=2, after=db.cursor_of(first[-1]))
    assert [r["name"] for r in by_cursor] == [r["name"] for r in by_offset] == ["c", "d"]


def test_cursor_respects_other_filters(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["fire_a.mov", "fire_b.mov"]))
    db.replace_dir_items(conn, _ROOT, "Rain", _items(["fire_c.mov"]))
    conn.commit()
    page = db.fetch_items(conn, roots=[_ROOT], category="Fire", query="fire", limit=1)
    nxt = db.fetch_items(
        conn, roots=[_ROOT], category="Fire", query="fire", limit=5, after=db.cursor_of(page[-1])
    )
    assert [r["name"] for r in page] == ["fire_a"]
    assert [r["name"] for r in nxt] == ["fire_b"]


def test_fetch_items_returns_cursor_columns(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]))
    conn.commit()
    row = db.fetch_items(conn, roots=[_ROOT])[0]
    assert {"id", "name_lower", "category", "dir_rel"} <= set(row)
    assert db.cursor_of(row) == ("Fire", "a", "Fire", row["id"])


def test_search_by_name_is_case_insensitive(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["BigSmoke.mov", "tiny_fire.mov"]))
    conn.commit()
    assert [r["name"] for r in db.fetch_items(conn, roots=[_ROOT], query="smoke")] == ["BigSmoke"]
    assert [r["name"] for r in db.fetch_items(conn, roots=[_ROOT], query="FIRE")] == ["tiny_fire"]


def test_search_escapes_like_wildcards(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    conn.commit()
    # '%' 를 그대로 넘기면 전체가 매치돼 버리므로 이스케이프되어야 한다.
    assert db.fetch_items(conn, roots=[_ROOT], query="%") == []


def test_filter_by_category_and_dir(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["f.mov"]))
    db.replace_dir_items(conn, _ROOT, "Fire/sub", _items(["deep.mov"]))
    db.replace_dir_items(conn, _ROOT, "Rain", _items(["r.mov"]))
    conn.commit()
    assert db.count_items(conn, roots=[_ROOT], category="Fire") == 2
    assert db.count_items(conn, roots=[_ROOT], category="Rain") == 1
    assert [r["name"] for r in db.fetch_items(conn, roots=[_ROOT], dir_rel="Fire/sub")] == ["deep"]


def test_list_categories_with_counts(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    db.replace_dir_items(conn, _ROOT, "Rain", _items(["c.mov"]))
    conn.commit()
    assert db.list_categories(conn, roots=[_ROOT]) == [("Fire", 2), ("Rain", 1)]


def test_list_folders_and_folders_filter(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov", "b.mov"]))
    db.replace_dir_items(conn, _ROOT, "Rain", _items(["c.mov"]))
    db.replace_dir_items(conn, "W:/other", "X", _items(["d.mov"]))
    conn.commit()
    assert db.list_folders(conn, roots=[_ROOT]) == [
        (_ROOT, "Fire", 2),
        (_ROOT, "Rain", 1),
    ]
    rows = db.fetch_items(
        conn,
        folders=[(_ROOT, "Fire"), ("W:/other", "X")],
    )
    assert sorted(r["name"] for r in rows) == ["a", "b", "d"]
    assert db.count_items(conn, folders=[(_ROOT, "Rain")]) == 1


def test_folders_filter_supports_deep_dir_rel(conn):
    """다단계 서버 구조 — folders 키가 1단계 category 를 넘어 임의 깊이를 지원해야 한다."""
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["top.mov"]))
    db.replace_dir_items(conn, _ROOT, "Fire/sub", _items(["deep.mov"]))
    conn.commit()
    # 깊은 키(dir_rel="Fire/sub")는 그 하위만 정확히 잡는다.
    assert db.count_items(conn, folders=[(_ROOT, "Fire/sub")]) == 1
    assert [r["name"] for r in db.fetch_items(conn, folders=[(_ROOT, "Fire/sub")])] == ["deep"]
    # 1단계 키(dir_rel="Fire")는 자기 자신 + 하위 전체를 합산한다 —
    # 기존 category exact-match와 결과가 동일해야 하는 하위호환 지점.
    assert db.count_items(conn, folders=[(_ROOT, "Fire")]) == 2


def test_prune_dirs_removes_vanished_folders(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]))
    db.replace_dir_items(conn, _ROOT, "Gone", _items(["b.mov"]))
    conn.commit()
    removed = db.prune_dirs(conn, _ROOT, ["Fire"])
    assert removed == 1
    assert [r["name"] for r in db.fetch_items(conn, roots=[_ROOT])] == ["a"]


def test_drop_root(conn):
    db.replace_dir_items(conn, _ROOT, "Fire", _items(["a.mov"]))
    db.replace_dir_items(conn, "W:/other", "X", _items(["b.mov"]))
    conn.commit()
    db.drop_root(conn, _ROOT)
    assert db.count_items(conn, roots=[_ROOT]) == 0
    assert db.count_items(conn, roots=["W:/other"]) == 1


def test_normalize_root_handles_backslash_and_trailing_slash(conn):
    db.replace_dir_items(conn, "W:\\lib\\", "Fire", _items(["a.mov"]))
    conn.commit()
    assert db.count_items(conn, roots=["W:/lib"]) == 1


def test_item_dir_path():
    assert db.item_dir_path({"root": "W:/lib", "dir_rel": "Fire"}) == "W:/lib/Fire"
    assert db.item_dir_path({"root": "W:/lib", "dir_rel": ""}) == "W:/lib"


def test_find_sequence_frame_range_matches_literal_and_pattern_filename(conn):
    from bpe.core.source_library_scan import KIND_SEQUENCE, LibraryItem

    item = LibraryItem(
        name="plate_a",
        kind=KIND_SEQUENCE,
        ext=".exr",
        seq_pattern="plate.%04d.exr",
        representative="plate.1001.exr",
        frame_first=1001,
        frame_last=1100,
        frame_count=100,
        size_bytes=100,
        mtime=1.0,
    )
    db.replace_dir_items(conn, _ROOT, "Fire", [item])
    conn.commit()
    # 실제 프레임 파일명(한 프레임)으로 조회 — Nuke 가 아직 패턴으로 안 뭉쳤을 때
    assert db.find_sequence_frame_range(conn, _ROOT, "Fire", "plate.1050.exr") == (1001, 1100)
    # %0Nd 패턴 문자열로도 조회 — Nuke 가 이미 시퀀스로 인식했을 때
    assert db.find_sequence_frame_range(conn, _ROOT, "Fire", "plate.%04d.exr") == (1001, 1100)
    # 다른 폴더/이름은 매치 없음
    assert db.find_sequence_frame_range(conn, _ROOT, "Rain", "plate.1050.exr") is None
    assert db.find_sequence_frame_range(conn, _ROOT, "Fire", "other.1050.exr") is None


def test_preview_file_roundtrip(conn):
    from bpe.core.source_library_scan import KIND_SEQUENCE, LibraryItem

    pack = LibraryItem(
        name="pack",
        kind=KIND_SEQUENCE,
        ext=".exr",
        seq_pattern="image/p.%04d.exr",
        representative="pack.jpg",
        frame_first=1,
        frame_last=3,
        frame_count=3,
        size_bytes=100,
        mtime=1.0,
        preview_file="pack.thumb.mov",
    )
    db.replace_dir_items(conn, _ROOT, "Glass/pack", [pack])
    conn.commit()
    row = db.fetch_items(conn, roots=[_ROOT])[0]
    assert row["preview_file"] == "pack.thumb.mov"
    assert row["representative"] == "pack.jpg"
    assert row["seq_pattern"] == "image/p.%04d.exr"


def test_schema_migrates_preview_file(tmp_path: Path):
    """v1 DB 에 preview_file 이 없으면 connect 시 ALTER 로 추가한다."""
    import sqlite3

    path = tmp_path / "old.sqlite"
    c = sqlite3.connect(str(path))
    c.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            root TEXT, dir_rel TEXT, category TEXT DEFAULT '',
            name TEXT, name_lower TEXT DEFAULT '', kind TEXT,
            ext TEXT DEFAULT '', seq_pattern TEXT DEFAULT '',
            representative TEXT DEFAULT '',
            frame_first INTEGER DEFAULT 0, frame_last INTEGER DEFAULT 0,
            frame_count INTEGER DEFAULT 1, size_bytes INTEGER DEFAULT 0,
            mtime REAL DEFAULT 0, indexed_at REAL DEFAULT 0
        );
        CREATE TABLE dirs (root TEXT, dir_rel TEXT, mtime REAL, indexed_at REAL,
                           PRIMARY KEY (root, dir_rel));
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');
        """
    )
    c.commit()
    c.close()

    conn = db.connect(path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
        assert "preview_file" in cols
        ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        assert ver == "2"
    finally:
        conn.close()
