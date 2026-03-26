"""Tests for bpe.core.nk_parser — NK file parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.core.nk_parser import (
    _PRESET_DEFAULTS,
    _extract_all_blocks,
    _find_named_block,
    _get_knob,
    parse_nk_file,
    parse_nk_for_preset,
)

# ---------------------------------------------------------------------------
# _get_knob
# ---------------------------------------------------------------------------


class TestGetKnob:
    def test_quoted(self):
        assert _get_knob(' fps "23.976"', "fps") == "23.976"

    def test_braced(self):
        assert _get_knob(" fps {24}", "fps") == "24"

    def test_bare(self):
        assert _get_knob(" fps 30", "fps") == "30"

    def test_missing(self):
        assert _get_knob(" fps 30", "format") is None


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
        assert result == {}

    def test_braced_format(self, tmp_path: Path):
        """Root format in {value} notation."""
        nk = "Root {\n format {1920 1080 0 0 1920 1080 1 HD}\n}\n"
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_file(str(p))
        assert result["plate_width"] == "1920"
        assert result["plate_height"] == "1080"


# ---------------------------------------------------------------------------
# parse_nk_for_preset
# ---------------------------------------------------------------------------


class TestParseNkForPreset:
    def test_fills_defaults_for_empty_file(self, tmp_path: Path):
        """Empty NK file should produce a dict with all default values."""
        p = tmp_path / "empty.nk"
        p.write_text("", encoding="utf-8")
        result = parse_nk_for_preset(str(p))
        for key, default in _PRESET_DEFAULTS.items():
            assert key in result
            assert result[key] == default

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
        result = parse_nk_for_preset(str(p))
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
        result = parse_nk_for_preset(str(p), preset_name="MY_PROJECT")
        assert result["project_code"] == "MY_PROJECT"

    def test_write_colorspace_fallback(self, tmp_path: Path):
        """write_colorspace should fall back to write_out_colorspace."""
        nk = 'Write {\n file_type exr\n ocioColorspace "ACES - ACEScg"\n name Write2\n}\n'
        p = tmp_path / "test.nk"
        p.write_text(nk, encoding="utf-8")
        result = parse_nk_for_preset(str(p))
        assert result["write_colorspace"] == result["write_out_colorspace"]
        assert result["write_colorspace"] == "ACES - ACEScg"

    def test_invalid_path_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="NK 파일을 읽지 못했습니다"):
            parse_nk_for_preset(str(tmp_path / "nonexistent.nk"))

    def test_all_default_keys_present(self, tmp_path: Path):
        """Result should always contain every key from _PRESET_DEFAULTS."""
        p = tmp_path / "minimal.nk"
        p.write_text("Root {\n fps 30\n}\n", encoding="utf-8")
        result = parse_nk_for_preset(str(p))
        for key in _PRESET_DEFAULTS:
            assert key in result
