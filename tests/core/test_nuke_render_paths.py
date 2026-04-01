"""Tests for bpe.core.nuke_render_paths — UNC preservation."""

from __future__ import annotations

from bpe.core.nuke_render_paths import (
    comp_devl_dir_from_nk_path,
    normalize_path_str,
    normalize_unc_to_drive,
    render_path_for_extension,
    renders_dir_from_nk_path_robust,
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


class TestRenderPathForExtension:
    def test_sequence_dpx_unc(self):
        root = (
            "//zeus.lennon.co.kr/beluca/vfx/p/SBS_030/04_sq/E106/E106_S029_0020/"
            "comp/devl/nuke/v005/E106_S029_0020_comp_v005.nk"
        )
        p = render_path_for_extension(root, "dpx", "%04d")
        assert p is not None
        assert p.startswith("//zeus.lennon.co.kr/")
        assert "/comp/devl/renders/E106_S029_0020_comp_v005/" in p
        assert p.endswith(".%04d.dpx")

    def test_single_mov(self):
        root = (
            "W:/vfx/project_2026/SBS_030/04_sq/E106/E106_S029_0020/"
            "comp/devl/nuke/v005/E106_S029_0020_comp_v005.nk"
        )
        p = render_path_for_extension(root, "mov", "")
        assert p is not None
        assert p.endswith("/E106_S029_0020_comp_v005.mov")

    def test_ext_strips_leading_dot(self):
        root = "W:/vfx/p/PRJ/04_sq/E1/E1_S1/comp/devl/nuke/v001/E1_S1_comp_v001.nk"
        p = render_path_for_extension(root, ".png", "####")
        assert p is not None
        assert ".####.png" in p

    def test_empty_ext_returns_none(self):
        assert render_path_for_extension("W:/a/b/c.nk", "", "%04d") is None


class TestRendersDirFromNkPathRobust:
    def test_standard_comp_devl_nuke(self):
        root = (
            "W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/"
            "comp/devl/nuke/v005/E102_S012_0340_comp_v005.nk"
        )
        got = renders_dir_from_nk_path_robust(root)
        assert got == ("W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/comp/devl/renders")

    def test_nonstandard_comp_nuke_without_devl_in_path(self):
        """NK 가 comp/nuke/v###/ 에만 있어도 comp/devl/renders 로 고정."""
        root = (
            "W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/"
            "comp/nuke/v005/E102_S012_0340_comp_v005.nk"
        )
        got = renders_dir_from_nk_path_robust(root)
        assert got == ("W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/comp/devl/renders")

    def test_unc(self):
        root = (
            "//zeus.lennon.co.kr/beluca/vfx/project_2026/SBS_030/04_sq/E102/"
            "E102_S012_0340/comp/devl/nuke/v005/E102_S012_0340_comp_v005.nk"
        )
        got = renders_dir_from_nk_path_robust(root)
        assert got is not None
        assert got.endswith("/comp/devl/renders")
        assert got.startswith("//zeus.lennon.co.kr/")

    def test_no_comp_returns_none(self):
        assert renders_dir_from_nk_path_robust("W:/tmp/shot.nk") is None


class TestNormalizeUncToDrive:
    def test_maps_longest_prefix_first(self):
        m = {
            "//zeus.lennon.co.kr": "X:",
            "//zeus.lennon.co.kr/beluca": "W:",
        }
        p = "//zeus.lennon.co.kr/beluca/vfx/project_2026/foo"
        assert normalize_unc_to_drive(p, m) == "W:/vfx/project_2026/foo"

    def test_already_drive_unchanged(self):
        m = {"//zeus.lennon.co.kr/beluca": "W:"}
        assert normalize_unc_to_drive("W:/vfx/foo", m) == "W:/vfx/foo"

    def test_empty_mappings_unchanged(self):
        p = "//zeus.lennon.co.kr/beluca/vfx/foo"
        assert normalize_unc_to_drive(p, {}) == p


class TestNormalizePathStr:
    def test_unc_to_w_with_default_settings(self, tmp_app_dir) -> None:
        p = "//zeus.lennon.co.kr/beluca/vfx/project_2026/SBS_030/foo"
        got = normalize_path_str(p)
        assert got.startswith("W:/")
        assert "zeus" not in got.lower()

    def test_drive_unchanged(self, tmp_app_dir) -> None:
        assert normalize_path_str("W:/vfx/foo") == "W:/vfx/foo"
