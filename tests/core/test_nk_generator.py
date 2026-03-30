"""Tests for bpe.core.nk_generator — NK generation and patching utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bpe.core.nk_generator import (
    _find_blocks_with_positions,
    _generate_nk_minimal,
    _nk_escape_quotes,
    _patch_read_colorspace,
    _patch_viewer_fps,
    _patch_write2_from_preset,
    _preset_datatype_string,
    _preset_first_part,
    _replace_knob_in_block,
    _to_nk_path,
    generate_nk_content,
)

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


class TestToNkPath:
    def test_backslash(self):
        assert _to_nk_path("C:\\foo\\bar") == "C:/foo/bar"

    def test_forward_slash(self):
        assert _to_nk_path("/mnt/data") == "/mnt/data"

    def test_path_object(self):
        assert "/" in _to_nk_path(Path("/a/b"))


class TestNkEscapeQuotes:
    def test_quotes(self):
        assert _nk_escape_quotes('say "hi"') == 'say \\"hi\\"'

    def test_backslash(self):
        assert _nk_escape_quotes("a\\b") == "a\\\\b"

    def test_none(self):
        assert _nk_escape_quotes("") == ""


# ---------------------------------------------------------------------------
# _find_blocks_with_positions
# ---------------------------------------------------------------------------


class TestFindBlocks:
    def test_single(self):
        nk = "Write {\n name Write2\n}\n"
        blocks = _find_blocks_with_positions(nk, "Write")
        assert len(blocks) == 1
        start, end, inner = blocks[0]
        assert "name Write2" in inner
        assert nk[start:end] == "Write {\n name Write2\n}"

    def test_nested(self):
        nk = "Root {\n format {1920 1080}\n}\n"
        blocks = _find_blocks_with_positions(nk, "Root")
        assert len(blocks) == 1
        assert "format {1920 1080}" in blocks[0][2]

    def test_multiple(self):
        nk = "Read {\n name A\n}\nRead {\n name B\n}\n"
        assert len(_find_blocks_with_positions(nk, "Read")) == 2

    def test_no_match(self):
        assert _find_blocks_with_positions("Foo {\n}\n", "Bar") == []


# ---------------------------------------------------------------------------
# _replace_knob_in_block
# ---------------------------------------------------------------------------


class TestReplaceKnob:
    def test_quoted(self):
        inner = '\n file "old.exr"\n name Write2\n'
        result = _replace_knob_in_block(inner, "file", "new.exr")
        assert '"new.exr"' in result

    def test_braced(self):
        inner = "\n colorspace {scene_linear}\n name Read4\n"
        result = _replace_knob_in_block(inner, "colorspace", "ACES")
        assert '"ACES"' in result
        assert "{scene_linear}" not in result

    def test_bare_token(self):
        inner = "\n colorspace scene_linear\n name Read4\n"
        result = _replace_knob_in_block(inner, "colorspace", "ACES")
        assert '"ACES"' in result

    def test_missing_knob(self):
        inner = "\n name Write2\n"
        assert _replace_knob_in_block(inner, "colorspace", "X") == inner


# ---------------------------------------------------------------------------
# Preset helpers
# ---------------------------------------------------------------------------


class TestPresetHelpers:
    def test_datatype_16bit(self):
        assert _preset_datatype_string({"write_datatype": "16 bit half"}) == "16 bit half"

    def test_datatype_32bit(self):
        assert _preset_datatype_string({"write_datatype": "32 bit float"}) == "32 bit float"

    def test_datatype_integer(self):
        assert _preset_datatype_string({"write_datatype": "8 bit integer"}) == "8 bit fixed"

    def test_datatype_default(self):
        assert _preset_datatype_string({}) == "16 bit half"

    def test_first_part_rgb(self):
        assert _preset_first_part({"write_channels": "rgb"}) == "rgb"

    def test_first_part_default(self):
        assert _preset_first_part({}) == "rgba"


# ---------------------------------------------------------------------------
# Patch functions
# ---------------------------------------------------------------------------


class TestPatchReadColorspace:
    def test_patches_read4(self):
        body = 'Read {\n colorspace "old"\n name Read4\n}\n'
        result = _patch_read_colorspace(body, "NEW_CS")
        assert '"NEW_CS"' in result
        assert '"old"' not in result

    def test_skips_non_read_blocks(self):
        body = 'Read {\n colorspace "old"\n name SomeNode\n}\n'
        result = _patch_read_colorspace(body, "NEW_CS")
        # SomeNode doesn't match Read[\w\d_]+ pattern, so no change
        assert '"old"' in result


class TestPatchViewerFps:
    def test_replaces_fps(self):
        body = "Viewer {\n frame_range 1001-1100\n fps 24\n}\n"
        result = _patch_viewer_fps(body, "30")
        assert "fps 30" in result
        assert "fps 24" not in result


class TestPatchWrite2DirnameTcl:
    """shot_node_template Write2 — file dirname Tcl 식과 _patch_write2_from_preset 호환."""

    def test_preserves_dirname_tcl_not_string_trim(self):
        _file_knob = (
            r' file "\[file dirname \[file dirname \[file dirname \[value root.name]]]]'
            r"/renders/\[file rootname \[file tail \[value root.name]]]/"
            r'\[file rootname \[file tail \[value root.name]]].%04d.exr"\n'
        )
        body = (
            "Write {\n"
            + _file_knob
            + " file_type exr\n"
            + " autocrop true\n"
            + ' compression "PIZ Wavelet (32 scanlines)"\n'
            + ' metadata "all metadata"\n'
            + " first_part rgba\n"
            + ' colorspace "ACES - ACES2065-1"\n'
            + " version 17\n"
            + ' ocioColorspace "ACES - ACEScg"\n'
            + " display ACES\n"
            + " view Rec.709\n"
            + " name Write2\n"
            + "}\n"
        )
        preset = {
            "write_compression": "PIZ Wavelet (32 scanlines)",
            "write_metadata": "all metadata",
            "write_channels": "all",
            "write_transform_type": "colorspace",
            "write_out_colorspace": "ACES - ACES2065-1",
            "write_output_display": "ACES",
            "write_output_view": "Rec.709",
        }
        new_body, ok = _patch_write2_from_preset(body, preset)
        assert ok
        assert "string trim" not in new_body
        assert r"\[file dirname \[file dirname \[file dirname \[value root.name]]]]" in new_body
        assert "name Write2" in new_body


# ---------------------------------------------------------------------------
# generate_nk_content — minimal fallback
# ---------------------------------------------------------------------------


class TestGenerateNkMinimal:
    def test_contains_root_and_nodes(self):
        paths = {
            "shot_root": Path("/shots/E01_S01"),
            "plate_hi": Path("/shots/E01_S01/plate/org/v001/hi"),
            "edit": Path("/shots/E01_S01/edit"),
            "renders": Path("/shots/E01_S01/comp/devl/renders"),
        }
        preset = {
            "fps": "24",
            "plate_width": 1920,
            "plate_height": 1080,
        }
        result = _generate_nk_minimal(preset, "E01_S01_0010", paths, "v001")
        assert "Root {" in result
        assert "fps 24" in result
        assert "Read_Plate" in result
        assert "setup_pro_write" in result
        assert "Read_Edit" in result


class TestGenerateNkContent:
    def test_no_template_fallback(self):
        """When no template is found, falls back to minimal NK."""
        paths = {
            "shot_root": Path("/shots/E01_S01"),
            "plate_hi": Path("/shots/E01_S01/plate/org/v001/hi"),
            "edit": Path("/shots/E01_S01/edit"),
            "renders": Path("/shots/E01_S01/comp/devl/renders"),
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080}
        with (
            patch("bpe.core.nk_generator.load_preset_template", return_value=None),
            patch("bpe.core.nk_generator.get_shot_node_template_path", return_value=None),
        ):
            content, warnings = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        assert "Root {" in content
        assert len(warnings) == 1
        assert "최소 NK" in warnings[0]

    def test_with_custom_template(self):
        """When a custom preset template exists, uses it."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Root {\n"
            " fps 23.976\n"
            "}\n"
            "Viewer {\n"
            " frame_range 1001-1100\n"
            " fps 23.976\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/shots/E01_S01"),
            "plate_hi": Path("/shots/E01_S01/plate/org/v001/hi"),
            "edit": Path("/shots/E01_S01/edit"),
            "renders": Path("/shots/E01_S01/comp/devl/renders"),
        }
        preset = {
            "fps": "30",
            "plate_width": 1920,
            "plate_height": 1080,
            "project_code": "TEST",
        }
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, warnings = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        assert "fps 30" in content
        # Root override block should be present
        assert content.count("Root {") >= 2

    def test_shot_name_substitution(self):
        """Template sample shot name/root are replaced."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            " file W:/vfx/project_2026/SBS_030/04_sq/E107/E107_S022_0080/plate/E107_S022_0080.exr\n"
            " name Read4\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/new/shot/root"),
            "plate_hi": Path("/new/shot/root/plate/hi"),
            "edit": Path("/new/shot/root/edit"),
            "renders": Path("/new/shot/root/renders"),
        }
        preset = {
            "fps": "24",
            "plate_width": 1920,
            "plate_height": 1080,
            "project_code": "PROJ",
        }
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "NEW_SHOT", paths, "v001")
        assert "E107_S022_0080" not in content
        assert "NEW_SHOT" in content
        assert "/new/shot/root" in content
