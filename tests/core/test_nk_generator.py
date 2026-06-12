"""Tests for bpe.core.nk_generator — NK generation and patching utilities."""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

from bpe.core.nk_generator import (
    _discover_edit_sequence_basename,
    _discover_plate_sequence_basename,
    _find_blocks_with_positions,
    _generate_nk_minimal,
    _is_edit_read_block,
    _is_edit_read_file_path,
    _nk_escape_quotes,
    _normalize_plate_basename,
    _parse_stts_inner,
    _patch_read_colorspace,
    _patch_read_edit_file_paths,
    _patch_read_frame_range,
    _patch_viewer_fps,
    _patch_write2_from_preset,
    _preset_datatype_string,
    _preset_first_part,
    _read_file_type_from_plate_basename,
    _replace_knob_in_block,
    _scan_plate_frame_range,
    _template_sample_path_warnings,
    _to_nk_path,
    _write2_inner_is_exr_delivery_target,
    generate_nk_content,
    strip_eo7_mov_problem_knobs_from_nk_body,
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


class TestWrite2NonExrPresetPreserved:
    """MOV (etc.) Write2 must not be rebuilt as EXR — preset NK stays faithful."""

    _preset = {
        "write_compression": "DWAA (lossy)",
        "write_metadata": "no metadata",
        "write_channels": "rgb",
        "write_transform_type": "colorspace",
        "write_out_colorspace": "ACES - ACEScg",
        "write_output_display": "ACES",
        "write_output_view": "Rec.709",
    }

    def test_mov_write2_unchanged_returns_ok_true(self):
        body = (
            'Write {\n file "X:/proj/renders/foo.mov"\n file_type mov\n'
            " mov64_codec appr\n name Write2\n}\n"
        )
        new_body, ok = _patch_write2_from_preset(body, dict(self._preset))
        assert ok is True
        assert new_body == body

    def test_quoted_exr_write2_still_patched(self):
        body = (
            'Write {\n file "X:/r/foo.%04d.exr"\n file_type "exr"\n autocrop true\n'
            ' compression "PIZ Wavelet (32 scanlines)"\n'
            ' metadata "all metadata"\n first_part rgba\n'
            ' colorspace "ACES - ACES2065-1"\n version 3\n'
            ' ocioColorspace "ACES - ACEScg"\n display ACES\n view Rec.709\n name Write2\n}\n'
        )
        new_body, ok = _patch_write2_from_preset(body, dict(self._preset))
        assert ok is True
        assert 'compression "DWAA (lossy)"' in new_body
        assert 'metadata "no metadata"' in new_body

    def test_braced_exr_write2_still_patched(self):
        body = (
            "Write {\n file X:/r/foo.%04d.exr\n file_type {exr}\n autocrop true\n"
            ' compression "PIZ Wavelet (32 scanlines)"\n'
            ' metadata "all metadata"\n first_part rgba\n'
            ' colorspace "ACES - ACES2065-1"\n version 3\n'
            ' ocioColorspace "ACES - ACEScg"\n display ACES\n view Rec.709\n name Write2\n}\n'
        )
        new_body, ok = _patch_write2_from_preset(body, dict(self._preset))
        assert ok is True
        assert 'compression "DWAA (lossy)"' in new_body


class TestWrite2InnerIsExrDeliveryTarget:
    def test_defaults(self):
        assert _write2_inner_is_exr_delivery_target("") is True
        assert _write2_inner_is_exr_delivery_target("\n name Write2\n") is True

    def test_mov_not_exr_target(self):
        assert _write2_inner_is_exr_delivery_target(" file_type mov\n") is False

    def test_openexr_alias(self):
        assert _write2_inner_is_exr_delivery_target(" file_type openexr\n") is True


# ---------------------------------------------------------------------------
# Plate frame range + eo7 MOV strip
# ---------------------------------------------------------------------------


class TestPlateFrameRangeAndEo7Strip:
    def test_parse_stts_inner(self):
        body = (
            struct.pack(">B", 0)
            + b"\x00\x00\x00"
            + struct.pack(">I", 1)
            + struct.pack(">I", 74)
            + struct.pack(">I", 1000)
        )
        assert _parse_stts_inner(body) == 74

    def test_scan_plate_frame_range_mov_mock(self, tmp_path):
        hi = tmp_path / "hi"
        hi.mkdir()
        (hi / "p.mov").write_bytes(b"fake")
        with patch("bpe.core.nk_generator._count_mov_frames", return_value=74):
            # MOV 파일은 Nuke에서 1번 프레임부터 시작 → (1, n)
            assert _scan_plate_frame_range(hi) == (1, 74)

    def test_scan_plate_frame_range(self, tmp_path):
        hi = tmp_path / "plate" / "org" / "v001" / "hi"
        hi.mkdir(parents=True)
        for name in (
            "E01_S01_0010_org_v001.1001.exr",
            "E01_S01_0010_org_v001.1010.exr",
            "E01_S01_0010_org_v001.1023.exr",
        ):
            (hi / name).write_bytes(b"")
        assert _scan_plate_frame_range(hi) == (1001, 1023)

    def test_scan_plate_frame_range_empty(self, tmp_path):
        assert _scan_plate_frame_range(tmp_path / "nope") is None

    def test_scan_plate_frame_range_dpx(self, tmp_path):
        hi = tmp_path / "hi"
        hi.mkdir()
        for name in (
            "S260_0515_org_v001.1001.dpx",
            "S260_0515_org_v001.1005.dpx",
            "S260_0515_org_v001.1010.dpx",
        ):
            (hi / name).write_bytes(b"")
        assert _scan_plate_frame_range(hi) == (1001, 1010)

    def test_patch_read_frame_range(self):
        nk = """
Read {
 file "W:/proj/plate/org/v001/hi/E01.1001.exr"
 first 1001
 last 1123
 origfirst 1001
 origlast 1123
 origset true
 name Read4
}
Viewer {
 frame_range 1001-1123
 fps 23.976
 name Viewer1
}
"""
        out = _patch_read_frame_range(nk, 1001, 1060)
        assert " last 1060" in out
        assert "origlast 1060" in out
        assert "origset false" in out
        assert "frame_range 1001-1060" in out

    def test_strip_eo7_mov_problem_knobs(self):
        nk = """Write {
 file "x.mov"
 file_type mov
 raw true
 colorspace qc_interchange
 in_colorspace scene_linear
 out_colorspace scene_linear
 name eo7Write1
}
"""
        out = strip_eo7_mov_problem_knobs_from_nk_body(nk)
        assert "raw true" not in out
        assert "qc_interchange" not in out
        assert "in_colorspace scene_linear" not in out
        assert "name eo7Write1" in out

    def test_generate_nk_content_patches_frame_range_from_disk(self, tmp_path):
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        (plate_hi / "E01_S01_0010_org_v001.1001.exr").write_bytes(b"")
        (plate_hi / "E01_S01_0010_org_v001.1023.exr").write_bytes(b"")
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            f' file "{ph}/E01_S01_0010_org_v001.1001.exr"\n'
            " first 1001\n"
            " last 1123\n"
            " origfirst 1001\n"
            " origlast 1123\n"
            " origset true\n"
            " name Read4\n"
            "}\n"
            "Viewer {\n"
            " frame_range 1001-1123\n"
            " fps 23.976\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        assert " last 1023" in content
        assert "frame_range 1001-1023" in content
        assert "origset false" in content
        assert "first_frame 1001" in content
        assert "last_frame 1023" in content
        norm = content.replace("\\", "/")
        assert 'file_type "exr"' in norm or "file_type exr" in norm

    def test_generate_nk_content_syncs_plate_frames_when_scan_fails(self, tmp_path):
        """스캔 실패 시에도 플레이트 Read·Viewer·Root를 기본 1001–1123에 맞춘다."""
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            f' file "{ph}/E01_S01_0010_org_v001.1001.exr"\n'
            " first 1\n"
            " last 1\n"
            " origfirst 1\n"
            " origlast 1\n"
            " origset true\n"
            " name Read4\n"
            "}\n"
            "Viewer {\n"
            " frame_range 1-1\n"
            " fps 23.976\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, warnings = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        assert " first 1001" in content
        assert " last 1123" in content
        assert "origfirst 1001" in content
        assert "origlast 1123" in content
        assert "frame_range 1001-1123" in content
        assert "first_frame 1001" in content
        assert "last_frame 1123" in content
        assert any("프레임 범위" in w for w in warnings)

    def test_generate_nk_content_patches_second_root_frame_range(self, tmp_path):
        """템플릿에 Root가 있으면 삽입 Root와 함께 last_frame 등을 플레이트 스캔값으로 통일한다."""
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        (plate_hi / "E01_S01_0010_org_v001.1001.exr").write_bytes(b"")
        (plate_hi / "E01_S01_0010_org_v001.1023.exr").write_bytes(b"")
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Root {\n"
            " inputs 0\n"
            " fps 23.976\n"
            " first_frame 1001\n"
            " last_frame 9999\n"
            "}\n"
            "Read {\n"
            f' file "{ph}/E01_S01_0010_org_v001.1001.exr"\n'
            " name Read4\n"
            "}\n"
            "Viewer {\n"
            " frame_range 1001-1100\n"
            " fps 23.976\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        assert content.count("last_frame 1023") >= 2
        assert content.count("first_frame 1001") >= 2

    def test_plate_read_inserts_file_type_when_knob_missing(self, tmp_path):
        """템플릿에 file_type 줄이 없어도 디스크 DPX면 file_type dpx 삽입."""
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        for fr in (1001, 1002):
            (plate_hi / f"E01_S01_0010_org_v001.{fr}.dpx").write_bytes(b"")
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            " inputs 0\n"
            f' file "{ph}/E01_S01_0010_org_v001.1001.exr"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        norm = content.replace("\\", "/")
        assert 'file_type "dpx"' in norm
        assert ".dpx" in norm

    def test_plate_read_uses_disk_dpx_sequence_basename(self, tmp_path):
        """디스크 DPX 시퀀스 + 템플릿 file_type exr 이면 file·file_type 모두 dpx에 맞춘다."""
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        for fr in (1001, 1002, 1003):
            (plate_hi / f"s260_0515_org_v001.{fr}.dpx").write_bytes(b"")
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            f' file "{ph}/E102_wrong_org_v001.1001.exr"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "S260_0515", paths, "v001")
        norm = content.replace("\\", "/")
        assert "s260_0515_org_v001.####.dpx" in norm
        assert "E102_wrong" not in norm
        assert 'file_type "dpx"' in norm

    def test_plate_read_uses_disk_tiff_sequence(self, tmp_path):
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        for fr in (1001, 1002):
            (plate_hi / f"E01_S01_0010_org_v001.{fr}.tif").write_bytes(b"")
        ph = plate_hi.as_posix()
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            f' file "{ph}/E01_S01_0010_org_v001.1001.exr"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080, "project_code": "X"}
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        norm = content.replace("\\", "/")
        assert 'file_type "tiff"' in norm
        assert ".tif" in norm


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

    def test_minimal_plate_uses_dpx_sequence_on_disk(self, tmp_path):
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        (plate_hi / "E01_S01_0010_delivery.1001.dpx").write_bytes(b"")
        (plate_hi / "E01_S01_0010_delivery.1002.dpx").write_bytes(b"")
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080}
        result = _generate_nk_minimal(preset, "E01_S01_0010", paths, "v001")
        norm = result.replace("\\", "/")
        assert "file_type dpx" in norm
        assert "E01_S01_0010_delivery.####.dpx" in norm

    def test_minimal_mov_write_single_file_no_frame_padding(self):
        """MOV는 단일 파일 — #### 접미사 없이 경로를 만든다 (Nuke 멀티프레임 Write 오류 방지)."""
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
            "delivery_format": "ProRes 422 HQ",
        }
        result = _generate_nk_minimal(preset, "E01_S01_0010", paths, "v001")
        assert "file_type mov" in result
        assert "/E01_S01_0010_comp_v001.mov" in result.replace("\\", "/")
        assert "####.mov" not in result

    def test_minimal_mov_plate_folder(self):
        """plate_hi가 v001/mov/ 이면 Read_Plate도 MOV로 맞춘다."""
        paths = {
            "shot_root": Path("/shots/E01_S01"),
            "plate_hi": Path("/shots/E01_S01/plate/org/v001/mov"),
            "edit": Path("/shots/E01_S01/edit"),
            "renders": Path("/shots/E01_S01/comp/devl/renders"),
        }
        preset = {"fps": "24", "plate_width": 1920, "plate_height": 1080}
        result = _generate_nk_minimal(preset, "E01_S01_0010", paths, "v001")
        norm = result.replace("\\", "/")
        assert "file_type mov" in norm
        assert "plate/org/v001/mov" in norm
        assert "E01_S01_0010_org_v001.mov" in norm


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
        assert "customOCIOConfigPath" not in content

    def test_injected_root_omits_ocio_when_ocio_path_empty(self):
        template_body = "set cut_paste_input [stack 0]\nversion 14.1 v4\nRead {\n name Read1\n}\n"
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
            "project_code": "X",
        }
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        norm = content.replace("\\", "/")
        assert "customOCIOConfigPath" not in norm
        assert "OCIO_config custom" not in norm
        assert "colorManagement OCIO" not in norm

    def test_injected_root_includes_ocio_when_path_set(self):
        template_body = "set cut_paste_input [stack 0]\nversion 14.1 v4\nRead {\n name Read1\n}\n"
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
            "project_code": "X",
            "ocio_path": "W:/configs/aces_1.2/config.ocio",
        }
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, "E01_S01_0010", paths, "v001")
        norm = content.replace("\\", "/")
        assert "colorManagement OCIO" in norm
        assert "OCIO_config custom" in norm
        assert "W:/configs/aces_1.2/config.ocio" in norm

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

    def test_plate_read_repoints_to_current_shot_plate_hi(self):
        """템플릿이 다른 샷(E102) 플레이트 경로로 저장돼 있어도 현재 샷 plate_hi로 고친다."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "Read {\n"
            " file_type exr\n"
            ' file "W:/vfx/E102/E102_S001_0020/plate/org/v001/hi/'
            'E102_S001_0020_org_v001.1001.exr"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/shots/E109_S002_0050"),
            "plate_hi": Path("/shots/E109_S002_0050/plate/org/v001/hi"),
            "edit": Path("/shots/E109_S002_0050/edit"),
            "renders": Path("/shots/E109_S002_0050/renders"),
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
            content, _ = generate_nk_content(preset, "E109_S002_0050", paths, "v001")
        assert "E102" not in content
        assert "E109_S002_0050_org_v001" in content
        assert "/shots/E109_S002_0050/plate/org/v001/hi/E109_S002_0050_org_v001" in content
        assert 'file_type "exr"' in content.replace("\\", "/")

    def test_plate_read_unquoted_file_and_percent04d(self):
        """따옴표 없는 ``file W:/...``·``%04d`` 저장 형식도 현재 샷 plate로 치환한다."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            " file W:/vfx/project_2026/SBS_030/04_sq/E102/E102_S001_0020/plate/org/v001/hi/"
            "E102_S001_0020_org_v001.%04d.exr\n"
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/shots/E109_S002_0050"),
            "plate_hi": Path("/shots/E109_S002_0050/plate/org/v001/hi"),
            "edit": Path("/shots/E109_S002_0050/edit"),
            "renders": Path("/shots/E109_S002_0050/renders"),
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
            content, _ = generate_nk_content(preset, "E109_S002_0050", paths, "v001")
        norm = content.replace("\\", "/")
        assert "E102" not in norm
        assert "E109_S002_0050_org_v001.####.exr" in norm
        assert "/shots/E109_S002_0050/plate/org/v001/hi/" in norm
        assert 'file_type "exr"' in norm

    def test_plate_read_mov_single_clip_repoints(self):
        """MOV 단일 클립 템플릿도 현재 샷·plate_hi로 맞추고 확장자는 mov 유지."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "Read {\n"
            " file_type exr\n"
            ' file "W:/other/E102/E102_S001_0020/plate/org/v001/hi/'
            'E102_S001_0020_org_v001.mov"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/shots/E109_S002_0050"),
            "plate_hi": Path("/shots/E109_S002_0050/plate/org/v001/hi"),
            "edit": Path("/shots/E109_S002_0050/edit"),
            "renders": Path("/shots/E109_S002_0050/renders"),
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
            content, _ = generate_nk_content(preset, "E109_S002_0050", paths, "v001")
        assert ".mov" in content
        assert "E109_S002_0050_org_v001.mov" in content
        assert "E102" not in content
        assert 'file_type "mov"' in content.replace("\\", "/")

    def test_plate_read_mov_folder_forces_mov_from_exr_template(self):
        """plate_hi가 v001/mov면 EXR 템플릿이어도 경로·파일명은 mov로 맞춘다."""
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "Read {\n"
            " file_type exr\n"
            ' file "W:/vfx/E102/E102_S001_0020/plate/org/v001/hi/'
            'E102_S001_0020_org_v001.1001.exr"\n'
            " name Read1\n"
            "}\n"
        )
        paths = {
            "shot_root": Path("/shots/E109_S002_0050"),
            "plate_hi": Path("/shots/E109_S002_0050/plate/org/v001/mov"),
            "edit": Path("/shots/E109_S002_0050/edit"),
            "renders": Path("/shots/E109_S002_0050/renders"),
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
            content, _ = generate_nk_content(preset, "E109_S002_0050", paths, "v001")
        norm = content.replace("\\", "/")
        assert "/plate/org/v001/mov/" in norm
        assert "E109_S002_0050_org_v001.mov" in norm
        assert "E102_S001_0020_org_v001.1001.exr" not in norm
        assert 'file_type "mov"' in norm


class TestReadFileTypeFromPlateBasename:
    def test_dpx_sequence(self):
        assert _read_file_type_from_plate_basename("foo.####.dpx") == "dpx"

    def test_exr_sequence(self):
        assert _read_file_type_from_plate_basename("bar.%04d.exr") == "exr"

    def test_tiff_sequence(self):
        assert _read_file_type_from_plate_basename("bar.####.tif") == "tiff"

    def test_tiff_long_ext(self):
        assert _read_file_type_from_plate_basename("bar.%04d.tiff") == "tiff"


class TestDiscoverPlateSequenceBasename:
    def test_tiebreak_prefers_shot_related_prefix(self, tmp_path):
        hi = tmp_path / "hi"
        hi.mkdir()
        for fr in (1001, 1002):
            (hi / f"ref_alt.{fr}.dpx").write_bytes(b"")
            (hi / f"S260_0515_org_v001.{fr}.dpx").write_bytes(b"")
        assert _discover_plate_sequence_basename(hi, "S260_0515") == "S260_0515_org_v001.####.dpx"

    def test_discovers_tiff_sequence(self, tmp_path):
        hi = tmp_path / "hi"
        hi.mkdir()
        for fr in (1001, 1002, 1003):
            (hi / f"shot_plate.{fr}.tif").write_bytes(b"")
        assert _discover_plate_sequence_basename(hi, "shot") == "shot_plate.####.tif"


class TestNormalizePlateBasename:
    def test_shot_prefix_exr_sequence(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_org_v001.1001.exr",
                "E109_S002_0050",
            )
            == "E109_S002_0050_org_v001.####.exr"
        )

    def test_shot_prefix_percent04d_exr(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_org_v001.%04d.exr",
                "E109_S002_0050",
            )
            == "E109_S002_0050_org_v001.####.exr"
        )

    def test_shot_prefix_mov_no_frame(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_org_v001.mov",
                "E109_S002_0050",
            )
            == "E109_S002_0050_org_v001.mov"
        )

    def test_shot_prefix_mov_with_frame(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_plate.1001.mov",
                "E109_S002_0050",
            )
            == "E109_S002_0050_plate.####.mov"
        )

    def test_no_shot_prefix_mov_not_forced_to_exr(self):
        assert _normalize_plate_basename("reference.mov", "E109_S002_0050") == (
            "E109_S002_0050_org_v001.mov"
        )

    def test_no_shot_prefix_exr(self):
        assert _normalize_plate_basename("foo.1001.exr", "E01_S01_0010") == (
            "E01_S01_0010_org_v001.####.exr"
        )

    def test_force_ext_mov_overrides_exr_template(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_org_v001.1001.exr",
                "E109_S002_0050",
                force_ext="mov",
            )
            == "E109_S002_0050_org_v001.mov"
        )

    def test_force_ext_exr_overrides_mov_template(self):
        assert (
            _normalize_plate_basename(
                "E102_S001_0020_org_v001.mov",
                "E109_S002_0050",
                force_ext="exr",
            )
            == "E109_S002_0050_org_v001.####.exr"
        )


class TestTemplateSamplePathWarnings:
    def test_detects_sample_root(self) -> None:
        from bpe.core import nk_generator as ng

        w = _template_sample_path_warnings(f'file "{ng._TEMPLATE_SAMPLE_SHOT_ROOT}/plate/x.exr"')
        assert len(w) >= 1

    def test_clean_body_empty(self) -> None:
        assert _template_sample_path_warnings("Read {\n name Read4\n}\n") == []


# ---------------------------------------------------------------------------
# Read_Edit patch helpers
# ---------------------------------------------------------------------------


class TestIsEditReadBlock:
    def test_detects_read_edit(self):
        inner = "\n inputs 0\n file_type exr\n file W:/edit/shot.####.exr\n name Read_Edit\n"
        assert _is_edit_read_block(inner) is True

    def test_ignores_read_plate(self):
        inner = "\n file W:/plate/shot.####.exr\n name Read_Plate\n"
        assert _is_edit_read_block(inner) is False

    def test_ignores_generic_read(self):
        inner = "\n file W:/edit/shot.####.exr\n name Read4\n"
        assert _is_edit_read_block(inner) is False


class TestDiscoverEditSequenceBasename:
    def test_finds_edit_exr(self, tmp_path):
        edit_dir = tmp_path / "edit"
        edit_dir.mkdir()
        (edit_dir / "E109_S002_0020_edit.1001.exr").write_bytes(b"")
        result = _discover_edit_sequence_basename(edit_dir, "E109_S002_0020")
        assert result == "E109_S002_0020_edit.####.exr"

    def test_finds_edit_mov(self, tmp_path):
        """CRS2 스타일: 소문자 샷명 + _edit_v001.mov"""
        edit_dir = tmp_path / "edit"
        edit_dir.mkdir()
        (edit_dir / "ep01_s01_c0010_edit_v001.mov").write_bytes(b"")
        result = _discover_edit_sequence_basename(edit_dir, "EP01_S01_C0010")
        assert result == "ep01_s01_c0010_edit_v001.mov"

    def test_prefers_shot_edit_mov_over_other(self, tmp_path):
        edit_dir = tmp_path / "edit"
        edit_dir.mkdir()
        (edit_dir / "ep01_s05_c0001_edit_v001.mov").write_bytes(b"")
        (edit_dir / "ep01_s01_c0010_edit_v001.mov").write_bytes(b"")
        result = _discover_edit_sequence_basename(edit_dir, "EP01_S01_C0010")
        assert result == "ep01_s01_c0010_edit_v001.mov"

    def test_missing_dir_returns_none(self, tmp_path):
        result = _discover_edit_sequence_basename(tmp_path / "nope", "E109_S002_0020")
        assert result is None

    def test_empty_dir_returns_none(self, tmp_path):
        edit_dir = tmp_path / "edit"
        edit_dir.mkdir()
        assert _discover_edit_sequence_basename(edit_dir, "E109_S002_0020") is None


class TestPatchReadEditFilePaths:
    """_patch_read_edit_file_paths: 템플릿 Read_Edit 경로 교체."""

    def _make_paths(self, tmp_path: Path, shot: str) -> dict:
        return {
            "shot_root": tmp_path / "shot",
            "plate_hi": tmp_path / "plate" / "org" / "v001" / "hi",
            "edit": tmp_path / "edit",
            "renders": tmp_path / "renders",
        }

    def test_replaces_bare_path_read_edit(self, tmp_path):
        """템플릿의 bare file 경로가 올바른 edit 경로로 교체된다."""
        shot = "E109_S002_0020"
        paths = self._make_paths(tmp_path, shot)
        sample_path = (
            "W:/vfx/project_2026/SBS_030/04_sq/E107"
            "/E107_S022_0080/edit/E107_S022_0080_edit.%04d.exr"
        )
        body = f"Read {{\n inputs 0\n file_type exr\n file {sample_path}\n name Read_Edit\n}}\n"
        result = _patch_read_edit_file_paths(body, shot, paths)
        edit_nk = str(paths["edit"]).replace("\\", "/")
        assert f"{edit_nk}/{shot}_edit.####.exr" in result

    def test_no_read_edit_is_noop(self, tmp_path):
        """Read_Edit 노드가 없으면 body가 변경되지 않는다."""
        shot = "E109_S002_0020"
        paths = self._make_paths(tmp_path, shot)
        body = "Read {\n file W:/plate/org/v001/hi/E107.####.exr\n name Read_Plate\n}\n"
        assert _patch_read_edit_file_paths(body, shot, paths) == body

    def test_uses_discovered_file_when_present(self, tmp_path):
        """edit 폴더에 실제 파일이 있으면 발견된 파일명을 사용한다."""
        shot = "E109_S002_0020"
        paths = self._make_paths(tmp_path, shot)
        edit_dir = Path(paths["edit"])
        edit_dir.mkdir(parents=True)
        (edit_dir / f"{shot}_edit.1001.exr").write_bytes(b"")
        body = (
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            f" file W:/old/edit/{shot}_edit.%04d.exr\n"
            " name Read_Edit\n"
            "}\n"
        )
        result = _patch_read_edit_file_paths(body, shot, paths)
        edit_nk = str(edit_dir).replace("\\", "/")
        assert f"{edit_nk}/{shot}_edit.####.exr" in result

    def test_replaces_script_guide_path_with_shot_edit_mov(self, tmp_path):
        """템플릿 가이드 MOV 경로 → 현재 컷 edit 폴더 MOV로 교체."""
        shot = "EP01_S01_C0010"
        paths = self._make_paths(tmp_path, shot)
        edit_dir = Path(paths["edit"])
        edit_dir.mkdir(parents=True)
        (edit_dir / "ep01_s01_c0010_edit_v001.mov").write_bytes(b"")
        guide_path = (
            "W:/vfx/project_2026/CRS2_032/03_prod/05_ref/script_guide/"
            "beluca/aces_1.2/edit/ep01_s05_c0001_edit_v001.mov"
        )
        body = f"Read {{\n inputs 0\n file_type mov\n file {guide_path}\n name Read_Edit\n}}\n"
        result = _patch_read_edit_file_paths(body, shot, paths)
        edit_nk = str(edit_dir).replace("\\", "/")
        assert guide_path not in result
        assert f"{edit_nk}/ep01_s01_c0010_edit_v001.mov" in result
        assert "file_type mov" in result or 'file_type "mov"' in result

    def test_plate_read_not_affected(self, tmp_path):
        """plate Read 노드는 건드리지 않는다."""
        shot = "E109_S002_0020"
        paths = self._make_paths(tmp_path, shot)
        plate_path = "W:/vfx/SBS_030/plate/org/v001/hi/E107.####.exr"
        body = (
            "Read {\n"
            f' file "{plate_path}"\n'
            " name Read_Plate\n"
            "}\n"
            "Read {\n"
            " file W:/old/edit/E107_S022_0080_edit.%04d.exr\n"
            " name Read_Edit\n"
            "}\n"
        )
        result = _patch_read_edit_file_paths(body, shot, paths)
        assert plate_path in result

    def test_generate_nk_content_patches_edit_path(self, tmp_path):
        """generate_nk_content 호출 시 Read_Edit 경로가 교체된다."""
        shot = "E109_S002_0020"
        plate_hi = tmp_path / "plate" / "org" / "v001" / "hi"
        plate_hi.mkdir(parents=True)
        edit_dir = tmp_path / "edit"
        paths = {
            "shot_root": tmp_path / "shot",
            "plate_hi": plate_hi,
            "edit": edit_dir,
            "renders": tmp_path / "renders",
        }
        sample_edit = (
            "W:/vfx/project_2026/SBS_030/04_sq/E107/E107_S022_0080/edit/"
            "E107_S022_0080_edit.%04d.exr"
        )
        plate_path = (
            "W:/vfx/project_2026/SBS_030/04_sq/E107/E107_S022_0080/plate/org/v001/hi/E107.####.exr"
        )
        template_body = (
            "set cut_paste_input [stack 0]\n"
            "version 14.1 v4\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            f" file {plate_path}\n"
            " name Read_Plate\n"
            "}\n"
            "Read {\n"
            " inputs 0\n"
            " file_type exr\n"
            f" file {sample_edit}\n"
            " name Read_Edit\n"
            "}\n"
        )
        preset = {
            "fps": "23.976",
            "plate_width": 1920,
            "plate_height": 1080,
            "project_code": "SBS_030",
        }
        with patch(
            "bpe.core.nk_generator.load_preset_template",
            return_value=template_body,
        ):
            content, _ = generate_nk_content(preset, shot, paths, "v001")
        edit_nk = str(edit_dir).replace("\\", "/")
        assert f"{edit_nk}/{shot}_edit.####.exr" in content
        assert "E107_S022_0080_edit" not in content

    def test_repoints_auto_named_edit_read_by_path(self, tmp_path):
        """edit Read 이름이 Read8 처럼 자동 이름이어도 /edit/ 경로면 교체된다."""
        shot = "EP01_S01_C0020"
        paths = self._make_paths(tmp_path, shot)
        edit_dir = Path(paths["edit"])
        edit_dir.mkdir(parents=True)
        (edit_dir / "ep01_s01_c0020_edit_v001.mov").write_bytes(b"")
        guide_path = (
            "W:/vfx/project_2026/CRS2_032/03_prod/05_ref/script_guide/"
            "beluca/aces_1.2/edit/ep01_s05_c0001_edit_v001.mov"
        )
        body = (
            "Read {\n"
            " inputs 0\n"
            " file_type mov\n"
            f" file {guide_path}\n"
            " colorspace rendering\n"
            " name Read8\n"
            "}\n"
        )
        result = _patch_read_edit_file_paths(body, shot, paths)
        edit_nk = str(edit_dir).replace("\\", "/")
        assert guide_path not in result
        assert f"{edit_nk}/ep01_s01_c0020_edit_v001.mov" in result
        # edit Read 의 colorspace 는 그대로 유지
        assert "colorspace rendering" in result


class TestPatchReadColorspaceSkipsEdit:
    """프로젝트별 edit 컬러스페이스 유지: edit Read 는 프리셋 CS 로 덮어쓰지 않는다."""

    def test_edit_read_colorspace_preserved_plate_changed(self):
        body = (
            "Read {\n"
            " file W:/proj/04_sq/ep01/EP01_S01_C0020/plate/org/v001/hi/x.####.exr\n"
            ' colorspace "ACES - ACEScg"\n'
            " name Read1\n"
            "}\n"
            "Read {\n"
            " file W:/proj/04_sq/ep01/EP01_S01_C0020/edit/x_edit_v001.mov\n"
            " colorspace rendering\n"
            " name Read8\n"
            "}\n"
        )
        out = _patch_read_colorspace(body, "ACES - ACES2065-1")
        # 플레이트는 프리셋 CS 로 변경
        assert '"ACES - ACES2065-1"' in out
        # edit 은 원본 유지
        assert "colorspace rendering" in out

    def test_edit_read_colorspace_preserved_different_value(self):
        """다른 프로젝트의 다른 edit CS 도 그대로 유지된다."""
        body = (
            "Read {\n"
            " file W:/p/edit/clip_edit_v001.mov\n"
            ' colorspace "Input - Sony - S-Log3 - S-Gamut3.Cine"\n'
            " name Read12\n"
            "}\n"
        )
        out = _patch_read_colorspace(body, "ACES - ACEScg")
        assert '"Input - Sony - S-Log3 - S-Gamut3.Cine"' in out
        assert "ACEScg" not in out


class TestIsEditReadFilePath:
    def test_edit_segment(self):
        assert _is_edit_read_file_path("W:/proj/04_sq/ep01/shot/edit/x_edit_v001.mov") is True

    def test_guide_edit_segment(self):
        assert (
            _is_edit_read_file_path(
                "W:/proj/03_prod/05_ref/script_guide/beluca/aces_1.2/edit/x_edit_v001.mov"
            )
            is True
        )

    def test_plate_path_false(self):
        assert _is_edit_read_file_path("W:/proj/shot/plate/org/v001/hi/x.####.exr") is False

    def test_backslash_path(self):
        assert _is_edit_read_file_path("W:\\proj\\shot\\edit\\x.mov") is True
