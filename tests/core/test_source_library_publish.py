"""소스 라이브러리 인덱스 게시/수신 — 미디어 루트에는 쓰지 않음."""

from __future__ import annotations

from pathlib import Path

from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core import source_library_publish as publish
from bpe.core.source_library_scan import FileEntry, group_entries

# ── 설정 「새로고침」 판정 ────────────────────────────────────────────

_R = "W:/proj/clips"


def _snap(items: int, digest: str, cats=None):
    return {
        "roots": {_R: {"items": items, "digest": digest}},
        "categories": {_R: dict(cats or {})},
    }


def _decide(baseline, after, **kw):
    opts = {"read_failures": 0, "shared_grouping_version": 2, "shared_moved": False}
    opts.update(kw)
    return publish.refresh_publish_decision(baseline, after, **opts)


def test_refresh_decision_unknown_when_snapshot_missing():
    assert _decide(None, _snap(1, "a")) == (False, publish.REFRESH_UNKNOWN)
    assert _decide(_snap(1, "a"), None) == (False, publish.REFRESH_UNKNOWN)


def test_refresh_decision_unknown_when_root_missing_in_baseline():
    after = {"roots": {"W:/other": {"items": 1, "digest": "x"}}, "categories": {}}
    assert _decide(_snap(1, "a"), after) == (False, publish.REFRESH_UNKNOWN)


def test_refresh_decision_read_error_wins_over_everything():
    assert _decide(_snap(1, "a"), _snap(5, "b"), read_failures=2) == (
        False,
        publish.REFRESH_READ_ERROR,
    )


def test_refresh_decision_unchanged():
    assert _decide(_snap(3, "a"), _snap(3, "a")) == (False, publish.REFRESH_UNCHANGED)


def test_refresh_decision_changed_publishes():
    assert _decide(_snap(3, "a"), _snap(10, "b")) == (True, publish.REFRESH_CHANGED)


def test_refresh_decision_rename_same_count_publishes():
    assert _decide(_snap(3, "a"), _snap(3, "b")) == (True, publish.REFRESH_CHANGED)


def test_refresh_decision_shared_newer_format():
    assert _decide(_snap(3, "a"), _snap(4, "b"), shared_grouping_version=99) == (
        False,
        publish.REFRESH_SHARED_NEWER_FORMAT,
    )


def test_refresh_decision_shared_moved():
    assert _decide(_snap(3, "a"), _snap(4, "b"), shared_moved=True) == (
        False,
        publish.REFRESH_SHARED_MOVED,
    )


def test_refresh_decision_small_loss_publishes_big_loss_holds():
    # 기준 1000개: 허용 감소 = max(200, 20) = 200
    assert _decide(_snap(1000, "a"), _snap(800, "b")) == (True, publish.REFRESH_CHANGED)
    assert _decide(_snap(1000, "a"), _snap(799, "b")) == (False, publish.REFRESH_BIG_LOSS)
    # 기준 100000개: 허용 감소 = max(200, 2000) = 2000
    assert _decide(_snap(100000, "a"), _snap(98000, "b")) == (True, publish.REFRESH_CHANGED)
    assert _decide(_snap(100000, "a"), _snap(97999, "b")) == (False, publish.REFRESH_BIG_LOSS)


def test_new_top_folders_lists_only_newly_appeared():
    base = _snap(3, "a", {"KMM_old": 3, "_PDf": 0})
    after = _snap(9, "b", {"KMM_old": 5, "KMM_new2": 2, "KMM_new1": 2, "": 1, "_PDf": 0})
    assert publish.new_top_folders(base, after) == ["KMM_new1", "KMM_new2"]
    assert publish.new_top_folders(None, after) == []


def test_merge_refresh_baseline_resets_when_published_at_differs():
    old = {"published_at": "2026-09-01T00:00:00Z", **_snap(1, "old")}
    cur = _snap(5, "cur")
    merged = publish.merge_refresh_baseline(old, "2026-09-02T00:00:00Z", cur, [_R])
    assert merged == {"published_at": "2026-09-02T00:00:00Z", **cur}


def test_merge_refresh_baseline_keeps_existing_and_fills_new_roots():
    old = {"published_at": "T1", **_snap(1, "old")}
    cur = {
        "roots": {_R: {"items": 7, "digest": "cur"}, "W:/b": {"items": 2, "digest": "bb"}},
        "categories": {_R: {"x": 7}, "W:/b": {"y": 2}},
    }
    merged = publish.merge_refresh_baseline(old, "T1", cur, [_R, "W:/b"])
    assert merged is not None
    assert merged["roots"][_R] == {"items": 1, "digest": "old"}
    assert merged["roots"]["W:/b"] == {"items": 2, "digest": "bb"}
    assert merged["categories"]["W:/b"] == {"y": 2}


def test_merge_refresh_baseline_none_when_snapshot_failed():
    assert publish.merge_refresh_baseline({}, "T1", None, [_R]) is None


def test_refresh_retry_after_read_error_publishes():
    """1차가 폴더 못 읽어 보류되면(성공분은 로컬에 이미 반영) 2차는 기준선 대비 변경으로 게시."""
    baseline = publish.merge_refresh_baseline({}, "T1", _snap(10, "team"), [_R])
    # 1차: 일부 반영 + 읽기 실패 → 보류, 기준선은 그대로 저장돼 있음
    assert _decide(baseline, _snap(12, "partial"), read_failures=1)[0] is False
    # 2차 시작: 로컬 before 는 이미 partial 이지만 같은 published_at 이라 기준선 유지
    baseline2 = publish.merge_refresh_baseline(baseline, "T1", _snap(12, "partial"), [_R])
    assert baseline2 == baseline
    assert _decide(baseline2, _snap(15, "full")) == (True, publish.REFRESH_CHANGED)


def test_refresh_retry_after_big_loss_still_holds():
    baseline = publish.merge_refresh_baseline({}, "T1", _snap(1000, "team"), [_R])
    assert _decide(baseline, _snap(500, "lost")) == (False, publish.REFRESH_BIG_LOSS)
    # 2차: 줄어든 로컬에 새 파일 조금 — 기준선은 여전히 팀 장부(1000)
    baseline2 = publish.merge_refresh_baseline(baseline, "T1", _snap(500, "lost"), [_R])
    assert _decide(baseline2, _snap(510, "lost+new")) == (False, publish.REFRESH_BIG_LOSS)


def test_refresh_baseline_file_roundtrip(tmp_app_dir: Path):
    assert publish.read_refresh_baseline() == {}
    data = {"published_at": "T1", **_snap(3, "a", {"x": 3})}
    publish.write_refresh_baseline(data)
    assert publish.refresh_baseline_path().parent == tmp_app_dir / "cache"
    assert publish.read_refresh_baseline() == data


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
