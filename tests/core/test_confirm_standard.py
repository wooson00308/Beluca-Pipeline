"""Tests for bpe.core.confirm_standard — 프리셋에서 컨펌 기준 읽기 (읽기 전용)."""

from __future__ import annotations

import json
from pathlib import Path

import bpe.core.confirm_standard as cs
from bpe.core.confirm_standard import (
    build_standard,
    load_standard,
    mov_size_from_template,
    preset_names_for,
    read_presets,
)

_PRESET = {
    "fps": "23.976",
    "mov_fps": "",
    "plate_width": "3840",
    "plate_height": "2076",
    "mov_codec": "appr",
    "mov_display": "ACES",
    "mov_view": "Rec.709",
    "viewer_process": "Rec.709 (ACES)",
}

_TEMPLATE = """Root {
 format "3840 2076 0 0 3840 2076 1 plate"
}
Read {
 file_type exr
 format "3840 2076 0 0 3840 2076 1 plate"
 name Read1
}
set N1 [stack 0]
Reformat {
 type "to box"
 box_width 1920
 box_height 1080
 box_fixed true
 name Reformat2
}
OCIODisplay {
 display ACES
 view Rec.709
 name OCIODisplay1
}
Write {
 file_type mov
 mov64_codec appr
 mov64_pixel_format {{0} "yuv420p\tYCbCr 4:2:0 8-bit"}
 name Write2
}
push $N1
Reformat {
 type "to box"
 box_width 3840
 box_height 2076
 name Reformat1
}
Write {
 file_type exr
 name Write1
}
"""


def test_mov_size_comes_from_the_reformat_feeding_the_mov_write() -> None:
    assert mov_size_from_template(_TEMPLATE) == (1920, 1080)


def test_mov_size_ignores_a_reformat_on_another_branch() -> None:
    text = (
        "Reformat {\n box_width 3840\n box_height 2076\n name R\n}\n"
        "Write {\n file_type exr\n name W1\n}\n"
        "push $N1\n"
        "Write {\n file_type mov\n name W2\n}\n"
    )
    assert mov_size_from_template(text) is None
    assert mov_size_from_template("") is None


def test_mov_size_reads_a_named_format() -> None:
    text = 'Reformat {\n format "2048 1080 0 0 2048 1080 1 2K_DCP"\n}\nWrite {\n file_type mov\n}\n'
    assert mov_size_from_template(text) == (2048, 1080)


def test_build_standard_from_preset_and_template() -> None:
    s = build_standard("PROJ_001", _PRESET, _TEMPLATE)
    assert s.preset == "PROJ_001"
    assert s.fps == 23.976
    assert s.mov_sizes == ((1920, 1080),) and s.plate_size == (3840, 2076)
    assert s.codec == "prores" and s.codec_title == "ProRes"
    assert s.look == "ACES / Rec.709" and s.color_tags == ("bt709",)
    assert s.viewer == "Rec.709 (ACES)"


def test_build_standard_leaves_unknowns_empty() -> None:
    s = build_standard("X", {"fps": "", "mov_codec": "zzzz", "mov_view": ""})
    assert s.fps is None and s.mov_sizes == () and s.plate_size is None
    assert s.codec == "" and s.look == "" and s.color_tags == ()


def test_mov_fps_wins_over_project_fps() -> None:
    assert build_standard("X", {"fps": "23.976", "mov_fps": "24"}).fps == 24.0


def test_preset_names_by_code_then_by_folder_name() -> None:
    presets = {"PROJ_001": {}, "PROJ_001_AI": {}, "OTHER_002": {}}
    assert preset_names_for(presets, "proj_001") == ["PROJ_001", "PROJ_001_AI"]
    parts = ("W:", "vfx", "OTHER_002", "04_sq", "E101", "E101_S001_0010")
    assert preset_names_for(presets, "", parts) == ["OTHER_002"]
    assert preset_names_for(presets, "", ("a", "b")) == []


def test_reading_presets_creates_nothing(tmp_app_dir: Path) -> None:
    before = sorted(p.name for p in tmp_app_dir.rglob("*"))
    assert read_presets() == {}
    assert load_standard("PROJ_001") is None
    assert cs.read_template("PROJ_001") == ""
    assert sorted(p.name for p in tmp_app_dir.rglob("*")) == before  # 아무것도 만들지 않는다


def test_load_standard_reads_preset_and_template(tmp_app_dir: Path) -> None:
    (tmp_app_dir / "presets.json").write_text(json.dumps({"PROJ_001": _PRESET}), encoding="utf-8")
    (tmp_app_dir / "PROJ_001_template.nk").write_text(_TEMPLATE, encoding="utf-8")
    s = load_standard("PROJ_001")
    assert s is not None and s.mov_sizes == ((1920, 1080),) and s.fps == 23.976


def test_lut_path_is_read_from_the_template_lut_node() -> None:
    from bpe.core.confirm_standard import lut_path_from_template

    vf = (
        "Read {\n file W:/plate/a.mov\n name Read1\n}\n"
        "Vectorfield {\n vfield_file //srv/lut/ARRI_LogC3-to-Rec709.cube\n"
        " file_type cube\n colorspaceIn rec709\n name VIEWER_INPUT\n}\n"
    )
    assert lut_path_from_template(vf) == "//srv/lut/ARRI_LogC3-to-Rec709.cube"
    ocio = 'OCIOFileTransform {\n file "W:/ref/my lut/Slog3 to s709.cube"\n name O1\n}\n'
    assert lut_path_from_template(ocio) == "W:/ref/my lut/Slog3 to s709.cube"
    # 식이 든 경로·.cube 가 아닌 것·룩업 노드가 아닌 곳의 경로는 쓰지 않는다
    expr = "Vectorfield {\n vfield_file [value root.lut].cube\n name V\n}\n"
    assert lut_path_from_template(expr) == ""
    assert lut_path_from_template("Read {\n file W:/x/y.cube\n name R\n}\n") == ""
    assert lut_path_from_template("Vectorfield {\n vfield_file W:/x/y.3dl\n name V\n}\n") == ""
    assert lut_path_from_template("") == ""
