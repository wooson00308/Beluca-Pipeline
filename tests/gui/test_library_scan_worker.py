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
