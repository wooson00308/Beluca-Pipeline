"""Nuke 플러그인 슬림 설치 / 스탬프 동기화."""

from __future__ import annotations

from pathlib import Path

from bpe.core import nuke_plugin_install as npi


def test_ensure_nuke_plugin_copies_slim_and_skips(tmp_path: Path):
    src = tmp_path / "src_bpe"
    (src / "nuke_plugin").mkdir(parents=True)
    (src / "core").mkdir()
    (src / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    (src / "nuke_plugin" / "__init__.py").write_text("# nuke\n", encoding="utf-8")
    (src / "nuke_plugin" / "menu_setup.py").write_text("x = 1\n", encoding="utf-8")
    (src / "core" / "__init__.py").write_text("# core\n", encoding="utf-8")
    (src / "core" / "settings.py").write_text("y = 2\n", encoding="utf-8")
    (src / "gui").mkdir()
    (src / "gui" / "x.py").write_text("should_not_copy = 1\n", encoding="utf-8")

    nuke_dir = tmp_path / ".nuke"
    r1 = npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir, force=True)
    assert r1["updated"] is True
    assert not r1["error"]
    dest = nuke_dir / "bpe"
    assert (dest / "nuke_plugin" / "menu_setup.py").is_file()
    assert (dest / "core" / "settings.py").is_file()
    assert not (dest / "gui").exists()
    assert (dest / npi.STAMP_NAME).is_file()
    assert (nuke_dir / "menu.py").is_file()
    assert npi.HOOK_MARKER in (nuke_dir / "menu.py").read_text(encoding="utf-8")

    r2 = npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir)
    assert r2["skipped"] is True
    assert r2["updated"] is False
    assert r2["stamp"] == r1["stamp"]


def test_ensure_updates_when_plugin_changes(tmp_path: Path):
    src = tmp_path / "src_bpe"
    (src / "nuke_plugin").mkdir(parents=True)
    (src / "core").mkdir()
    (src / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    plugin = src / "nuke_plugin" / "a.py"
    plugin.write_text("v = 1\n", encoding="utf-8")
    (src / "core" / "__init__.py").write_text("#\n", encoding="utf-8")

    nuke_dir = tmp_path / ".nuke"
    r1 = npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir, force=True)
    plugin.write_text("v = 2\n", encoding="utf-8")
    r2 = npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir)
    assert r2["updated"] is True
    assert r2["stamp"] != r1["stamp"]
