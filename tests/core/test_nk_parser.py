"""Tests for bpe.core.nk_parser — NK file parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.core.nk_parser import (
    _PRESET_DEFAULTS,
    _extract_all_blocks,
    _find_named_block,
    get_knob,
    merge_nk_preserve_root_template,
    merge_nodetree_content,
    merge_parsed_into_preset,
    parse_nk_file,
    parse_nk_for_preset,
)

# ---------------------------------------------------------------------------
# get_knob
# ---------------------------------------------------------------------------


class TestGetKnob:
    def test_quoted(self):
        assert get_knob(' fps "23.976"', "fps") == "23.976"

    def test_braced(self):
        assert get_knob(" fps {24}", "fps") == "24"

    def test_bare(self):
        assert get_knob(" fps 30", "fps") == "30"

    def test_missing(self):
        assert get_knob(" fps 30", "format") is None


# ---------------------------------------------------------------------------
# _extract_all_blocks / _find_named_block
# ---------------------------------------------------------------------------


class TestBlockExtraction:
    def test_single_block(self):
        nk = "Root {\n fps 24\n}\n"
        blocks = _extract_all_blocks(nk, "Root")
        assert len(blocks) == 1
        assert "fps 24" in blocks[0]

    def test_nested_braces(self):
        nk = "Root {\n format {1920 1080}\n}\n"
        blocks = _extract_all_blocks(nk, "Root")
        assert len(blocks) == 1
        assert "format {1920 1080}" in blocks[0]

    def test_multiple_blocks(self):
        nk = "Read {\n name Read1\n}\nRead {\n name Read2\n}\n"
        blocks = _extract_all_blocks(nk, "Read")
        assert len(blocks) == 2

    def test_find_named_block(self):
        nk = "Write {\n name Write1\n}\nWrite {\n name Write2\n}\n"
        block = _find_named_block(nk, "Write", "Write2")
        assert block is not None
        assert "Write2" in block

    def test_find_named_block_missing(self):
        nk = "Write {\n name Write1\n}\n"
        assert _find_named_block(nk, "Write", "Write99") is None


# ---------------------------------------------------------------------------
# parse_nk_file — full integration
# ---------------------------------------------------------------------------


class TestParseNkFile:
    def test_root_fps_and_format(self, tmp_path: Path):
        nk = 'Root {\n fps 24\n format "3840 2160 0 0 3840 2160 1 UHD"\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["fps"] == "24"
        assert result["plate_width"] == "3840"
        assert result["plate_height"] == "2160"

    def test_root_ocio(self, tmp_path: Path):
        nk = 'Root {\n customOCIOConfigPath "/path/to/config.ocio"\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["ocio_path"] == "/path/to/config.ocio"

    def test_write_exr_16bit(self, tmp_path: Path):
        nk = (
            "Write {\n"
            " file_type exr\n"
            " channels rgba\n"
            ' datatype "16 bit half"\n'
            ' compression "PIZ Wavelet"\n'
            ' metadata "all metadata"\n'
            ' ocioColorspace "ACES - ACEScg"\n'
            " name Write2\n"
            "}\n"
        )
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["write_enabled"] is True
        assert result["delivery_format"] == "EXR 16bit"
        assert result["write_channels"] == "rgba"
        assert result["write_out_colorspace"] == "ACES - ACEScg"
        assert result["write_transform_type"] == "colorspace"

    def test_write_exr_32bit(self, tmp_path: Path):
        nk = 'Write {\n file_type exr\n datatype "32 bit float"\n name Write2\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["delivery_format"] == "EXR 32bit"

    def test_write_mov(self, tmp_path: Path):
        nk = "Write {\n file_type mov\n name Write2\n}\n"
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["delivery_format"] == "ProRes 422 HQ"

    def test_write_display_view(self, tmp_path: Path):
        nk = 'Write {\n file_type exr\n display ACES\n view "Rec.709"\n name Write2\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["write_output_display"] == "ACES"
        assert result["write_output_view"] == "Rec.709"
        assert result["write_transform_type"] == "display/view"

    def test_read_colorspace(self, tmp_path: Path):
        nk = 'Read {\n colorspace "ACES - ACES2065-1"\n name Read4\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["read_input_transform"] == "ACES - ACES2065-1"

    def test_read_fallback_to_first(self, tmp_path: Path):
        """When no named Read is found, falls back to first Read block."""
        nk = 'Read {\n colorspace "sRGB"\n name SomeOtherRead\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["read_input_transform"] == "sRGB"

    def test_full_nk(self, tmp_path: Path):
        """Parse a realistic NK with Root + Read + Write."""
        nk = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Root {\n"
            " inputs 0\n"
            " fps 23.976\n"
            ' format "3840 2076 0 0 3840 2076 1 plate"\n'
            " colorManagement OCIO\n"
            " OCIO_config custom\n"
            ' customOCIOConfigPath "/mnt/ocio/config.ocio"\n'
            "}\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            ' colorspace "ACES - ACES2065-1"\n'
            " name Read4\n"
            "}\n"
            "Write {\n"
            " file_type exr\n"
            " channels rgba\n"
            ' datatype "16 bit half"\n'
            ' compression "PIZ Wavelet (32 scanlines)"\n'
            ' metadata "all metadata"\n'
            ' colorspace "ACES - ACEScg"\n'
            " name Write2\n"
            "}\n"
        )
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["fps"] == "23.976"
        assert result["plate_width"] == "3840"
        assert result["plate_height"] == "2076"
        assert result["ocio_path"] == "/mnt/ocio/config.ocio"
        assert result["write_enabled"] is True
        assert result["read_input_transform"] == "ACES - ACES2065-1"

    def test_invalid_path_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="NK 파일을 읽지 못했습니다"):
            parse_nk_file(str(tmp_path / "nonexistent.nk"))

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.nk"
        p.write_text("", encoding="utf-8")
        result = parse_nk_file(str(p))
        assert "_node_stats" in result
        assert result["_node_stats"]["total"] == 0
        assert result["_node_stats"]["by_type"] == {}

    def test_braced_format(self, tmp_path: Path):
        """Root format in {value} notation."""
        nk = "Root {\n format {1920 1080 0 0 1920 1080 1 HD}\n}\n"
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["plate_width"] == "1920"
        assert result["plate_height"] == "1080"

    def test_write_exr_datatype_inferred_when_missing(self, tmp_path: Path):
        """EXR Write without explicit datatype knob → inferred '16 bit half'."""
        nk = (
            'Write {\n file_type exr\n channels rgba\n compression "PIZ Wavelet"\n name Write2\n}\n'
        )
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["write_datatype"] == "16 bit half"
        assert result["delivery_format"] == "EXR 16bit"

    def test_write_exr_datatype_explicit_overrides_inference(self, tmp_path: Path):
        """Explicit datatype knob must not be replaced by inference."""
        nk = 'Write {\n file_type exr\n datatype "32 bit float"\n name Write2\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["write_datatype"] == "32 bit float"
        assert result["delivery_format"] == "EXR 32bit"


# ---------------------------------------------------------------------------
# parse_nk_for_preset
# ---------------------------------------------------------------------------


class TestParseNkForPreset:
    def test_fills_defaults_for_empty_file(self, tmp_path: Path):
        """Empty NK file should produce a dict with all default values."""
        p = tmp_path / "empty.nk"
        p.write_text("", encoding="utf-8")
        result, stats = parse_nk_for_preset(str(p))
        for key, default in _PRESET_DEFAULTS.items():
            assert key in result
            assert result[key] == default
        assert stats["total"] == 0

    def test_detected_values_override_defaults(self, tmp_path: Path):
        nk = (
            "Root {\n"
            " fps 24\n"
            ' format "4096 2160 0 0 4096 2160 1 UHD"\n'
            "}\n"
            "Write {\n"
            " file_type exr\n"
            ' datatype "32 bit float"\n'
            ' compression "DWAA"\n'
            ' ocioColorspace "ACES - ACEScg"\n'
            " name Write2\n"
            "}\n"
        )
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result, _stats = parse_nk_for_preset(str(p))
        assert result["fps"] == "24"
        assert result["plate_width"] == "4096"
        assert result["plate_height"] == "2160"
        assert result["delivery_format"] == "EXR 32bit"
        assert result["write_compression"] == "DWAA"
        assert result["write_out_colorspace"] == "ACES - ACEScg"
        assert result["write_colorspace"] == "ACES - ACEScg"

    def test_preset_name_sets_project_code(self, tmp_path: Path):
        p = tmp_path / "test.nk"
        p.write_text("", encoding="utf-8")
        result, _stats = parse_nk_for_preset(str(p), preset_name="MY_PROJECT")
        assert result["project_code"] == "MY_PROJECT"

    def test_write_colorspace_fallback(self, tmp_path: Path):
        """write_colorspace should fall back to write_out_colorspace."""
        nk = 'Write {\n file_type exr\n ocioColorspace "ACES - ACEScg"\n name Write2\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result, _stats = parse_nk_for_preset(str(p))
        assert result["write_colorspace"] == result["write_out_colorspace"]
        assert result["write_colorspace"] == "ACES - ACEScg"

    def test_invalid_path_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="NK 파일을 읽지 못했습니다"):
            parse_nk_for_preset(str(tmp_path / "nonexistent.nk"))

    def test_all_default_keys_present(self, tmp_path: Path):
        """Result should always contain every key from _PRESET_DEFAULTS."""
        p = tmp_path / "minimal.nk"
        p.write_text("Root {\n fps 30\n}\n", encoding="utf-8")
        result, _stats = parse_nk_for_preset(str(p))
        for key in _PRESET_DEFAULTS:
            assert key in result


# ---------------------------------------------------------------------------
# Extended parsing — OCIO LUT, Viewer, MOV, node stats, merge
# ---------------------------------------------------------------------------


class TestParseNkFileExtended:
    def test_root_ocio_lut_settings(self, tmp_path: Path):
        nk = (
            "Root {\n"
            ' workingSpaceLUT "ACES - ACEScg"\n'
            ' monitorLut "Rec.709"\n'
            ' int8Lut "sRGB"\n'
            ' int16Lut "ACEScc"\n'
            ' logLut "ADX10"\n'
            ' floatLut "ACEScg"\n'
            "}\n"
        )
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["working_space_lut"] == "ACES - ACEScg"
        assert r["monitor_lut"] == "Rec.709"
        assert r["int8_lut"] == "sRGB"
        assert r["int16_lut"] == "ACEScc"
        assert r["log_lut"] == "ADX10"
        assert r["float_lut"] == "ACEScg"

    def test_root_color_management(self, tmp_path: Path):
        nk = "Root {\n colorManagement OCIO\n}\n"
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["color_management"] == "OCIO"

    def test_root_format_name_plate(self, tmp_path: Path):
        nk = 'Root {\n format "3840 2076 0 0 3840 2076 1 plate"\n}\n'
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["plate_format_name"] == "plate"

    def test_viewer_process(self, tmp_path: Path):
        nk = 'Viewer {\n viewerProcess "Rec.709 (ACES)"\n name Viewer1\n}\n'
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["viewer_process"] == "Rec.709 (ACES)"

    def test_mov_write_node(self, tmp_path: Path):
        nk = (
            "Write {\n"
            " file_type mov\n"
            ' mov64_codec "Apple ProRes 422 HQ"\n'
            ' colorspace "Rec.709"\n'
            " name WriteMov\n"
            "}\n"
        )
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["mov_codec"] == "Apple ProRes 422 HQ"
        assert r["mov_colorspace"] == "Rec.709"
        assert r["delivery_format"] == "ProRes 422 HQ"

    def test_mov_extended_fields(self, tmp_path: Path):
        """MOV Write node: fps, channels, display, view, codec_profile are captured."""
        nk = (
            "Write {\n"
            " file_type mov\n"
            ' mov64_codec "apcn"\n'
            ' mov64_codec_profile "High Quality"\n'
            " fps 23.976\n"
            " channels rgb\n"
            " display ACES\n"
            ' view "Rec.709"\n'
            " name WriteMov\n"
            "}\n"
        )
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["mov_codec"] == "apcn"
        assert r["mov_profile"] == "High Quality"
        assert r["mov_fps"] == "23.976"
        assert r["mov_channels"] == "rgb"
        assert r["mov_display"] == "ACES"
        assert r["mov_view"] == "Rec.709"

    def test_exr_and_mov_write_both(self, tmp_path: Path):
        nk = (
            "Write {\n"
            " file_type mov\n"
            ' mov64_codec "ProRes"\n'
            " name WMov\n"
            "}\n"
            "Write {\n"
            " file_type exr\n"
            ' datatype "16 bit half"\n'
            ' compression "PIZ Wavelet"\n'
            ' ocioColorspace "ACES2065"\n'
            " name Write2\n"
            "}\n"
        )
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        assert r["mov_codec"] == "ProRes"
        assert r["write_out_colorspace"] == "ACES2065"
        assert r["delivery_format"] == "EXR 16bit"

    def test_node_stats(self, tmp_path: Path):
        nk = (
            "Root {\n fps 24\n}\n"
            "Read {\n name Read1\n}\n"
            "Read {\n name Read2\n}\n"
            "Write {\n file_type exr\n name Write2\n}\n"
        )
        p = tmp_path / "t.nk"
        p.write_text(nk, encoding="utf-8")
        r = parse_nk_file(str(p))
        stats = r["_node_stats"]
        assert stats["total"] >= 4
        assert stats["by_type"]["Root"] == 1
        assert stats["by_type"]["Write"] == 1
        assert len(stats["write_names"]) == 1
        assert len(stats["read_names"]) == 2

    def test_merge_parsed_into_preset(self, tmp_path: Path):
        p = tmp_path / "t.nk"
        p.write_text("Root {\n fps 30\n}\n", encoding="utf-8")
        raw = parse_nk_file(str(p))
        raw.pop("_node_stats", None)
        merged = merge_parsed_into_preset(raw)
        assert merged["fps"] == "30"
        assert merged["project_code"] == ""

    def test_merge_nk_preserve_root_template(self) -> None:
        old = (
            "set x 1\n"
            "Root {\n"
            " fps 24\n"
            ' customOCIOConfigPath "W:/old"\n'
            "}\n"
            "Write {\n name Write1\n}\n"
        )
        new = 'Root {\n fps 30\n customOCIOConfigPath "W:/new"\n}\nRead {\n name Read9\n}\n'
        out = merge_nk_preserve_root_template(old, new)
        assert "W:/old" in out
        assert "Read9" in out
        assert "Write1" not in out

    def test_merge_nodetree_content_with_root(self) -> None:
        """When new content has Root, delegate to merge_nk_preserve_root_template."""
        old = "Root {\n}\nWrite {\n name W1\n}\n"
        new = "Root {\n}\nRead {\n name R1\n}\n"
        out = merge_nodetree_content(old, new)
        assert "R1" in out
        assert "W1" not in out

    def test_merge_nodetree_content_no_root(self) -> None:
        """Nuke Ctrl+C style (no Root): append after old Root."""
        old = "Root {\n fps 24\n}\nWrite {\n name W1\n}\n"
        new = "Read {\n name R1\n}\n"
        out = merge_nodetree_content(old, new)
        assert "fps 24" in out
        assert "R1" in out
        assert "W1" not in out
