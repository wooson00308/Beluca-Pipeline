"""샷의 글 칸에 적용할 글 다루기 — 불러온 글을 고친 그대로 적용한다."""

from __future__ import annotations

from bpe.core.confirm_shot_text import (
    KIND_DESCRIPTION,
    KIND_LABELS,
    KIND_ROW_KEYS,
    KIND_WORK_ORDER,
    KINDS,
    WORK_ORDER_CHIPS,
    clean_text,
    has_line,
    same_text,
    toggle_line,
)

NL = chr(10)


def test_clean_text_trims_edges_only() -> None:
    raw = NL + "  " + NL + "리무브  " + chr(13) + NL + NL + "AI 병사연장 " + NL + NL
    assert clean_text(raw) == "리무브" + NL + NL + "AI 병사연장"
    assert clean_text("") == "" and clean_text(None) == ""  # type: ignore[arg-type]


def test_same_text_ignores_line_endings_and_edge_blanks() -> None:
    old = "2D 합성" + NL + "260928 - omit"
    assert same_text(old, old + NL + "  ")
    assert same_text(old, "2D 합성" + chr(13) + NL + "260928 - omit")
    assert same_text("", "  " + NL) and same_text(None, "")  # type: ignore[arg-type]
    assert not same_text(old, old + NL + "AI")
    assert not same_text(old, "2D 합성")
    assert not same_text(old, "2d 합성" + NL + "260928 - omit")  # 글자가 다르면 다른 글


def test_chip_toggles_its_line_in_the_loaded_text() -> None:
    text = toggle_line("", "AI")
    assert text == "AI" and has_line(text, "AI")
    text = toggle_line(text, "2D 합성")
    assert text == "AI" + NL + "2D 합성"
    # 이미 적혀 있던 글에 단추를 누르면 그 뒤에 한 줄이 붙는다
    loaded = "리무브" + NL + "260928 - omit"
    assert toggle_line(loaded, "AI") == loaded + NL + "AI"
    # 이미 적혀 있던 줄의 단추를 누르면 그 줄이 빠진다
    assert has_line(loaded, "리무브")
    assert toggle_line(loaded, "리무브") == "260928 - omit"
    # 단추 뒤에 내용을 이어 쓴 줄은 다른 줄이다 — 단추를 또 누르면 새 줄이 생긴다
    typed = "AI 병사연장" + NL + "2D 합성"
    assert not has_line(typed, "AI")
    assert toggle_line(typed, "AI") == typed + NL + "AI"
    assert toggle_line("AI", "AI") == ""
    assert toggle_line("AI", "  ") == "AI"


def test_chips_and_labels() -> None:
    assert len(set(WORK_ORDER_CHIPS)) == len(WORK_ORDER_CHIPS)
    for word in ("리무브", "2D 합성", "AI", "ENV", "CROWD", "MATTE", "SIM", "COMP", "FX"):
        assert word in WORK_ORDER_CHIPS
    assert KIND_LABELS[KIND_WORK_ORDER] == "워크오더"
    assert KIND_LABELS[KIND_DESCRIPTION] == "디스크립션"
    assert KINDS == (KIND_WORK_ORDER, KIND_DESCRIPTION)
    assert KIND_ROW_KEYS == {
        KIND_WORK_ORDER: "vfx_work_order",
        KIND_DESCRIPTION: "shot_description",
    }
