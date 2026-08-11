"""소스 라이브러리 스캔 — 시퀀스 묶기/패딩/카테고리 순수 로직 테스트."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from bpe.core.source_library_scan import (
    KIND_MOVIE,
    KIND_SEQUENCE,
    KIND_STILL,
    FileEntry,
    category_of,
    expand_frame_pattern,
    filmstrip_frames,
    frame_pattern,
    group_entries,
    item_frame_path,
    read_dir,
    relative_dir,
    scan_dir_items,
    split_name_ext,
    split_trailing_number,
)


def _entries(names: List[str]) -> List[FileEntry]:
    return [FileEntry(n, 1000, 100.0) for n in names]


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("plate.1001", ("plate.", "1001")),
        ("smoke_0042", ("smoke_", "0042")),
        ("shot_v002_0001", ("shot_v002_", "0001")),
        ("0001", ("", "0001")),
        ("no_digits", None),
        ("trailing_v2a", None),
    ],
)
def test_split_trailing_number(stem, expected):
    assert split_trailing_number(stem) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("plate.1001.EXR", ("plate.1001", ".exr")),
        ("clip.MOV", ("clip", ".mov")),
        ("noext", ("noext", "")),
    ],
)
def test_split_name_ext(name, expected):
    assert split_name_ext(name) == expected


def test_frame_pattern_uniform_padding():
    assert frame_pattern("plate.", ".exr", [4, 4, 4]) == "plate.%04d.exr"


def test_frame_pattern_mixed_padding_falls_back_to_plain():
    assert frame_pattern("plate.", ".exr", [3, 4]) == "plate.%d.exr"


def test_expand_frame_pattern():
    assert expand_frame_pattern("plate.%04d.exr", 1001) == "plate.1001.exr"
    assert expand_frame_pattern("clip.mov", 5) == "clip.mov"


def test_group_entries_builds_one_sequence():
    items = group_entries(_entries(["p.1001.exr", "p.1002.exr", "p.1003.exr"]))
    assert len(items) == 1
    it = items[0]
    assert it.kind == KIND_SEQUENCE
    assert it.name == "p"
    assert it.seq_pattern == "p.%04d.exr"
    assert (it.frame_first, it.frame_last, it.frame_count) == (1001, 1003, 3)
    # 대표 프레임은 중간 프레임 (앞뒤는 페이드가 흔하다)
    assert it.representative == "p.1002.exr"
    assert it.size_bytes == 3000


def test_group_entries_single_frame_is_still_not_sequence():
    items = group_entries(_entries(["p.1001.exr"]))
    assert len(items) == 1
    assert items[0].kind == KIND_STILL


def test_group_entries_separates_different_prefix_and_ext():
    items = group_entries(
        _entries(
            [
                "fire.1001.exr",
                "fire.1002.exr",
                "smoke.1001.dpx",
                "smoke.1002.dpx",
                "ref.mov",
            ]
        )
    )
    kinds = {it.name: it.kind for it in items}
    assert kinds == {"fire": KIND_SEQUENCE, "smoke": KIND_SEQUENCE, "ref": KIND_MOVIE}


def test_group_entries_ignores_unknown_extensions():
    items = group_entries(_entries(["readme.txt", "notes.pdf", "a.nk"]))
    assert items == []


def test_group_entries_movie_is_never_grouped_as_sequence():
    items = group_entries(_entries(["take.0001.mov", "take.0002.mov"]))
    assert len(items) == 2
    assert all(it.kind == KIND_MOVIE for it in items)


def test_group_entries_numbered_jpgs_are_individual_stills():
    """셋 사진·레퍼런스 JPG는 시퀀스로 안 묶고 장마다 카드."""
    names = ["DSC.{:05d}.jpg".format(n) for n in range(5641, 5646)]
    items = group_entries(_entries(names))
    assert len(items) == 5
    assert all(it.kind == KIND_STILL for it in items)
    assert {it.seq_pattern for it in items} == set(names)


def test_group_entries_numbered_png_tif_are_individual_stills():
    items = group_entries(
        _entries(["ref.0001.png", "ref.0002.png", "plate.10.tif", "plate.11.tif"])
    )
    assert len(items) == 4
    assert all(it.kind == KIND_STILL for it in items)


def test_group_entries_handles_gaps_in_frame_numbers():
    items = group_entries(_entries(["p.1001.exr", "p.1005.exr", "p.1009.exr"]))
    it = items[0]
    assert (it.frame_first, it.frame_last, it.frame_count) == (1001, 1009, 3)


@pytest.mark.parametrize(
    "dir_rel,expected",
    [("", ""), ("Fire", "Fire"), ("Fire/sub/deep", "Fire")],
)
def test_category_of(dir_rel, expected):
    assert category_of(dir_rel) == expected


def test_relative_dir():
    assert relative_dir("W:/lib", "W:/lib") == ""
    assert relative_dir("W:/lib", "W:/lib/Fire") == "Fire"
    assert relative_dir("W:/lib/", "W:/lib/Fire/sub") == "Fire/sub"


def test_filmstrip_frames_even_spread():
    assert filmstrip_frames(1001, 1005, 5) == [1001, 1002, 1003, 1004, 1005]
    assert filmstrip_frames(1, 100, 5) == [1, 26, 51, 75, 100]
    # 프레임이 요청 수보다 적으면 있는 것만
    assert filmstrip_frames(1, 3, 5) == [1, 2, 3]
    assert filmstrip_frames(1, 10, 0) == []


def test_item_frame_path_for_sequence_and_movie():
    items = {it.kind: it for it in group_entries(_entries(["p.1001.exr", "p.1002.exr", "c.mov"]))}
    assert item_frame_path("W:/lib", items[KIND_SEQUENCE], 1002) == "W:/lib/p.1002.exr"
    assert item_frame_path("W:/lib", items[KIND_MOVIE], 5) == "W:/lib/c.mov"


def test_read_dir_and_scan_dir_items(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / ".hidden").mkdir()
    for n in ("a.1001.exr", "a.1002.exr", "b.mov", "skip.txt"):
        (tmp_path / n).write_bytes(b"x" * 10)

    subdirs, files = read_dir(str(tmp_path))
    assert subdirs == ["sub"]
    assert sorted(f.name for f in files) == ["a.1001.exr", "a.1002.exr", "b.mov"]

    items = scan_dir_items(str(tmp_path))
    assert {it.name: it.kind for it in items} == {"a": KIND_SEQUENCE, "b": KIND_MOVIE}


def test_read_dir_missing_path_returns_empty():
    assert read_dir("Z:/definitely/not/here") == ([], [])


def test_try_build_pack_actionvfx_layout(tmp_path: Path):
    from bpe.core.source_library_scan import row_pattern_path, row_preview_path, try_build_pack

    pack = tmp_path / "Glass" / "actionvfx_Champagne_Glass_5_2769_4K"
    (pack / "image").mkdir(parents=True)
    base = "actionvfx_Champagne_Glass_5_2769_4K"
    (pack / "{}.jpg".format(base)).write_bytes(b"jpg")
    (pack / "{}.thumb.mov".format(base)).write_bytes(b"mov")
    for n in (1099, 1100, 1101):
        (pack / "image" / "{}.{:05d}.exr".format(base, n)).write_bytes(b"exr")

    subdirs, files = read_dir(str(pack))
    result = try_build_pack(str(pack), subdirs, files)
    assert result is not None
    item, consumed = result
    assert consumed == ["image"]
    assert item.kind == KIND_SEQUENCE
    assert item.representative == "{}.jpg".format(base)
    assert item.preview_file == "{}.thumb.mov".format(base)
    assert item.seq_pattern.startswith("image/")
    assert "%0" in item.seq_pattern or "%d" in item.seq_pattern
    assert item.frame_first == 1099
    assert item.frame_last == 1101

    row = {
        "root": str(tmp_path / "Glass").replace("\\", "/"),
        "dir_rel": "actionvfx_Champagne_Glass_5_2769_4K",
        "seq_pattern": item.seq_pattern,
        "preview_file": item.preview_file,
        "representative": item.representative,
    }
    assert "/image/" in row_pattern_path(row).replace("\\", "/")
    assert row_preview_path(row).endswith(".thumb.mov")


def test_try_build_pack_returns_none_without_image(tmp_path: Path):
    from bpe.core.source_library_scan import try_build_pack

    pack = tmp_path / "only_preview"
    pack.mkdir()
    (pack / "clip.jpg").write_bytes(b"j")
    (pack / "clip.thumb.mov").write_bytes(b"m")
    subdirs, files = read_dir(str(pack))
    assert try_build_pack(str(pack), subdirs, files) is None


def test_try_build_pack_returns_none_for_plain_movie(tmp_path: Path):
    from bpe.core.source_library_scan import try_build_pack

    pack = tmp_path / "plain"
    pack.mkdir()
    (pack / "alone.mov").write_bytes(b"m")
    subdirs, files = read_dir(str(pack))
    assert try_build_pack(str(pack), subdirs, files) is None
    # 기존 per-file 동작
    items = group_entries(files)
    assert len(items) == 1
    assert items[0].kind == KIND_MOVIE
