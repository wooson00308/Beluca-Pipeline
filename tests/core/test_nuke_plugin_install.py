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


# 실제 사용자 menu.py 와 동일 구조 (사용자 소유 줄 + 레거시 훅 + 현재 훅)
_REAL_MENU_PY = """import nuke_setup_pro

nuke_setup_pro.add_setup_pro_menu()

# --- SETUP_PRO_BPE_MENU_HOOK_V1 (BPE install; existing menu.py preserved) ---
try:
    import nuke_setup_pro
    nuke_setup_pro.add_setup_pro_menu()
except Exception:
    pass
# --- end SETUP_PRO_BPE_MENU_HOOK_V1 ---
import W_hotbox, W_hotboxManager

# BPE_HOOK_START
try:
    from bpe.nuke_plugin.menu_setup import add_setup_pro_menu
    add_setup_pro_menu()
    from bpe.nuke_plugin.tool_hooks import reload_tool_hooks
    reload_tool_hooks()
except Exception as _bpe_err:
    import nuke
    nuke.tprint("[BPE] menu.py hook load failed: " + str(_bpe_err))
# BPE_HOOK_END
"""


class TestStripMenuHooks:
    def test_removes_both_hook_blocks_keeps_user_lines(self):
        cleaned = npi.strip_menu_hooks(_REAL_MENU_PY)
        assert "import W_hotbox, W_hotboxManager" in cleaned
        assert cleaned.startswith("import nuke_setup_pro")
        assert "nuke_setup_pro.add_setup_pro_menu()" in cleaned
        assert "BPE_HOOK_START" not in cleaned
        assert "BPE_HOOK_END" not in cleaned
        assert "SETUP_PRO_BPE_MENU_HOOK_V1" not in cleaned
        assert "bpe.nuke_plugin" not in cleaned
        assert "reload_tool_hooks" not in cleaned

    def test_noop_without_hooks(self):
        plain = "import W_hotbox\n"
        assert npi.strip_menu_hooks(plain) == plain

    def test_idempotent(self):
        once = npi.strip_menu_hooks(_REAL_MENU_PY)
        assert npi.strip_menu_hooks(once) == once


class TestRemoveNukePlugin:
    def test_removes_dir_and_cleans_menu(self, tmp_path: Path):
        nuke_dir = tmp_path / ".nuke"
        (nuke_dir / "bpe" / "nuke_plugin").mkdir(parents=True)
        (nuke_dir / "bpe" / "__init__.py").write_text("# pkg\n", encoding="utf-8")
        (nuke_dir / "menu.py").write_text(_REAL_MENU_PY, encoding="utf-8")

        result = npi.remove_nuke_plugin(nuke_dir=nuke_dir)
        assert result["error"] is None
        assert result["removed_dir"] is True
        assert not (nuke_dir / "bpe").exists()
        assert result["menu_cleaned"] is True
        backup = nuke_dir / str(result["menu_backup"])
        assert backup.is_file()
        assert "BPE_HOOK_START" in backup.read_text(encoding="utf-8")
        cleaned = (nuke_dir / "menu.py").read_text(encoding="utf-8")
        assert "BPE_HOOK_START" not in cleaned
        assert "import W_hotbox" in cleaned

    def test_noop_when_nothing_installed(self, tmp_path: Path):
        nuke_dir = tmp_path / ".nuke"
        nuke_dir.mkdir()
        (nuke_dir / "menu.py").write_text("import W_hotbox\n", encoding="utf-8")
        result = npi.remove_nuke_plugin(nuke_dir=nuke_dir)
        assert result["error"] is None
        assert result["removed_dir"] is False
        assert result["menu_cleaned"] is False

    def test_reinstall_after_remove(self, tmp_path: Path):
        src = tmp_path / "src_bpe"
        (src / "nuke_plugin").mkdir(parents=True)
        (src / "core").mkdir()
        (src / "__init__.py").write_text("# pkg\n", encoding="utf-8")
        (src / "nuke_plugin" / "a.py").write_text("v = 1\n", encoding="utf-8")
        nuke_dir = tmp_path / ".nuke"
        npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir, force=True)
        npi.remove_nuke_plugin(nuke_dir=nuke_dir)
        assert not (nuke_dir / "bpe").exists()
        r = npi.ensure_nuke_plugin(src=src, nuke_dir=nuke_dir, force=True)
        assert r["updated"] is True
        assert (nuke_dir / "bpe" / "nuke_plugin" / "a.py").is_file()
