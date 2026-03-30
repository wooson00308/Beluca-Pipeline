"""Tests for bpe.core.nuke_render_paths — UNC preservation."""

from __future__ import annotations

from bpe.core.nuke_render_paths import (
    comp_devl_dir_from_nk_path,
    write_file_paths_from_nk_root_name,
)


class TestCompDevlDirFromNkPath:
    def test_unc_preserves_double_slash(self):
        root = (
            "//zeus.lennon.co.kr/beluca/vfx/project_2026/SBS_030/04_sq/E106/"
            "E106_S029_0020/comp/devl/nuke/v005/E106_S029_0020_comp_v005.nk"
        )
        got = comp_devl_dir_from_nk_path(root)
        assert got is not None
        assert got.startswith("//zeus.lennon.co.kr/")
        assert got.endswith("/comp/devl")

    def test_unc_backslash_input(self):
        root = (
            r"\\zeus.lennon.co.kr\beluca\vfx\project_2026\SBS_030\04_sq\E106"
            r"\E106_S029_0020\comp\devl\nuke\v005\E106_S029_0020_comp_v005.nk"
        )
        got = comp_devl_dir_from_nk_path(root)
        assert got is not None
        assert got.startswith("//zeus.lennon.co.kr/")
        assert got.endswith("/comp/devl")

    def test_drive_letter_path(self):
        root = (
            "W:/vfx/project_2026/SBS_030/04_sq/E106/E106_S029_0020/"
            "comp/devl/nuke/v005/E106_S029_0020_comp_v005.nk"
        )
        got = comp_devl_dir_from_nk_path(root)
        assert got == ("W:/vfx/project_2026/SBS_030/04_sq/E106/E106_S029_0020/comp/devl")

    def test_write_paths_unc_mov(self):
        root = (
            "//zeus.lennon.co.kr/beluca/vfx/p/SBS_030/04_sq/E106/E106_S029_0020/"
            "comp/devl/nuke/v005/E106_S029_0020_comp_v005.nk"
        )
        _r, exr, mov = write_file_paths_from_nk_root_name(root)
        assert mov.startswith("//zeus.lennon.co.kr/")
        assert "/comp/devl/renders/E106_S029_0020_comp_v005.mov" in mov
        assert "E106_S029_0020_comp_v005.%04d.exr" in exr
