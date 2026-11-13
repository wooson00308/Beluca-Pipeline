"""컨펌 창의 상태 색·아이콘 — 샷그리드 값이 있으면 그것, 없으면 BPE 기본 표."""

from __future__ import annotations

from typing import Any

import pytest

try:
    from bpe.gui import theme
    from bpe.gui.confirm import status_style
    from bpe.gui.confirm.side_panel import ConfirmSidePanel
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("컨펌 창 부품을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)


@pytest.fixture(autouse=True)
def _clean_styles() -> Any:
    status_style.set_styles({})
    yield
    status_style.set_styles({})


def test_falls_back_to_the_app_palette_until_shotgrid_answers(qapp: Any) -> None:
    _ = qapp
    assert not status_style.has_styles()
    assert status_style.colors("sv") == theme.task_status_badge_colors("sv")
    assert status_style.name("sv") == ""
    assert not status_style.chip("sv", 16).isNull()


def test_shotgrid_colours_win_and_text_stays_readable(qapp: Any) -> None:
    _ = qapp
    status_style.set_styles(
        {
            "SV": {"name": "supervisor confirm", "color": "#1dd72e"},
            "hld": {"name": "Hold", "color": "#0a0a0a"},
            "cfrm": {"name": "SV Confirmed", "color": "#ffffff", "icon_key": "icon_thumb_up"},
        }
    )
    assert status_style.colors("sv") == ("#1dd72e", "#111111")  # 밝은 바탕엔 어두운 글자
    assert status_style.colors("hld") == ("#0a0a0a", "#ffffff")
    assert status_style.name("sv") == "supervisor confirm"
    # 어두운 패널 위에 쓸 글자색: 상태 색이 너무 어두우면 흐린 글자색으로
    assert status_style.text_color("sv") == "#1dd72e"
    assert status_style.text_color("hld") != "#0a0a0a"
    assert not status_style.chip("cfrm", 18).isNull()  # 기본 아이콘은 우리가 그린다
    assert not status_style.icon("unknown-code").isNull()


def test_status_picker_lists_codes_with_names_and_icons(qtbot: Any) -> None:
    status_style.set_styles({"tm": {"name": "team confirm", "color": "#d5f762"}})
    panel = ConfirmSidePanel()
    qtbot.addWidget(panel)
    panel.set_other_statuses([("tm", "team confirm"), ("hld", "Hold")])
    box = panel._other
    assert box.count() == 3 and box.itemText(0) == "Status"
    assert box.itemData(1) == "tm" and "team confirm" in box.itemText(1)
    assert not box.itemIcon(1).isNull() and not box.itemIcon(2).isNull()
    assert box.view().minimumWidth() >= 280  # 고르기 쉽게 넓고 큰 목록
    assert not panel._btn_retake.icon().isNull() and not panel._btn_cfrm.icon().isNull()
    got = []
    panel.status_requested.connect(got.append)
    panel._on_other(2)
    assert got == ["hld"] and box.currentIndex() == 0
