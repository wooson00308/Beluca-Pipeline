"""Tests for bpe.core.nuke_render_paths — UNC preservation."""

from __future__ import annotations

from bpe.core.nuke_render_paths import (
    canonical_frame_pattern,
    classify_recoverable_write_path,
    comp_devl_dir_from_nk_path,
    eval_managed_write_tcl,
    ext_from_write_script_text,
    extract_frame_pattern_from_write_script,
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

    def test_rnd_devl_nuke_standard(self):
        root = (
            "W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/"
            "rnd/devl/nuke/v001/E102_S012_0340_rnd_v001.nk"
        )
        got = renders_dir_from_nk_path_robust(root)
        assert got == ("W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/rnd/devl/renders")

    def test_crowd_devl_nuke_standard(self):
        root = "W:/vfx/p/PRJ/04_sq/E01/E01_S01_0010/crowd/devl/nuke/v002/e01_s01_0010_crowd_v002.nk"
        got = renders_dir_from_nk_path_robust(root)
        assert got == "W:/vfx/p/PRJ/04_sq/E01/E01_S01_0010/crowd/devl/renders"

    def test_nonstandard_without_devl_no_comp_returns_none(self):
        """rnd/nuke/v### (devl 없음) 는 폴백하지 않음."""
        root = "W:/vfx/p/PRJ/04_sq/E01/E01_S01_0010/rnd/nuke/v001/x_rnd_v001.nk"
        assert renders_dir_from_nk_path_robust(root) is None


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


_ROOT = (
    "W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/"
    "comp/devl/nuke/v005/E102_S012_0340_comp_v005.nk"
)
_SV = "E102_S012_0340_comp_v005"
_RD = "W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S012_0340/comp/devl/renders"
_UNC = {"//zeus.lennon.co.kr/beluca": "W:"}

# 레거시 템플릿 Tcl 원문 (SBS_030_template.nk 136/244행과 동일 형태, 이스케이프 제거)
_TCL_MOV = (
    '"[string trim [value root.name] nuke/[file tail [value root.name]]]'
    '/renders/[string trim [file tail [value root.name]] .nk].mov"'
)
_TCL_EXR = (
    '"[string trim [value root.name] nuke/[file tail [value root.name]]]'
    "/renders/[string trim [file tail [value root.name]] .nk]"
    '/[string trim [file tail [value root.name]] .nk].%04d.exr"'
)
_TCL_MOV_LUT = _TCL_MOV.replace(".mov", "_lut.mov")
_TCL_DIRNAME_MOV = (
    '"[file dirname [file dirname [file dirname [value root.name]]]]'
    '/renders/[file rootname [file tail [value root.name]]].mov"'
)


class TestCanonicalFramePattern:
    def test_zeroless_pad_fixed(self):
        assert canonical_frame_pattern("%4d") == "%04d"
        assert canonical_frame_pattern("%5d") == "%05d"

    def test_hashes(self):
        assert canonical_frame_pattern("####") == "%04d"
        assert canonical_frame_pattern("#####") == "%05d"
        assert canonical_frame_pattern("###") == "%03d"

    def test_intentional_forms_kept(self):
        assert canonical_frame_pattern("%04d") == "%04d"
        assert canonical_frame_pattern("%d") == "%d"


class TestExtractFramePatternFromWriteScript:
    def test_broken_plain_pad_sanitized(self):
        assert extract_frame_pattern_from_write_script(f"{_RD}/{_SV}/{_SV}.%4d.exr") == "%04d"

    def test_tcl_template(self):
        assert extract_frame_pattern_from_write_script(_TCL_EXR) == "%04d"

    def test_default(self):
        assert extract_frame_pattern_from_write_script(f"{_RD}/{_SV}.mov") == "%04d"


class TestExtFromWriteScriptText:
    def test_bug_artifact_name_rejected(self):
        assert ext_from_write_script_text(f"{_RD}/{_SV}/{_SV}.%04d.name") is None
        assert ext_from_write_script_text(f"{_RD}/{_SV}.name") is None

    def test_plain_and_broken_pad(self):
        assert ext_from_write_script_text(f"{_RD}/{_SV}/{_SV}.%4d.exr") == "exr"

    def test_tcl_mov_not_name(self):
        # ``[value root.name]`` 의 ``.name]`` 오매칭 회귀 방지
        assert ext_from_write_script_text(_TCL_MOV) == "mov"

    def test_no_ext(self):
        assert ext_from_write_script_text(f"{_RD}/{_SV}") is None


class TestEvalManagedWriteTcl:
    def test_standard_exr(self):
        assert eval_managed_write_tcl(_TCL_EXR, _ROOT) == f"{_RD}/{_SV}/{_SV}.%04d.exr"

    def test_standard_mov(self):
        assert eval_managed_write_tcl(_TCL_MOV, _ROOT) == f"{_RD}/{_SV}.mov"

    def test_lut_suffix_preserved(self):
        # Write 2개 중 하나가 ``_lut`` 커스텀 — 접미사가 보존되어야 충돌이 없다.
        assert eval_managed_write_tcl(_TCL_MOV_LUT, _ROOT) == f"{_RD}/{_SV}_lut.mov"

    def test_dirname_form(self):
        assert eval_managed_write_tcl(_TCL_DIRNAME_MOV, _ROOT) == f"{_RD}/{_SV}.mov"

    def test_unc_root_mapped_to_drive(self):
        unc_root = _ROOT.replace("W:", "//zeus.lennon.co.kr/beluca")
        assert eval_managed_write_tcl(_TCL_MOV, unc_root, _UNC) == f"{_RD}/{_SV}.mov"

    def test_unknown_tcl_returns_none(self):
        assert eval_managed_write_tcl('"[python {custom()}]/out.mov"', _ROOT) is None

    def test_plain_path_returns_none(self):
        assert eval_managed_write_tcl(f"{_RD}/{_SV}.mov", _ROOT) is None

    def test_escaped_brackets(self):
        # .nk 파일/toScript 는 ``\[`` 이스케이프를 포함할 수 있다.
        esc = _TCL_MOV.replace("[", "\\[")
        assert eval_managed_write_tcl(esc, _ROOT) == f"{_RD}/{_SV}.mov"


class TestClassifyRecoverableWritePath:
    def test_a1_zeroless_pad(self):
        assert classify_recoverable_write_path(f"{_RD}/{_SV}/{_SV}.%4d.exr", _ROOT)
        assert classify_recoverable_write_path(f"{_RD}/{_SV}/{_SV}.%5d.exr", "")

    def test_a1_protected_outside_renders(self):
        assert classify_recoverable_write_path("C:/temp/test.%4d.exr", _ROOT) is None

    def test_a2_name_ext(self):
        assert classify_recoverable_write_path(f"{_RD}/{_SV}/{_SV}.%04d.name", _ROOT)
        assert classify_recoverable_write_path("C:/other/out.name", _ROOT) is None

    def test_b_unc_unnormalized(self):
        unc = f"{_RD}/{_SV}/{_SV}.%04d.exr".replace("W:", "//zeus.lennon.co.kr/beluca")
        assert classify_recoverable_write_path(unc, _ROOT, _UNC)

    def test_b_comp_escape(self):
        assert classify_recoverable_write_path(f"W:/comp/devl/renders/{_SV}/{_SV}.%04d.exr", _ROOT)

    def test_b_protected_local_copy(self):
        local = f"D:/cache/renders/{_SV}/{_SV}.%04d.exr"
        assert classify_recoverable_write_path(local, _ROOT) is None

    def test_b_protected_artist_variant_name(self):
        assert classify_recoverable_write_path(f"{_RD}/{_SV}_temp.%04d.exr", _ROOT) is None
        assert classify_recoverable_write_path(f"{_RD}/{_SV}_lut.mov", _ROOT) is None

    def test_b_protected_other_stem(self):
        assert classify_recoverable_write_path(f"{_RD}/OTHER_v001.%04d.exr", _ROOT) is None

    def test_b_mov_and_hashes(self):
        assert classify_recoverable_write_path(f"W:/comp/devl/renders/{_SV}.mov", _ROOT)
        assert classify_recoverable_write_path(f"W:/comp/devl/renders/{_SV}.####.exr", _ROOT)

    def test_tcl_and_empty_rejected(self):
        assert classify_recoverable_write_path(_TCL_MOV, _ROOT) is None
        assert classify_recoverable_write_path("", _ROOT) is None

    def test_baked_frame_number_rejected(self):
        assert classify_recoverable_write_path(f"{_RD}/{_SV}.1001.exr", _ROOT) is None

    def test_version_mismatch_flag(self):
        old = f"{_RD}/{_SV.replace('v005', 'v004')}.%04d.exr"
        assert classify_recoverable_write_path(old, _ROOT) is None
        assert classify_recoverable_write_path(old, _ROOT, allow_version_mismatch=True)
        other = f"{_RD}/OTHER_comp_v004.%04d.exr"
        assert classify_recoverable_write_path(other, _ROOT, allow_version_mismatch=True) is None
