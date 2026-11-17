"""guide 봇에 맞추는 규칙 — 그림 이름, 영상 파일에 맞는 버전 고르기, 노트가 붙는 버전."""

from __future__ import annotations

from pathlib import Path

from bpe.core.confirm_annotations import SOURCE_EDIT, SOURCE_PLATE
from bpe.core.confirm_guide_note import (
    annot_file_name,
    annot_file_names,
    match_version,
    pick_note_version,
    stage_annot_files,
)

EDIT = {"id": 30, "code": "ep06_s017_0170_edit_v003", "task": "edit"}
EDIT_OLD = {"id": 20, "code": "ep06_s017_0170_edit_v002", "task": "edit"}
PLATE = {"id": 40, "code": "ep06_s017_0170_org_v004", "task": "org"}
ROWS = [PLATE, EDIT, EDIT_OLD]  # 최근 것이 앞


def test_annot_names_look_like_shotgrid_and_never_collide() -> None:
    assert annot_file_name(157097, 12) == "annot_version_157097.12.png"
    assert annot_file_name(5, -3) == "annot_version_5.0.png"
    # 같은 순번이 두 번 오면(edit 과 원본의 같은 자리) 뒤 것이 다음 빈 번호
    assert annot_file_names(9, [0, 0, 1, 7]) == [
        "annot_version_9.0.png",
        "annot_version_9.1.png",
        "annot_version_9.2.png",
        "annot_version_9.7.png",
    ]


def test_match_version_prefers_the_opened_file_then_the_latest() -> None:
    # 파일 이름과 같은 버전(대소문자는 가리지 않는다)
    assert match_version(ROWS, "edit", "EP06_s017_0170_edit_v002") == EDIT_OLD
    # 같은 이름이 없으면 그 태스크의 가장 최근 버전
    assert match_version(ROWS, "edit", "ep06_s017_0170_edit_v009") == EDIT
    assert match_version(ROWS, "edit") == EDIT
    assert match_version(ROWS, "org", "anything") == PLATE
    assert match_version([EDIT], "org", "ep06_s017_0170_org_v004") is None
    assert match_version([], "edit") is None


def test_note_goes_to_the_version_of_the_video_it_was_drawn_on() -> None:
    both = {SOURCE_EDIT: EDIT, SOURCE_PLATE: PLATE}
    only_edit = {SOURCE_EDIT: EDIT, SOURCE_PLATE: None}
    # edit 에 그리면 edit, 원본에 그리고 org 버전이 있으면 org
    assert pick_note_version(["edit"], "org", both) == ("edit", EDIT)
    assert pick_note_version(["org"], "edit", both) == ("org", PLATE)
    # 원본에 그렸는데 샷그리드에 org 버전이 없으면 edit 버전
    assert pick_note_version(["org"], "org", only_edit) == ("edit", EDIT)
    # 두 영상에 다 그렸으면 노트 하나로 edit 버전
    assert pick_note_version(["org", "edit"], "org", both) == ("edit", EDIT)
    # 그림 없이 글만 — 지금 보는 영상
    assert pick_note_version([], "edit", both) == ("edit", EDIT)
    assert pick_note_version([], "org", both) == ("org", PLATE)
    assert pick_note_version([], "", both) == ("org", PLATE)
    # edit 버전이 없고 org 만 있으면 org, 둘 다 없으면 붙일 곳이 없다
    assert pick_note_version(["edit"], "edit", {SOURCE_EDIT: None, SOURCE_PLATE: PLATE}) == (
        "org",
        PLATE,
    )
    assert pick_note_version(["edit"], "edit", {}) == ("", None)


def test_stage_copies_pictures_under_shotgrid_names(tmp_path: Path) -> None:
    a, b = tmp_path / "bpe_confirm_1001_x.png", tmp_path / "bpe_confirm_1012_y.png"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    out = stage_annot_files([(str(a), 0), (str(b), 11)], 321, tmp_path / "staged")
    assert [Path(p).name for p in out] == ["annot_version_321.0.png", "annot_version_321.11.png"]
    assert Path(out[0]).read_bytes() == b"A" and Path(out[1]).read_bytes() == b"B"
    assert a.is_file() and b.is_file()  # 원래 파일은 그대로
    assert stage_annot_files([], 321, tmp_path / "empty") == []
