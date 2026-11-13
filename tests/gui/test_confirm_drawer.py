"""컨펌 창의 샷 목록 서랍 — 갈래·정렬·고르기 (ShotGrid 조회 없이 줄만 넣어 본다)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

try:
    from bpe.gui.confirm.shot_drawer import ShotDrawer
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("서랍을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)

from bpe.core.confirm_list import GROUP_INTERNAL, GROUP_VENDOR
from bpe.core.settings import get_confirm_settings


def _row(tid: int, shot: str, kind: str, when: str) -> Dict[str, Any]:
    return {
        "task_id": tid,
        "shot_code": shot,
        "task_status": "sv",
        "uploader_type": kind,
        "uploader_name": "업체 A" if kind == "Group" else "작업자",
        "latest_version_code": f"{shot}_comp_v002",
        "latest_version_created_at": when,
    }


@pytest.fixture
def drawer(qtbot: Any, tmp_app_dir: Path) -> Any:
    _ = tmp_app_dir
    d = ShotDrawer()
    qtbot.addWidget(d)
    d.set_rows(
        [
            _row(1, "S_0030", "Group", "2026-11-09"),
            _row(2, "S_0010", "Group", "2026-11-05"),
            _row(3, "S_0020", "HumanUser", "2026-11-07"),
        ]
    )
    return d


def test_vendor_group_is_default_and_oldest_first(drawer: Any) -> None:
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0010", "S_0030"]
    assert drawer.summary() == f"{GROUP_VENDOR} 2"


def test_group_choice_is_remembered(drawer: Any) -> None:
    drawer._set_group(GROUP_INTERNAL)
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0020"]
    assert drawer.summary() == f"{GROUP_INTERNAL} 1"
    assert get_confirm_settings()["list_group"] == GROUP_INTERNAL


def test_search_and_pick(drawer: Any) -> None:
    picked: List[Dict[str, Any]] = []
    drawer.task_picked.connect(picked.append)
    drawer._search.setText("0030")
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0030"]
    drawer._on_clicked(drawer._list.item(0))
    assert picked and picked[0]["task_id"] == 1


def test_summary_is_empty_before_first_load(qtbot: Any, tmp_app_dir: Path) -> None:
    _ = tmp_app_dir
    d = ShotDrawer()
    qtbot.addWidget(d)
    assert d.summary() == ""
