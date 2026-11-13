"""Tests for bpe.core.confirm_standard — 프리셋 고르기와 가지가 있는 누크 틀의 MOV 크기."""

from __future__ import annotations

from bpe.core.confirm_standard import is_ai_shot, mov_sizes_from_template, pick_preset

_NAMES = ["PROJ_001_AI_GAMMA", "PROJ_001_AI_REC709", "PROJ_001_GAMMA", "PROJ_001_REC709"]


def test_ai_tag_decides_ai_shot() -> None:
    assert is_ai_shot(["ai"]) is True
    assert is_ai_shot(["뷰티", "AI"]) is True
    assert is_ai_shot(["뷰티"]) is False
    assert is_ai_shot([]) is False
    assert is_ai_shot(None) is None  # 태그를 못 읽었으면 모름


def test_plate_colour_and_ai_tag_pick_one_preset() -> None:
    assert pick_preset(_NAMES, plate_color="REC709", is_ai=False) == ("PROJ_001_REC709", True)
    assert pick_preset(_NAMES, plate_color="GAMMA", is_ai=True) == ("PROJ_001_AI_GAMMA", True)
    assert pick_preset(_NAMES, plate_color="GAMMA", is_ai=False) == ("PROJ_001_GAMMA", True)


def test_missing_information_leaves_it_undecided() -> None:
    name, decided = pick_preset(_NAMES, plate_color="REC709", is_ai=None)
    assert not decided and name == "PROJ_001_REC709"  # 색은 맞추고, AI 는 몰라 일반을 먼저
    name, decided = pick_preset(_NAMES, plate_color=None, is_ai=True)
    assert not decided and "_AI_" in name
    assert pick_preset(_NAMES)[1] is False
    assert pick_preset([]) == ("", False)


def test_single_preset_is_always_decided() -> None:
    assert pick_preset(["SBS_030"], plate_color="REC709", is_ai=True) == ("SBS_030", True)


def test_unknown_colour_name_does_not_empty_the_choice() -> None:
    name, decided = pick_preset(["A_REC709", "A_GAMMA"], plate_color="PQ")
    assert name in ("A_REC709", "A_GAMMA") and not decided


# ── 가지(set / push)가 있는 틀 ────────────────────────────────────

_BRANCHED = """Root {
 format "3840 2160 0 0 3840 2160 1 UHD"
}
Read {
 file_type mov
 name Read1
}
set Nplate [stack 0]
push $Nplate
Reformat {
 type "to box"
 box_width 3840
 box_height 2160
 name Reformat1
}
set Nfull [stack 0]
Grade {
 name Grade1
}
set Ngraded [stack 0]
push $Nplate
push $Ngraded
Write {
 file_type mov
 name WriteMov
}
push $Nplate
Write {
 file_type mov
 name WriteRaw
}
"""


def test_size_follows_set_and_push_to_the_mov_write() -> None:
    # Reformat → (set) → Grade → (set) … push → Write(mov): 크기는 Reformat 것
    assert mov_sizes_from_template(_BRANCHED) == [(3840, 2160)]


def test_read_starts_a_new_picture_of_unknown_size() -> None:
    text = (
        "Reformat {\n box_width 1920\n box_height 1080\n}\n"
        "Read {\n name R\n}\n"
        "Write {\n file_type mov\n}\n"
    )
    assert mov_sizes_from_template(text) == []


def test_two_mov_outputs_give_two_sizes() -> None:
    text = (
        "Read {\n name R\n}\nset N1 [stack 0]\n"
        "Reformat {\n box_width 3840\n box_height 2160\n}\nWrite {\n file_type mov\n}\n"
        "push $N1\n"
        "Reformat {\n box_width 1920\n box_height 1080\n}\nWrite {\n file_type mov\n}\n"
    )
    assert mov_sizes_from_template(text) == [(3840, 2160), (1920, 1080)]
