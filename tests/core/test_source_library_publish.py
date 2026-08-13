"""소스 라이브러리 인덱스 게시/수신 — 미디어 루트에는 쓰지 않음."""

from __future__ import annotations

from pathlib import Path

from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core import source_library_publish as publish
from bpe.core.source_library_scan import FileEntry, group_entries


def test_publish_and_pull_roundtrip(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)

    media = tmp_path / "media"
    media.mkdir()
    (media / "a.mov").write_bytes(b"123")

    conn = db.connect(tmp_app_dir / "cache" / "source_library.sqlite")
    try:
        items = group_entries([FileEntry("a.mov", 3, 1.0)])
        db.replace_dir_items(conn, str(media).replace("\\", "/"), "", items)
        conn.commit()
        meta = publish.publish_index(conn)
    finally:
        conn.close()

    assert meta["items"] == 1
    assert (shared / "index" / "library.sqlite").is_file()
    assert (shared / "index" / "index.json").is_file()
    # 미디어 폴더는 그대로
    assert list(media.iterdir()) == [media / "a.mov"]

    # 로컬 마커를 지워 pull 이 필요하게 만든다
    marker = publish.local_marker_path()
    if marker.is_file():
        marker.unlink()
    # 로컬 DB 삭제 후 pull
    local_db = db.index_path()
    if local_db.is_file():
        local_db.unlink()

    assert publish.needs_pull() is True
    pulled = publish.pull_index()
    assert pulled is not None
    assert pulled["items"] == 1
    assert local_db.is_file()

    conn2 = db.connect()
    try:
        assert db.total_indexed(conn2) == 1
    finally:
        conn2.close()


def test_needs_pull_false_when_same(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)
    conn = db.connect()
    try:
        publish.publish_index(conn)
    finally:
        conn.close()
    assert publish.needs_pull() is False
    assert publish.needs_pull_reason() is None
    meta, err = publish.try_pull_index_with_status()
    assert meta is None
    assert err is None


def test_needs_pull_when_items_mismatch(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    """마커 시각이 같아도 로컬 건수가 공유보다 적으면 pull."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)

    media_a = tmp_path / "a"
    media_b = tmp_path / "b"
    media_a.mkdir()
    media_b.mkdir()
    (media_a / "1.mov").write_bytes(b"x")
    (media_b / "2.mov").write_bytes(b"y")

    conn = db.connect()
    try:
        from bpe.core.source_library_scan import FileEntry, group_entries

        db.replace_dir_items(
            conn,
            str(media_a).replace("\\", "/"),
            "",
            group_entries([FileEntry("1.mov", 1, 1.0)]),
        )
        db.replace_dir_items(
            conn,
            str(media_b).replace("\\", "/"),
            "",
            group_entries([FileEntry("2.mov", 1, 1.0)]),
        )
        conn.commit()
        publish.publish_index(conn)
    finally:
        conn.close()

    # 로컬에서 b 루트만 삭제 — 마커는 그대로
    conn2 = db.connect()
    try:
        db.drop_root(conn2, str(media_b).replace("\\", "/"))
        assert db.total_indexed(conn2) == 1
    finally:
        conn2.close()

    reason = publish.needs_pull_reason()
    assert reason is not None
    assert "items_mismatch" in reason
    assert publish.needs_pull() is True
    meta = publish.pull_index()
    assert meta is not None
    conn3 = db.connect()
    try:
        assert db.total_indexed(conn3) == 2
    finally:
        conn3.close()


def test_publish_writes_grouping_version(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)
    conn = db.connect()
    try:
        meta = publish.publish_index(conn)
    finally:
        conn.close()
    assert meta["grouping_version"] == publish.GROUPING_VERSION
    assert publish.read_shared_meta()["grouping_version"] == publish.GROUPING_VERSION
    assert publish.shared_grouping_outdated() is False


def test_pull_refused_for_outdated_grouping(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    """구버전(그룹핑 버전 없음=0) 게시본은 published_at 이 더 새로워도 pull 하지 않는다."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)

    conn = db.connect()
    try:
        items = group_entries([FileEntry("a.mov", 3, 1.0)])
        db.replace_dir_items(conn, str(tmp_path / "m").replace("\\", "/"), "", items)
        conn.commit()
        publish.publish_index(conn)
    finally:
        conn.close()

    # 구버전이 재게시한 상황 재현: meta 에서 grouping_version 을 제거하고 시각을 미래로
    from bpe.core.atomic_io import read_json_file, write_json_file

    meta_path = publish.shared_meta_path()
    meta = read_json_file(meta_path, {})
    meta.pop("grouping_version", None)
    meta["published_at"] = "2999-01-01T00:00:00Z"
    meta["items"] = 999
    write_json_file(meta_path, meta)

    assert publish.shared_grouping_outdated() is True
    assert publish.needs_pull_reason() is None
    assert publish.needs_pull() is False
    meta2, err = publish.try_pull_index_with_status()
    assert meta2 is None
    assert err is None


def test_needs_pull_when_root_missing_locally(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)

    media_a = tmp_path / "elem"
    media_b = tmp_path / "mmk"
    media_a.mkdir()
    media_b.mkdir()
    (media_a / "1.mov").write_bytes(b"x")
    (media_b / "2.mov").write_bytes(b"y")
    root_a = str(media_a).replace("\\", "/")
    root_b = str(media_b).replace("\\", "/")

    # library.json 에 두 루트 등록
    data = libcfg.empty_library()
    libcfg.set_scope(
        data,
        libcfg.COMMON_SCOPE,
        [root_a, root_b],
        [
            {"name": libcfg.COMMON_LABEL, "folders": [root_a]},
            {"name": "MMK_028", "folders": [root_b]},
        ],
    )
    libcfg.save_library(data)

    from bpe.core.source_library_scan import FileEntry, group_entries

    conn = db.connect()
    try:
        db.replace_dir_items(conn, root_a, "", group_entries([FileEntry("1.mov", 1, 1.0)]))
        db.replace_dir_items(conn, root_b, "", group_entries([FileEntry("2.mov", 1, 1.0)]))
        conn.commit()
        publish.publish_index(conn)
    finally:
        conn.close()

    conn2 = db.connect()
    try:
        db.drop_root(conn2, root_b)
    finally:
        conn2.close()

    # items_mismatch 가 먼저 걸릴 수 있음 — 어느 쪽이든 pull 필요
    assert publish.needs_pull() is True
    publish.pull_index()
    conn3 = db.connect()
    try:
        assert db.count_for_root(conn3, root_b) == 1
    finally:
        conn3.close()
