"""새로고침 미리보기 — 변경 집계·선택 적용·분류 안 됨 판정·자동 분류 (순수 로직)."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core import source_library_refresh as refresh
from bpe.core.source_library_scan import FileEntry, group_entries

_R = "W:/proj/clips"
_E = "W:/library/element"


def _items(names: List[str], size: int = 1):
    return group_entries([FileEntry(n, size, 1.0) for n in names])


@pytest.fixture()
def conn(tmp_path: Path):
    c = db.connect(tmp_path / "idx.sqlite")
    yield c
    c.close()


def _seed(conn, dir_rel: str, names: List[str]) -> None:
    db.replace_dir_items(conn, _R, dir_rel, _items(names), 1.0)
    conn.commit()


# ── db 헬퍼 ────────────────────────────────────────────────────────


def test_db_helpers_and_column_order(conn) -> None:
    assert db._SNAPSHOT_COLUMNS == "dir_rel, " + db.ITEM_CONTENT_COLUMNS
    _seed(conn, "Day1", ["a.mov", "b.mov"])
    _seed(conn, "Day1/Reel", ["c.mov"])
    rows = db.dir_item_contents(conn, _R, "Day1")
    assert [r[0] for r in rows] == ["a", "b"]
    assert rows[0] == refresh.item_content(_items(["a.mov"])[0])
    assert db.item_counts_by_dir(conn, _R) == {"Day1": 2, "Day1/Reel": 1}
    db.delete_dir(conn, _R, "Day1")
    conn.commit()
    assert db.item_counts_by_dir(conn, _R) == {"Day1/Reel": 1}
    assert db.known_dirs(conn, _R) == ["Day1/Reel"]


# ── record_dir 집계 ─────────────────────────────────────────────────


def test_record_dir_counts(conn) -> None:
    _seed(conn, "Day1", ["a.mov", "b.mov", "s.1001.exr", "s.1002.exr"])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    # 같은 내용 → 기록 없음
    assert (
        p.record_dir(conn, _R, "Day1", _items(["a.mov", "b.mov", "s.1001.exr", "s.1002.exr"]), 9.0)
        == 0
    )
    assert p.changes == []
    # 추가 1, 삭제 1(b), 시퀀스 프레임 증가 = 변경 1
    n = p.record_dir(
        conn, _R, "Day1", _items(["a.mov", "c.mov", "s.1001.exr", "s.1002.exr", "s.1003.exr"]), 9.0
    )
    assert n == 3
    ch = p.changes[0]
    assert (ch.added, ch.removed, ch.changed) == (1, 1, 1)
    assert ch.mtime == 9.0


def test_record_dir_size_change_is_changed(conn) -> None:
    _seed(conn, "Day1", ["a.mov"])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    p.record_dir(conn, _R, "Day1", _items(["a.mov"], size=99), 1.0)
    assert (p.changes[0].added, p.changes[0].removed, p.changes[0].changed) == (0, 0, 1)


def test_finish_root_skips_empty_gone_dirs(conn) -> None:
    _seed(conn, "Day1", ["a.mov"])
    _seed(conn, "Empty", [])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    p.finish_root(_R, ["Day1", "Empty", "Never"])
    assert p.gone == [refresh.GoneDir(_R, "Day1", 1)]


# ── groups / apply ──────────────────────────────────────────────────


def test_groups_kinds_and_order(conn) -> None:
    _seed(conn, "Day1", ["a.mov"])
    _seed(conn, "", ["root.mov"])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    p.record_dir(conn, _R, "Day1/ReelA", _items(["x.mov"]), 1.0)
    p.record_dir(conn, _R, "zzz", _items(["z.mov"]), 1.0)
    p.record_dir(conn, _R, "Aaa", _items(["q.mov", "w.mov"]), 1.0)
    p.record_dir(conn, _R, "", _items(["root.mov", "root2.mov"]), 1.0)
    p.finish_root(_R, ["Day1"])
    p.add_unorganized(_R, "Old", 7)
    g = p.groups()
    assert [(x.category, x.kind) for x in g] == [
        ("Aaa", "new"),
        ("zzz", "new"),
        ("", "existing"),
        ("Day1", "existing"),
        ("Old", "unorganized"),
    ]
    day1 = [x for x in g if x.category == "Day1"][0]
    assert (day1.added, day1.removed) == (1, 1)
    assert [x for x in g if x.category == "Aaa"][0].clips == 2
    assert p.is_empty() is False


def test_apply_writes_only_selected_and_deletes_gone(conn) -> None:
    _seed(conn, "Day1", ["a.mov"])
    _seed(conn, "Day2", ["b.mov"])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    p.record_dir(conn, _R, "Day1", _items(["a.mov", "a2.mov"]), 7.0)
    p.record_dir(conn, _R, "Day3", _items(["c.mov"]), 7.0)
    p.finish_root(_R, ["Day2"])
    written = p.apply(conn, {(_R, "Day1"), (_R, "Day2")})
    assert written == 2
    names = sorted(r["name"] for r in db.fetch_items(conn, roots=[_R]))
    assert names == ["a", "a2"]  # Day2 삭제됨, Day3 는 안 고름
    assert db.dir_needs_index(conn, _R, "Day1", 7.0) is False
    assert "Day3" not in db.known_dirs(conn, _R)


def test_apply_rolls_back_on_error(conn, monkeypatch) -> None:
    _seed(conn, "Day1", ["a.mov"])
    p = refresh.RefreshPreview()
    p.begin_root(conn, _R)
    p.record_dir(conn, _R, "Day1", _items(["a.mov", "b.mov"]), 7.0)
    p.record_dir(conn, _R, "Day2", _items(["c.mov"]), 7.0)
    calls = {"n": 0}
    real = db.replace_dir_items

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk")
        return real(*a, **k)

    monkeypatch.setattr(db, "replace_dir_items", flaky)
    with pytest.raises(RuntimeError):
        p.apply(conn, {(_R, "Day1"), (_R, "Day2")})
    assert sorted(r["name"] for r in db.fetch_items(conn, roots=[_R])) == ["a"]


# ── 분류 안 됨 / 자동 분류 ──────────────────────────────────────────


def _lib():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        [_E, _R],
        [{"name": libcfg.COMMON_LABEL, "folders": [_E]}],
    )
    libcfg.add_top_level_folder(lib, "MMK_Plate")
    assert libcfg.organize_into_folder(lib, "MMK_Plate", _R + "/Day1")
    assert libcfg.organize_into_folder(lib, "MMK_Plate", _R + "/Day2")
    return lib


def test_unorganized_categories() -> None:
    lib = _lib()
    libcfg.set_folder_hidden(lib, _R + "/Hidden", True)
    counts = [
        (_R, "Day1", 5),  # 정리됨
        (_R, "Day3", 4),  # 분류 안 됨
        (_R, "", 1),  # 루트 직속 → 제외
        (_R, "Zero", 0),  # 항목 없음
        (_R, "Hidden", 3),  # 숨김
        (_E, "Fire", 9),  # CS 소유 루트 → 평탄 표시되므로 제외
    ]
    assert refresh.unorganized_categories(lib, counts) == [(_R, "Day3", 4)]


def test_auto_organize_targets_follow_siblings() -> None:
    lib = _lib()
    out = refresh.auto_organize_targets(lib, [(_R, "Day3"), (_R, "Day1"), (_E, "Fire")])
    # Day1 은 이미 정리됨 → 제외. Fire 는 element 에 옆 폴더가 없음 → "".
    assert out == [(_R + "/Day3", "MMK_Plate"), (_E + "/Fire", "")]


def test_auto_organize_targets_picks_most_common_parent() -> None:
    lib = _lib()
    libcfg.add_folder_under(lib, "MMK_Plate", "B유닛")
    assert libcfg.organize_into_folder(lib, "MMK_Plate/B유닛", _R + "/KMM_B_010")
    assert libcfg.organize_into_folder(lib, "MMK_Plate/B유닛", _R + "/KMM_B_011")
    assert libcfg.organize_into_folder(lib, "MMK_Plate/B유닛", _R + "/KMM_B_012")
    out = refresh.auto_organize_targets(lib, [(_R, "New")])
    assert out == [(_R + "/New", "MMK_Plate/B유닛")]


def test_apply_auto_organize_and_reserved_name() -> None:
    lib = _lib()
    done, failed = refresh.apply_auto_organize(
        lib, [(_R + "/Day3", "MMK_Plate"), (_R + "/기타", "MMK_Plate"), (_R + "/NoHome", "")]
    )
    assert done == [_R + "/Day3"]
    assert failed == [_R + "/기타", _R + "/NoHome"]
    org = libcfg.library_organized_paths(lib)
    assert _R + "/Day3" in org and _R + "/Day1" in org
    # 이미 정리된 폴더는 자리를 옮기지 않는다
    assert refresh.auto_organize_targets(lib, [(_R, "Day3")]) == []
