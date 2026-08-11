"""라이브러리 → Nuke 핸드오프 JSON."""

from __future__ import annotations

from pathlib import Path

from bpe.core import library_handoff as hh
from bpe.core.source_library_scan import KIND_SEQUENCE


def test_write_and_read_handoff(tmp_app_dir: Path):
    rows = [
        {
            "root": "W:/lib",
            "dir_rel": "한글소스",
            "name": "plate",
            "kind": KIND_SEQUENCE,
            "seq_pattern": "plate.%04d.exr",
            "frame_first": 1001,
            "frame_last": 1050,
        }
    ]
    path = hh.write_handoff(rows)
    assert path.is_file()
    items = hh.read_handoff()
    assert len(items) == 1
    assert "한글소스" in items[0]["path"]
    assert items[0]["first"] == 1001
    assert items[0]["last"] == 1050
    payload = hh.read_handoff_payload()
    assert payload.get("send_id")
    assert payload.get("consumed") is False


def test_write_handoff_only_touches_cache_json(tmp_app_dir: Path, tmp_path: Path):
    media = tmp_path / "한글소스"
    media.mkdir()
    marker = media / "plate.1001.exr"
    marker.write_bytes(b"exr")
    before = marker.stat().st_mtime_ns

    rows = [
        {
            "root": str(tmp_path).replace("\\", "/"),
            "dir_rel": "한글소스",
            "name": "plate",
            "kind": KIND_SEQUENCE,
            "seq_pattern": "plate.%04d.exr",
            "frame_first": 1001,
            "frame_last": 1050,
        }
    ]
    out = hh.write_handoff(rows)
    assert out.is_file()
    assert "cache" in str(out).replace("\\", "/")
    assert marker.read_bytes() == b"exr"
    assert marker.stat().st_mtime_ns == before
    items = hh.read_handoff()
    assert items[0]["path"].replace("\\", "/").endswith("한글소스/plate.%04d.exr")


def test_write_handoff_pack_uses_image_pattern(tmp_app_dir: Path):
    rows = [
        {
            "root": "W:/library/element",
            "dir_rel": "Blood/actionvfx_Hole_7",
            "name": "actionvfx_Hole_7",
            "kind": KIND_SEQUENCE,
            "seq_pattern": "image/actionvfx_Hole_7.%04d.exr",
            "frame_first": 1001,
            "frame_last": 1100,
            "representative": "actionvfx_Hole_7.jpg",
            "preview_file": "actionvfx_Hole_7.thumb.mov",
        }
    ]
    hh.write_handoff(rows)
    items = hh.read_handoff()
    assert len(items) == 1
    assert (
        items[0]["path"]
        .replace("\\", "/")
        .endswith("Blood/actionvfx_Hole_7/image/actionvfx_Hole_7.%04d.exr")
    )
    assert ".jpg" not in items[0]["path"]


def test_multi_rows_and_consume(tmp_app_dir: Path):
    rows = [
        {
            "root": "W:/lib",
            "dir_rel": "a",
            "name": "one",
            "kind": "movie",
            "seq_pattern": "one.mov",
        },
        {
            "root": "W:/lib",
            "dir_rel": "b",
            "name": "two",
            "kind": "movie",
            "seq_pattern": "two.mov",
        },
    ]
    hh.write_handoff(rows)
    assert len(hh.read_handoff()) == 2
    sid = hh.handoff_send_id()
    assert sid
    hh.mark_handoff_consumed()
    assert hh.handoff_is_consumed() is True
    assert hh.handoff_send_id() == sid
