"""Source Library 탐색기 하이라이트 경로 / explorer argv."""

from __future__ import annotations

import subprocess
from pathlib import Path

from bpe.core import library_reveal as lr
from bpe.core.source_library_scan import KIND_SEQUENCE


def test_windows_explorer_select_args_split_for_spaces():
    path = r"W:/team/_Library/Compositing Source/pack/foo.jpg"
    args = lr.windows_explorer_select_args(path)
    assert args[0] == "explorer"
    assert args[1] == "/select,"
    assert "Compositing Source" in args[2]
    cmdline = subprocess.list2cmdline(args)
    assert cmdline.startswith("explorer /select,")
    assert '"/select,' not in cmdline


def test_row_reveal_path_pack_prefers_jpg(tmp_path: Path):
    pack = tmp_path / "pack"
    image = pack / "image"
    image.mkdir(parents=True)
    jpg = pack / "asset.jpg"
    jpg.write_bytes(b"jpg")
    frame = image / "asset.01001.exr"
    frame.write_bytes(b"exr")
    (pack / "asset.thumb.mov").write_bytes(b"mov")

    row = {
        "root": str(tmp_path).replace("\\", "/"),
        "dir_rel": "pack",
        "kind": KIND_SEQUENCE,
        "seq_pattern": "image/asset.%05d.exr",
        "representative": "asset.jpg",
        "preview_file": "asset.thumb.mov",
        "frame_first": 1001,
        "frame_last": 1001,
    }
    revealed = lr.row_reveal_path(row).replace("\\", "/")
    assert revealed.endswith("/pack/asset.jpg")


def test_row_reveal_path_sequence_first_frame(tmp_path: Path):
    seq_dir = tmp_path / "seq"
    seq_dir.mkdir()
    frame = seq_dir / "plate.1001.exr"
    frame.write_bytes(b"x")
    row = {
        "root": str(tmp_path).replace("\\", "/"),
        "dir_rel": "seq",
        "kind": KIND_SEQUENCE,
        "seq_pattern": "plate.%04d.exr",
        "representative": "plate.1001.exr",
        "preview_file": "",
        "frame_first": 1001,
        "frame_last": 1005,
    }
    revealed = lr.row_reveal_path(row).replace("\\", "/")
    assert revealed.endswith("/seq/plate.1001.exr")
