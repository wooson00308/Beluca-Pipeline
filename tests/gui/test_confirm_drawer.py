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


def test_internal_group_is_default_and_vendor_lists_oldest_first(drawer: Any) -> None:
    # 처음에는 맨 위 갈래인 내부가 보인다
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0020"]
    assert drawer.summary() == f"{GROUP_INTERNAL} 1"
    assert drawer._group_box.itemText(0) == GROUP_INTERNAL
    drawer._set_group(GROUP_VENDOR)
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
    drawer._set_group(GROUP_VENDOR)
    drawer._search.setText("0030")
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0030"]
    drawer._on_clicked(drawer._list.item(0))
    assert picked and picked[0]["task_id"] == 1


def test_summary_is_empty_before_first_load(qtbot: Any, tmp_app_dir: Path) -> None:
    _ = tmp_app_dir
    d = ShotDrawer()
    qtbot.addWidget(d)
    assert d.summary() == ""


def test_rows_show_thumbnails_as_they_arrive(drawer: Any, qapp: Any) -> None:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QPixmap

    _ = qapp
    pm = QPixmap(160, 90)
    pm.fill(QColor("#336699"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    row = drawer.shown_rows()[0]
    key = drawer._thumb_key(row)
    assert key in drawer._thumb_labels and key not in drawer._thumbs
    drawer._on_thumb(key, bytes(buf.data()))
    assert key in drawer._thumbs and key not in drawer._thumb_labels
    assert (drawer._thumbs[key].width(), drawer._thumbs[key].height()) == (80, 45)
    drawer._on_thumb(("nope", None), b"not an image")  # 깨진 그림은 조용히 버린다
    drawer._refill()  # 다시 그려도 받은 그림은 그대로 쓴다
    assert key in drawer._thumbs and key not in drawer._thumb_labels


def test_no_thumbnail_download_without_an_address(drawer: Any) -> None:
    assert drawer._thumb_workers == []  # 시험 줄에는 그림 주소가 없다 — 내려받기를 시작하지 않는다
    assert drawer._thumb_url({"latest_version_image": "a", "shot_image": "b"}) == "a"
    assert drawer._thumb_url({"shot_image": "b"}) == "b"


def _anno_rows() -> List[Dict[str, Any]]:
    from bpe.core.confirm_list import group_rows_by_shot

    who = {"type": "HumanUser", "id": 3, "name": "김작업"}
    return group_rows_by_shot(
        [
            {
                "task_id": 11,
                "shot_id": 2,
                "shot_code": "S_0020",
                "task_content": "comp",
                "task_status": "assign",
                "task_assignees": [who],
            },
            {
                "task_id": 12,
                "shot_id": 1,
                "shot_code": "S_0010",
                "task_content": "roto",
                "task_status": "wtg",
                "task_assignees": [],
            },
            {
                "task_id": 13,
                "shot_id": 1,
                "shot_code": "S_0010",
                "task_content": "comp",
                "task_status": "assign",
                "task_assignees": [],
            },
        ]  # fmt: skip
    )


def test_annotation_mode_lists_shots_and_filters(drawer: Any) -> None:
    from bpe.core.confirm_list import MODE_ANNOTATION, MODE_CONFIRM
    from bpe.core.shot_filter_logic import ShotFacetField

    drawer.set_mode(MODE_ANNOTATION)
    assert drawer.mode() == MODE_ANNOTATION
    assert drawer.summary() == ""  # 아직 안 읽음
    assert drawer.shown_rows() == []
    # 갈래·업체·정렬 칸은 숨고, 필터 버튼이 보인다
    assert not drawer._group_box.isVisibleTo(drawer) and not drawer._vendor.isVisibleTo(drawer)
    assert not drawer._sort_box.isVisibleTo(drawer)
    assert drawer._mode_title.isVisibleTo(drawer) and drawer._facet_btn.isVisibleTo(drawer)

    drawer.set_rows(_anno_rows())
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0010", "S_0020"]  # 샷 이름 순
    assert drawer.summary() == "Annotation 2"
    assert drawer._count.text() == "2샷"
    html = drawer._row_html(drawer.shown_rows()[0])
    assert "roto wtg" in html and "comp assign" in html and "wtg · assign" in html

    drawer._search.setText("김작업")
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0020"]
    drawer._search.setText("")

    # 내 작업 탭과 같은 필터: 고르면 그 샷만 남는다
    assert not drawer._facet_btn.isEnabled()
    field = ShotFacetField(field_name="sg_sequence", display_label="시퀀스", data_type="text")
    drawer.set_facets([field], [{"id": 1, "sg_sequence": "S10"}, {"id": 2, "sg_sequence": "S20"}])
    assert drawer._facet_btn.isEnabled()
    drawer.set_facet_selection({"sg_sequence": {"S20"}})
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0020"]
    assert "필터 1" in drawer._facet_btn.text()
    drawer.set_facet_selection({})
    assert len(drawer.shown_rows()) == 2

    # Confirm 으로 돌아가면 읽어 둔 확인 대기 목록이 그대로 나온다
    drawer.set_mode(MODE_CONFIRM)
    assert drawer._group_box.isVisibleTo(drawer) and not drawer._facet_btn.isVisibleTo(drawer)
    assert [r["shot_code"] for r in drawer.shown_rows()] == ["S_0020"]
    drawer.set_mode(MODE_ANNOTATION)
    assert drawer.summary() == "Annotation 2"


def test_sequence_pick_mode_marks_rows_instead_of_opening(drawer: Any) -> None:
    from bpe.core.confirm_list import GROUP_ALL, MODE_ANNOTATION

    drawer._set_group(GROUP_ALL)
    opened: List[Any] = []
    asked: List[Any] = []
    drawer.task_picked.connect(opened.append)
    drawer.sequence_requested.connect(asked.append)
    assert not drawer._seq_play.isVisibleTo(drawer)

    drawer._seq_btn.setChecked(True)
    assert drawer._seq_play.isVisibleTo(drawer) and not drawer._seq_play.isEnabled()
    items = [drawer._list.item(i) for i in range(drawer._list.count())]
    by_shot = {it.data(0x0100)["shot_code"]: it for it in items}
    drawer._on_clicked(by_shot["S_0030"])
    assert opened == [] and not drawer._seq_play.isEnabled()  # 한 컷으로는 못 튼다
    drawer._on_clicked(by_shot["S_0010"])
    assert drawer._seq_play.isEnabled() and drawer._seq_play.text() == "2컷 이어 재생"
    # 고른 순서와 상관없이 샷 이름 순으로 보낸다
    assert [r["shot_code"] for r in drawer.sequence_picks()] == ["S_0010", "S_0030"]
    drawer._seq_play.click()
    assert [r["shot_code"] for r in asked[0]] == ["S_0010", "S_0030"]

    # 다시 누르면 빠진다. 줄을 다시 그려도 목록은 그대로다
    drawer._on_clicked(drawer._list.item(0))
    assert len(drawer.sequence_picks()) == 1 and drawer._list.count() == 3
    drawer.clear_sequence_picks()
    assert drawer.sequence_picks() == [] and not drawer._seq_clear.isVisibleTo(drawer)

    # 끄면 다시 누를 때 샷이 열린다. Annotation 모드에서는 이어 보기 줄이 숨는다
    drawer._seq_btn.setChecked(False)
    drawer._on_clicked(drawer._list.item(0))
    assert len(opened) == 1
    drawer._seq_btn.setChecked(True)
    drawer.set_mode(MODE_ANNOTATION)
    assert not drawer._seq_band.isVisibleTo(drawer) and not drawer._seq_pick


# ── 2026-11-16 추가: 보낸 줄은 다시 조회하지 않아도 바로 「보냄」으로 보인다 ───────────────


def test_sent_row_is_marked_at_once_and_stays_in_place(drawer: Any) -> None:
    from bpe.core.confirm_list import MODE_ANNOTATION

    def html_of(task_id: int) -> str:
        return drawer._row_html(next(r for r in drawer._rows if r["task_id"] == task_id))

    drawer._set_group(GROUP_VENDOR)
    before = [r["shot_code"] for r in drawer.shown_rows()]
    assert "보냄" not in html_of(1)
    assert drawer.mark_sent(1, "retake") == 1
    assert [r["shot_code"] for r in drawer.shown_rows()] == before  # 줄이 사라지지 않는다
    assert drawer._list.count() == len(before)
    row = next(r for r in drawer.shown_rows() if r["task_id"] == 1)
    assert "보냄" in html_of(1) and "retake" in html_of(1)
    assert row["task_status"] == "sv"  # 원래 상태는 그대로 — 갈래·필터가 흔들리지 않는다
    assert drawer.sent_status_of(1) == "retake" and drawer.sent_status_of(2) == ""
    assert "보냄" not in html_of(2)

    # Note 만 보낸 줄은 상태 글은 그대로이고 「보냄」만 붙는다
    assert drawer.mark_sent(2) == 1
    assert "보냄" in html_of(2) and "sv" in html_of(2) and drawer.sent_status_of(2) == ""
    # 목록에 없는 태스크는 아무 일도 없다
    assert drawer.mark_sent(99, "retake") == 0 and drawer.mark_sent(None) == 0

    # 갈래를 바꿨다 돌아와도 표시가 남고, 다시 조회해 새 줄이 오면 사라진다
    drawer._set_group(GROUP_INTERNAL)
    drawer._set_group(GROUP_VENDOR)
    assert "보냄" in html_of(1)
    drawer.set_rows([_row(1, "S_0030", "Group", "2026-11-09")])
    assert "보냄" not in html_of(1)

    # Annotation 줄(샷 한 줄에 태스크가 여럿)은 그 샷의 어느 태스크로 보내도 표시된다
    drawer.set_mode(MODE_ANNOTATION)
    drawer.set_rows(_anno_rows())
    assert drawer.mark_sent(13) == 1
    shot = next(r for r in drawer.shown_rows() if r["shot_code"] == "S_0010")
    assert "보냄" in drawer._row_html(shot)
    other = next(r for r in drawer.shown_rows() if r["shot_code"] == "S_0020")
    assert "보냄" not in drawer._row_html(other)
