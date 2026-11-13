"""Tests for bpe.core.confirm_list — 컨펌 목록 갈래·찾기·정렬."""

from __future__ import annotations

from bpe.core.confirm_list import (
    GROUP_INTERNAL,
    GROUP_SV,
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
    # 올린 쪽을 모르면 내부로 본다
    assert _codes(filter_rows(ROWS, GROUP_INTERNAL)) == ["ep01_s020_0010", "ep01_s040_0010"]


def test_tm_and_sv_by_status() -> None:
    assert _codes(filter_rows(ROWS, GROUP_TM)) == ["ep01_s020_0010"]
    assert len(filter_rows(ROWS, GROUP_SV)) == 3


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
