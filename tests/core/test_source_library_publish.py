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


def test_pull_succeeds_while_local_db_handle_is_open(
    tmp_path: Path, monkeypatch, tmp_app_dir: Path
):
    """GUI 가 로컬 DB 를 열어둔 채로도 pull 이 성공해야 한다 (신규 PC 시나리오).

    예전 구현(os.replace 파일 교체)은 Windows 에서 열린 sqlite 핸들 때문에
    PermissionError 로 실패해, 신규 PC 가 라이브러리를 영영 못 받았다 (실측 재현).
    backup 방식은 열린 핸들과 공존한다.
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(libcfg, "config_dir", lambda: shared)

    # 공유본 게시 (항목 1개)
    conn = db.connect()
    try:
        items = group_entries([FileEntry("a.mov", 3, 1.0)])
        db.replace_dir_items(conn, str(tmp_path / "m").replace("\\", "/"), "", items)
        conn.commit()
        publish.publish_index(conn)
    finally:
        conn.close()

    # 신규 PC 재현: 로컬 DB 비우고 마커 삭제
    marker = publish.local_marker_path()
    if marker.is_file():
        marker.unlink()
    local_db = db.index_path()
    if local_db.is_file():
        local_db.unlink()

    # GUI 처럼 로컬 DB 를 미리 열어둔다 (빈 스키마 생성 + 핸들 유지)
    held = db.connect()
    try:
        assert db.total_indexed(held) == 0
        meta = publish.pull_index()
        assert meta is not None and meta["items"] == 1
        # 열려 있던 핸들도 새 내용을 본다 (backup 은 파일 교체가 아니라 내용 교체)
        assert db.total_indexed(held) == 1
    finally:
        held.close()


def test_unknown_local_count_does_not_force_pull(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    """로컬 건수 조회 실패(락 등)="모름" — 건수 비교 pull 이 오발되면 안 된다.

    예전엔 실패를 0으로 취급해 items_mismatch 가 성립, 멀쩡한(혹은 방금 스캔한)
    로컬 인덱스를 공유본으로 되돌렸다 (스캔 취소/락 함정).
    """
    import sqlite3 as _sqlite3

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

    # 로컬 DB 열기가 실패하는 상황(락/손상) 재현
    def _boom(path=None):
        raise _sqlite3.DatabaseError("database is locked")

    monkeypatch.setattr(db, "connect", _boom)
    assert publish._local_total_safe() is None
    # 건수 비교 분기가 스킵되어 pull 사유가 없어야 한다
    assert publish.needs_pull_reason() is None
    # 커버리지 조회도 "전부 빠짐"이 아니라 빈 리스트(오발 방지)
    assert publish.roots_missing_from_local(["W:/lib"]) == []


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
