"""Tests for bpe.core.shotgun_python_api_path."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from bpe.core import shotgun_python_api_path as sut


def _minimal_shotgun_api3_tree(parent: object) -> None:
    """Create parent/shotgun_api3/__init__.py (minimal importable package)."""
    p = parent / "shotgun_api3"
    p.mkdir(parents=True)
    p.joinpath("__init__.py").write_text("# test stub\n", encoding="utf-8")


def _cleanup_path_and_modules(path_str: str) -> None:
    while path_str in sys.path:
        sys.path.remove(path_str)
    for k in list(sys.modules):
        if k == "shotgun_api3" or k.startswith("shotgun_api3."):
            sys.modules.pop(k, None)


def test_prepend_inserts_when_dir_exists_and_import_ok(tmp_path, monkeypatch) -> None:
    root = tmp_path / "shotgun-python-api"
    root.mkdir()
    _minimal_shotgun_api3_tree(root)
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", root)
    _cleanup_path_and_modules(str(root))
    try:
        sut.prepend_studio_shotgun_api_if_available()
        assert sys.path[0] == str(root)
        assert "shotgun_api3" in sys.modules
        sut.prepend_studio_shotgun_api_if_available()
        assert sys.path.count(str(root)) == 1
    finally:
        _cleanup_path_and_modules(str(root))


def test_frozen_still_prepends_when_import_ok(tmp_path, monkeypatch) -> None:
    root = tmp_path / "shotgun-python-api"
    root.mkdir()
    _minimal_shotgun_api3_tree(root)
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", root)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _cleanup_path_and_modules(str(root))
    try:
        sut.prepend_studio_shotgun_api_if_available()
        assert sys.path[0] == str(root)
    finally:
        _cleanup_path_and_modules(str(root))


def test_rolls_back_when_shotgun_api3_import_fails(tmp_path, monkeypatch) -> None:
    root = tmp_path / "shotgun-python-api"
    root.mkdir()
    sg = root / "shotgun_api3"
    sg.mkdir()
    sg.joinpath("__init__.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", root)
    _cleanup_path_and_modules(str(root))
    before = list(sys.path)
    sut.prepend_studio_shotgun_api_if_available()
    assert str(root) not in sys.path
    assert sys.path == before


def test_skips_when_no_shotgun_api3_subfolder(tmp_path, monkeypatch) -> None:
    root = tmp_path / "shotgun-python-api"
    root.mkdir()
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", root)
    before = list(sys.path)
    sut.prepend_studio_shotgun_api_if_available()
    assert str(root) not in sys.path
    assert sys.path == before


def test_prepend_skips_when_not_a_dir(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "nope"
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", missing)
    before_len = len(sys.path)
    sut.prepend_studio_shotgun_api_if_available()
    assert len(sys.path) == before_len


def test_prepend_skips_when_is_dir_raises_oserror(monkeypatch) -> None:
    fake_parent = MagicMock()
    fake_parent.is_dir.side_effect = OSError("network")
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", fake_parent)
    before = list(sys.path)
    sut.prepend_studio_shotgun_api_if_available()
    assert sys.path == before


def test_opt_out_env_skips(monkeypatch, tmp_path) -> None:
    root = tmp_path / "shotgun-python-api"
    root.mkdir()
    _minimal_shotgun_api3_tree(root)
    monkeypatch.setattr(sut, "_STUDIO_SHOTGUN_API_PARENT", root)
    monkeypatch.setenv("BPE_SHOTGUN_NO_STUDIO_PATH", "1")
    _cleanup_path_and_modules(str(root))
    before = list(sys.path)
    sut.prepend_studio_shotgun_api_if_available()
    assert sys.path == before
    assert str(root) not in sys.path
