"""Tests for bpe.core.atomic_io."""

from __future__ import annotations

import json
from pathlib import Path

from bpe.core.atomic_io import atomic_write_text, read_json_file, write_json_file


def test_atomic_write_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "test.txt"
    atomic_write_text(p, "hello")
    assert p.read_text() == "hello"


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    atomic_write_text(p, "first")
    atomic_write_text(p, "second")
    assert p.read_text() == "second"


def test_read_json_file_missing(tmp_path: Path) -> None:
    assert read_json_file(tmp_path / "nope.json", default={}) == {}


def test_read_json_file_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.json"
    p.write_text("")
    assert read_json_file(p, default={"a": 1}) == {"a": 1}


def test_read_json_file_valid(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"key": "val"}))
    assert read_json_file(p, default={}) == {"key": "val"}


def test_read_json_file_type_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "arr.json"
    p.write_text(json.dumps([1, 2, 3]))
    # default is dict, but file has list -> returns default
    assert read_json_file(p, default={}) == {}


def test_read_json_file_list_default(tmp_path: Path) -> None:
    p = tmp_path / "arr.json"
    p.write_text(json.dumps(["a", "b"]))
    assert read_json_file(p, default=[]) == ["a", "b"]


def test_write_json_file(tmp_path: Path) -> None:
    p = tmp_path / "out.json"
    write_json_file(p, {"hello": "world"})
    data = json.loads(p.read_text())
    assert data == {"hello": "world"}


def test_atomic_write_no_leftover_on_success(tmp_path: Path) -> None:
    p = tmp_path / "clean.txt"
    atomic_write_text(p, "ok")
    # No .tmp files should remain
    tmps = list(tmp_path.glob(".*clean*.tmp"))
    assert tmps == []
