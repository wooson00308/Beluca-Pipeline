"""Tests for bpe.core.confirm_list — 컨펌 목록 갈래·찾기·정렬."""

from __future__ import annotations

from bpe.core.confirm_list import (
    GROUP_ALL,
    GROUP_INTERNAL,
    GROUP_TM,
    GROUP_VENDOR,
    SORT_NEW,
    SORT_OLD,
    SORT_SHOT,
    filter_rows,
    row_subtitle,
    sort_rows,
    vendor_names,
)

ROWS = [
    {
        "shot_code": "ep01_s010_0030",
        "task_status": "sv",
        "uploader_type": "Group",
        "uploader_name": "업체 A",
        "latest_version_code": "ep01_s010_0030_comp_v004",
        "latest_version_created_at": "2026-11-10 10:00:00",
    },
    {
        "shot_code": "ep01_s010_0010",
        "task_status": "sv",
        "uploader_type": "Group",
        "uploader_name": "업체 B",
        "latest_version_code": "ep01_s010_0010_comp_v002",
        "latest_version_created_at": "2026-11-12 09:00:00",
    },
    {
        "shot_code": "ep01_s020_0010",
        "task_status": "tm",
        "uploader_type": "HumanUser",
        "uploader_name": "작업자",
        "latest_version_code": "ep01_s020_0010_comp_v005",
        "latest_version_created_at": "2026-11-11 09:00:00",
    },
    {
        "shot_code": "ep01_s040_0010",
        "task_status": "sv",
        "uploader_type": "",
        "uploader_name": "",
        "latest_version_code": "",
        "latest_version_created_at": None,
    },
]


def _codes(rows: list) -> list:
    return [r["shot_code"] for r in rows]


def test_vendor_and_internal_split_by_uploader_type() -> None:
    assert _codes(filter_rows(ROWS, GROUP_VENDOR)) == ["ep01_s010_0030", "ep01_s010_0010"]
    # 올린 쪽을 모르면 내부로 본다. tm 상태는 SV_Confirm 갈래에 들지 않는다
    assert _codes(filter_rows(ROWS, GROUP_INTERNAL)) == ["ep01_s040_0010"]


def test_tm_and_sv_by_status() -> None:
    assert _codes(filter_rows(ROWS, GROUP_TM)) == ["ep01_s020_0010"]
    assert len(filter_rows(ROWS, GROUP_ALL)) == len(ROWS)


def test_vendor_pick_and_search() -> None:
    assert vendor_names(ROWS) == ["업체 A", "업체 B"]
    assert _codes(filter_rows(ROWS, GROUP_VENDOR, vendor="업체 B")) == ["ep01_s010_0010"]
    assert _codes(filter_rows(ROWS, GROUP_VENDOR, search="0030")) == ["ep01_s010_0030"]
    assert filter_rows(ROWS, GROUP_VENDOR, search="없는 샷") == []


def test_sorting() -> None:
    assert _codes(sort_rows(ROWS, SORT_OLD))[0] == "ep01_s010_0030"  # 가장 오래된 것이 위
    assert _codes(sort_rows(ROWS, SORT_OLD))[-1] == "ep01_s040_0010"  # 날짜 없는 것은 맨 아래
    assert _codes(sort_rows(ROWS[:3], SORT_NEW))[0] == "ep01_s010_0010"
    assert _codes(sort_rows(ROWS, SORT_SHOT))[0] == "ep01_s010_0010"


def test_row_subtitle() -> None:
    assert row_subtitle(ROWS[0]) == "v004 · 업체 A · 2026-11-10"
    assert row_subtitle(ROWS[3]) == ""


def test_internal_comes_first_and_cgi_confirm_has_its_own_group() -> None:
    from bpe.core.confirm_list import GROUP_CGI, GROUPS, LIST_STATUSES

    assert GROUPS[0] == GROUP_INTERNAL  # 내부가 맨 위
    assert GROUPS == (GROUP_INTERNAL, GROUP_VENDOR, GROUP_CGI, GROUP_TM, GROUP_ALL)
    assert "cgi" in LIST_STATUSES
    rows = ROWS + [
        {"shot_code": "ep01_s050_0010", "task_status": "cgi", "uploader_type": "HumanUser"}
    ]
    assert _codes(filter_rows(rows, GROUP_CGI)) == ["ep01_s050_0010"]
    # cgi 상태 샷은 SV·TM 갈래에 섞이지 않고, total 에는 들어간다
    assert "ep01_s050_0010" not in _codes(filter_rows(rows, GROUP_INTERNAL))
    assert "ep01_s050_0010" not in _codes(filter_rows(rows, GROUP_TM))
    assert "ep01_s050_0010" in _codes(filter_rows(rows, GROUP_ALL))


def test_annotation_rows_are_grouped_one_line_per_shot() -> None:
    from bpe.core.confirm_list import annotation_subtitle, group_rows_by_shot

    a = {"type": "HumanUser", "id": 3, "name": "작업자"}
    b = {"type": "Group", "id": 9, "name": "업체"}
    rows = [
        {
            "task_id": 12,
            "shot_id": 2,
            "shot_code": "ep01_s020_0010",
            "task_content": "comp",
            "task_status": "assign",
            "task_assignees": [a],
        },
        {
            "task_id": 11,
            "shot_id": 1,
            "shot_code": "ep01_s010_0010",
            "task_content": "roto",
            "task_status": "wtg",
            "task_assignees": [],
        },
        {
            "task_id": 10,
            "shot_id": 1,
            "shot_code": "ep01_s010_0010",
            "task_content": "comp",
            "task_status": "assign",
            "task_assignees": [a, b],
        },
        {
            "task_id": 13,
            "shot_id": 1,
            "shot_code": "ep01_s010_0010",
            "task_content": "matte",
            "task_status": "assign",
            "task_assignees": [a],
        },
        {
            "task_id": 14,
            "shot_id": None,
            "shot_code": "",
            "task_content": "x",
            "task_status": "wtg",
        },
    ]
    out = group_rows_by_shot(rows)
    assert [r["shot_code"] for r in out] == [
        "ep01_s010_0010",
        "ep01_s020_0010",
    ]  # 샷 이름 순, 샷당 한 줄
    first = out[0]
    assert [t["task_id"] for t in first["tasks"]] == [10, 11, 13]
    assert first["task_id"] == 10 and first["task_statuses"] == ["assign", "wtg"]
    assert first["task_assignees"] == [a, b]  # 담당은 겹치지 않게 모두
    assert annotation_subtitle(first) == "comp assign · roto wtg · matte assign"
    assert rows[1]["task_assignees"] == []  # 받은 목록은 그대로 둔다


def test_annotation_filter_by_search_and_shot_ids() -> None:
    from bpe.core.confirm_list import (
        annotation_status_text,
        filter_annotation_rows,
        group_rows_by_shot,
    )

    who = {"type": "HumanUser", "id": 3, "name": "김작업"}
    rows = group_rows_by_shot(
        [
            {
                "task_id": 1,
                "shot_id": 2,
                "shot_code": "ep01_s020_0010",
                "task_content": "comp",
                "task_status": "assign",
                "task_assignees": [who],
            },
            {
                "task_id": 2,
                "shot_id": 1,
                "shot_code": "ep01_s010_0010",
                "task_content": "roto",
                "task_status": "wtg",
                "task_assignees": [],
            },
            {
                "task_id": 3,
                "shot_id": 1,
                "shot_code": "ep01_s010_0010",
                "task_content": "comp",
                "task_status": "assign",
                "task_assignees": [],
            },
        ]  # fmt: skip
    )
    assert [r["shot_code"] for r in filter_annotation_rows(rows)] == [
        "ep01_s010_0010",
        "ep01_s020_0010",
    ]
    assert [r["shot_id"] for r in filter_annotation_rows(rows, search="s020")] == [2]
    assert [r["shot_id"] for r in filter_annotation_rows(rows, search="김작업")] == [2]
    assert [r["shot_id"] for r in filter_annotation_rows(rows, search="ROTO")] == [1]
    assert [r["shot_id"] for r in filter_annotation_rows(rows, shot_ids={1})] == [1]
    assert filter_annotation_rows(rows, shot_ids=set()) == []
    assert annotation_status_text(rows[0]) == "wtg · assign"
