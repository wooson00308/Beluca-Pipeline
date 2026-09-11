# @cursor-change: 2026-08-11, 0.13.x, 팩 후 image/ 고아 prune 테스트
"""LibraryScanWorker — 시그널 이름 충돌 방지와 실제 폴더 인덱싱 동작."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from bpe.core import source_library_db as db
from bpe.gui.workers.library_scan_worker import LibraryScanWorker


def test_worker_does_not_redefine_qthread_finished() -> None:
    """QThread.finished() 와 겹치면 완료 콜백이 두 번 호출된다."""
    assert "finished" not in LibraryScanWorker.__dict__
    assert "scan_done" in LibraryScanWorker.__dict__
    assert "scan_aborted" in LibraryScanWorker.__dict__
    assert "scan_error" in LibraryScanWorker.__dict__
    assert "progress" in LibraryScanWorker.__dict__


def test_worker_with_no_roots_reports_zero() -> None:
    seen: List[int] = []
    w = LibraryScanWorker([])
    w.scan_done.connect(seen.append)
    w.run()  # 스레드를 띄우지 않고 본문만 직접 실행
    assert seen == [0]


def test_worker_indexes_folders_and_groups_sequences(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    (lib / "Fire").mkdir(parents=True)
    (lib / "Rain").mkdir(parents=True)
    for n in ("f.1001.exr", "f.1002.exr", "f.1003.exr"):
        (lib / "Fire" / n).write_bytes(b"x")
    (lib / "Rain" / "drops.mov").write_bytes(b"x")
    (lib / "Rain" / "notes.txt").write_bytes(b"x")

    done: List[int] = []
    errors: List[str] = []
    w = LibraryScanWorker([str(lib)])
    w.scan_done.connect(done.append)
    w.scan_error.connect(errors.append)
    w.run()

    assert errors == []
    assert done == [2]  # 시퀀스 1벌 + mov 1개

    conn = db.connect()
    try:
        assert db.list_categories(conn, roots=[str(lib)]) == [("Fire", 1), ("Rain", 1)]
        rows = db.fetch_items(conn, roots=[str(lib)])
        by_name = {r["name"]: r for r in rows}
        assert by_name["f"]["seq_pattern"] == "f.%04d.exr"
        assert (by_name["f"]["frame_first"], by_name["f"]["frame_last"]) == (1001, 1003)
        assert by_name["drops"]["kind"] == "movie"
    finally:
        conn.close()


def test_second_run_skips_unchanged_folders(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    (lib / "Fire").mkdir(parents=True)
    (lib / "Fire" / "a.mov").write_bytes(b"x")

    results: List[int] = []
    for _ in range(2):
        w = LibraryScanWorker([str(lib)])
        w.scan_done.connect(results.append)
        w.run()

    # 폴더 mtime 이 그대로면 두 번째 스캔은 다시 인덱싱하지 않는다.
    assert results[0] == 1
    assert results[1] == 0

    conn = db.connect()
    try:
        assert db.count_items(conn, roots=[str(lib)]) == 1
    finally:
        conn.close()


# ── strict (설정 「새로고침」 안전 모드) ────────────────────────────────


def _norm(p: object) -> str:
    return str(p).replace("\\", "/").rstrip("/")


def _fail_reading(monkeypatch, failing: List[Path]) -> List[str]:
    """``failing`` 경로의 폴더 읽기를 실패로 만든다. 실제로 불린 경로 목록을 돌려준다."""
    import bpe.gui.workers.library_scan_worker as lsw

    real = lsw.read_dir_checked
    called: List[str] = []
    bad = {_norm(p) for p in failing}

    def fake(path: str):
        called.append(_norm(path))
        if _norm(path) in bad:
            return [], [], False
        return real(path)

    monkeypatch.setattr(lsw, "read_dir_checked", fake)
    return called


def _dirs(lib: Path) -> List[str]:
    conn = db.connect()
    try:
        return sorted(db.known_dirs(conn, str(lib)))
    finally:
        conn.close()


def _names(lib: Path) -> List[str]:
    conn = db.connect()
    try:
        return sorted(r["name"] for r in db.fetch_items(conn, roots=[str(lib)]))
    finally:
        conn.close()


def _make_days(tmp_path: Path) -> Path:
    lib = tmp_path / "clips"
    (lib / "Day1" / "ReelA").mkdir(parents=True)
    (lib / "Day1" / "ReelB").mkdir(parents=True)
    (lib / "Day10").mkdir(parents=True)
    (lib / "Day1" / "ReelA" / "a.mov").write_bytes(b"x")
    (lib / "Day1" / "ReelB" / "b.mov").write_bytes(b"x")
    (lib / "Day10" / "c.mov").write_bytes(b"x")
    LibraryScanWorker([str(lib)]).run()
    return lib


def test_strict_picks_up_new_file_like_normal_scan(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = _make_days(tmp_path)
    (lib / "Day1" / "ReelA" / "new.mov").write_bytes(b"x")
    (lib / "Day2").mkdir()
    (lib / "Day2" / "d.mov").write_bytes(b"x")

    w = LibraryScanWorker([str(lib)], strict=True)
    done: List[int] = []
    w.scan_done.connect(done.append)
    w.run()

    assert w.read_failures == 0
    assert done and done[0] >= 2
    assert _names(lib) == ["a", "b", "c", "d", "new"]


def test_strict_keeps_old_index_when_folder_unreadable(
    tmp_app_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    lib = _make_days(tmp_path)
    dirs_before = _dirs(lib)
    (lib / "Day1" / "ReelA" / "new.mov").write_bytes(b"x")
    _fail_reading(monkeypatch, [lib / "Day1"])

    w = LibraryScanWorker([str(lib)], strict=True)
    w.run()

    assert w.read_failures == 1
    # 못 읽은 Day1 과 그 하위는 "비었다"로 적히지도, 지워지지도 않는다
    assert _dirs(lib) == dirs_before
    assert _names(lib) == ["a", "b", "c"]  # new.mov 는 다음 새로고침 때


def test_strict_failure_prefix_does_not_protect_sibling(
    tmp_app_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    """「Day1」 실패가 이름이 비슷한 「Day10」 을 지켜주면 안 된다 (삭제는 정상 반영)."""
    lib = _make_days(tmp_path)
    (lib / "Day10" / "c.mov").unlink()
    (lib / "Day10").rmdir()
    _fail_reading(monkeypatch, [lib / "Day1"])

    w = LibraryScanWorker([str(lib)], strict=True)
    w.run()

    assert w.read_failures == 1
    assert "Day10" not in _dirs(lib)
    assert _names(lib) == ["a", "b"]


def test_strict_unreadable_root_keeps_everything(
    tmp_app_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    lib = _make_days(tmp_path)
    dirs_before = _dirs(lib)
    _fail_reading(monkeypatch, [lib])

    w = LibraryScanWorker([str(lib)], strict=True)
    w.run()

    assert w.read_failures == 1
    assert _dirs(lib) == dirs_before
    assert _names(lib) == ["a", "b", "c"]


def test_strict_zero_mtime_counts_as_failure(
    tmp_app_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    import bpe.gui.workers.library_scan_worker as lsw

    lib = _make_days(tmp_path)
    real = lsw.dir_mtime
    target = _norm(lib / "Day10")
    monkeypatch.setattr(lsw, "dir_mtime", lambda p: 0.0 if _norm(p) == target else real(p))
    (lib / "Day10" / "c.mov").unlink()

    w = LibraryScanWorker([str(lib)], strict=True)
    w.run()

    assert w.read_failures == 1
    assert _names(lib) == ["a", "b", "c"]  # 확인 못 한 폴더는 예전 목록 유지


def test_default_mode_ignores_strict_path(tmp_app_dir: Path, tmp_path: Path, monkeypatch) -> None:
    """strict=False(전체 스캔 등)는 새 함수를 전혀 안 쓰고 기존 동작 그대로."""
    lib = _make_days(tmp_path)
    called = _fail_reading(monkeypatch, [lib / "Day1"])
    (lib / "Day1" / "ReelA" / "new.mov").write_bytes(b"x")

    w = LibraryScanWorker([str(lib)])
    w.run()

    assert called == []
    assert w.read_failures == 0
    assert _names(lib) == ["a", "b", "c", "new"]


def test_strict_is_ignored_for_pack_roots(tmp_app_dir: Path, tmp_path: Path, monkeypatch) -> None:
    lib = _make_days(tmp_path)
    called = _fail_reading(monkeypatch, [lib / "Day1"])

    w = LibraryScanWorker([str(lib)], pack_roots=[str(lib)], strict=True)
    w.run()

    assert called == []
    assert w.read_failures == 0


# ── preview (설정 「새로고침」: 쓰지 않고 모으기만) ────────────────────


def _mtimes(lib: Path) -> dict:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT dir_rel, mtime FROM dirs WHERE root=?", (_norm(lib),)
        ).fetchall()
        return {str(r[0]): float(r[1]) for r in rows}
    finally:
        conn.close()


def test_preview_records_changes_without_writing(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = _make_days(tmp_path)
    before_names, before_dirs, before_mtimes = _names(lib), _dirs(lib), _mtimes(lib)
    (lib / "Day1" / "ReelA" / "new.mov").write_bytes(b"x")
    (lib / "Day2").mkdir()
    (lib / "Day2" / "d.mov").write_bytes(b"x")
    (lib / "Day10" / "c.mov").unlink()
    (lib / "Day10").rmdir()

    w = LibraryScanWorker([str(lib)], strict=True, preview=True)
    done: List[int] = []
    w.scan_done.connect(done.append)
    w.run()

    assert w.read_failures == 0
    assert (_names(lib), _dirs(lib), _mtimes(lib)) == (before_names, before_dirs, before_mtimes)
    res = w.preview_result
    assert res is not None
    assert sorted((c.dir_rel, c.added) for c in res.changes) == [("Day1/ReelA", 1), ("Day2", 1)]
    assert [(g.dir_rel, g.removed) for g in res.gone] == [("Day10", 1)]
    groups = res.groups()
    assert [(g.category, g.kind) for g in groups] == [
        ("Day2", "new"),
        ("Day1", "existing"),
        ("Day10", "existing"),
    ]


def test_preview_ignores_mtime_only_change(tmp_app_dir: Path, tmp_path: Path) -> None:
    import os

    lib = _make_days(tmp_path)
    os.utime(lib / "Day10", (1.0, 1.0))
    w = LibraryScanWorker([str(lib)], strict=True, preview=True)
    w.run()
    assert w.preview_result is not None
    assert w.preview_result.is_empty()
    assert _mtimes(lib)["Day10"] != 1.0  # preview 는 기록 시각도 안 건드린다


def test_preview_read_failure_and_hidden_are_not_gone(
    tmp_app_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    lib = _make_days(tmp_path)
    _fail_reading(monkeypatch, [lib / "Day1"])
    w = LibraryScanWorker(
        [str(lib)], hidden_folders=[str(lib / "Day10")], strict=True, preview=True
    )
    w.run()
    assert w.read_failures == 1
    assert w.preview_result is not None
    assert w.preview_result.gone == []
    assert _names(lib) == ["a", "b", "c"]


def test_preview_skips_pack_roots_entirely(tmp_app_dir: Path, tmp_path: Path, monkeypatch) -> None:
    lib = _make_days(tmp_path)
    called = _fail_reading(monkeypatch, [])
    w = LibraryScanWorker([str(lib)], pack_roots=[str(lib)], strict=True, preview=True)
    w.run()
    assert called == []
    assert w.preview_result is not None and w.preview_result.is_empty()


def test_preview_then_apply_subset_then_preview_again(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = _make_days(tmp_path)
    (lib / "Day2").mkdir()
    (lib / "Day2" / "d.mov").write_bytes(b"x")
    (lib / "Day3").mkdir()
    (lib / "Day3" / "e.mov").write_bytes(b"x")
    w = LibraryScanWorker([str(lib)], strict=True, preview=True)
    w.run()
    conn = db.connect()
    try:
        assert w.preview_result is not None
        w.preview_result.apply(conn, {(_norm(lib), "Day2")})
    finally:
        conn.close()
    assert _names(lib) == ["a", "b", "c", "d"]
    w2 = LibraryScanWorker([str(lib)], strict=True, preview=True)
    w2.run()
    assert w2.preview_result is not None
    assert [(g.category, g.kind) for g in w2.preview_result.groups()] == [("Day3", "new")]


def test_stop_prevents_pruning_and_further_work(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    (lib / "Fire").mkdir(parents=True)
    (lib / "Fire" / "a.mov").write_bytes(b"x")

    w = LibraryScanWorker([str(lib)])
    w.stop()
    done: List[int] = []
    aborted: List[int] = []
    w.scan_done.connect(done.append)
    w.scan_aborted.connect(aborted.append)
    w.run()
    assert done == []
    assert aborted == [0]

    conn = db.connect()
    try:
        assert db.count_items(conn, roots=[str(lib)]) == 0
    finally:
        conn.close()


def test_deleted_folder_is_pruned_on_next_scan(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    (lib / "Keep").mkdir(parents=True)
    (lib / "Gone").mkdir(parents=True)
    (lib / "Keep" / "a.mov").write_bytes(b"x")
    (lib / "Gone" / "b.mov").write_bytes(b"x")

    LibraryScanWorker([str(lib)]).run()
    (lib / "Gone" / "b.mov").unlink()
    (lib / "Gone").rmdir()
    LibraryScanWorker([str(lib)]).run()

    conn = db.connect()
    try:
        remaining: List[Tuple[str, int]] = db.list_categories(conn, roots=[str(lib)])
        assert remaining == [("Keep", 1)]
    finally:
        conn.close()


def test_worker_indexes_pack_layout_as_one_card_on_pack_roots(
    tmp_app_dir: Path, tmp_path: Path
) -> None:
    """pack_roots 에 포함된 루트만 JPG+thumb.mov+image/ 를 한 카드로 묶는다."""
    lib = tmp_path / "lib"
    pack = lib / "Glass" / "actionvfx_Bottle_1_2749_4K"
    (pack / "image").mkdir(parents=True)
    base = "actionvfx_Bottle_1_2749_4K"
    (pack / "{}.jpg".format(base)).write_bytes(b"j")
    (pack / "{}.thumb.mov".format(base)).write_bytes(b"m")
    for n in (1001, 1002, 1003):
        (pack / "image" / "{}.{:04d}.exr".format(base, n)).write_bytes(b"e")

    root = str(lib).replace("\\", "/")
    w = LibraryScanWorker([root], pack_roots=[root])
    counts: List[int] = []
    w.scan_done.connect(counts.append)
    w.run()
    assert counts and counts[0] >= 1

    conn = db.connect()
    try:
        rows = db.fetch_items(conn, roots=[root])
        assert len(rows) == 1
        assert str(rows[0]["kind"]) == "sequence"
        assert str(rows[0].get("preview_file") or "").endswith(".thumb.mov")
        assert str(rows[0].get("representative") or "").endswith(".jpg")
        assert "image/" in str(rows[0].get("seq_pattern") or "").replace("\\", "/")
    finally:
        conn.close()


def test_worker_prunes_stale_image_dir_after_pack(tmp_app_dir: Path, tmp_path: Path) -> None:
    """옛 …/image per-file 행이 있으면 pack 스캔 후 prune 되어 카드 1장만 남는다."""
    lib = tmp_path / "lib"
    pack = lib / "Blood" / "actionvfx_Hole_7"
    (pack / "image").mkdir(parents=True)
    base = "actionvfx_Hole_7"
    (pack / "{}.jpg".format(base)).write_bytes(b"j")
    (pack / "{}.thumb.mov".format(base)).write_bytes(b"m")
    for n in (1001, 1002, 1003):
        (pack / "image" / "{}.{:04d}.exr".format(base, n)).write_bytes(b"e")

    root = str(lib).replace("\\", "/")
    # 예전 방식처럼 image/ 만 먼저 인덱싱
    LibraryScanWorker([root], pack_roots=[]).run()
    conn = db.connect()
    try:
        before = db.fetch_items(conn, roots=[root])
        assert any("/image" in str(r.get("dir_rel") or "").replace("\\", "/") for r in before)
    finally:
        conn.close()

    LibraryScanWorker([root], pack_roots=[root], force=True).run()
    conn = db.connect()
    try:
        rows = db.fetch_items(conn, roots=[root])
        assert len(rows) == 1
        assert str(rows[0].get("preview_file") or "").endswith(".thumb.mov")
        assert "image/" in str(rows[0].get("seq_pattern") or "").replace("\\", "/")
        assert not any(
            str(r.get("dir_rel") or "").replace("\\", "/").endswith("/image") for r in rows
        )
    finally:
        conn.close()


def test_worker_without_pack_roots_keeps_separate_cards(tmp_app_dir: Path, tmp_path: Path) -> None:
    """MMK 등 pack_roots 미포함 루트는 파일 단위(3카드)로 인덱싱."""
    lib = tmp_path / "lib"
    pack = lib / "Glass" / "actionvfx_Bottle_1_2749_4K"
    (pack / "image").mkdir(parents=True)
    base = "actionvfx_Bottle_1_2749_4K"
    (pack / "{}.jpg".format(base)).write_bytes(b"j")
    (pack / "{}.thumb.mov".format(base)).write_bytes(b"m")
    for n in (1001, 1002, 1003):
        (pack / "image" / "{}.{:04d}.exr".format(base, n)).write_bytes(b"e")

    root = str(lib).replace("\\", "/")
    w = LibraryScanWorker([root], pack_roots=[])
    w.run()
    conn = db.connect()
    try:
        rows = db.fetch_items(conn, roots=[root])
        assert len(rows) == 3
        assert not any(str(r.get("preview_file") or "") for r in rows)
    finally:
        conn.close()


def test_force_reindexes_unchanged_folders(tmp_app_dir: Path, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    (lib / "Fire").mkdir(parents=True)
    (lib / "Fire" / "a.mov").write_bytes(b"x")

    results: List[int] = []
    LibraryScanWorker([str(lib)]).run()
    w = LibraryScanWorker([str(lib)], force=True)
    w.scan_done.connect(results.append)
    w.run()
    assert results == [1]


def test_cache_trim_runs_before_scan(tmp_app_dir: Path, tmp_path: Path) -> None:
    from bpe.core import media_thumbs

    cache = media_thumbs.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (cache / "old{}.jpg".format(i)).write_bytes(b"x" * 1000)

    lib = tmp_path / "lib"
    lib.mkdir()
    LibraryScanWorker([str(lib)], trim_cache_bytes=1500).run()

    assert media_thumbs.cache_size_bytes() <= 1500
