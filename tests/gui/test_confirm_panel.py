"""컨펌 창 오른쪽 칸 — 검사 줄, 지난 지적의 프레임 번호, 메모 줄."""

from __future__ import annotations

from typing import Any, List

import pytest

try:
    from bpe.gui.confirm import side_panel as sp
    from bpe.gui.confirm.side_panel import ConfirmSidePanel
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("컨펌 창 패널을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)

from bpe.core.confirm_checks import STATE_FAIL, STATE_PASS, CheckResult


def _check(state: str, message: str) -> CheckResult:
    return CheckResult("frames", state, message)


@pytest.fixture
def panel(qtbot: Any) -> Any:
    p = ConfirmSidePanel()
    qtbot.addWidget(p)
    return p


def test_checks_collapse_to_one_line_when_all_pass(panel: Any) -> None:
    panel.set_checks([_check(STATE_PASS, "프레임 74/74 통과"), _check(STATE_PASS, "fps 통과")])
    assert "2/2 통과" in panel._v_checks.text() and "프레임 74/74" not in panel._v_checks.text()
    assert "프레임 74/74 통과" in panel._v_checks.toolTip()
    assert panel._btn_failures.isHidden()


def test_failed_check_is_spelled_out(panel: Any) -> None:
    panel.set_checks(
        [_check(STATE_FAIL, "프레임 다름: 편집본 75 / 작업본 74"), _check(STATE_PASS, "fps 통과")]
    )
    assert "편집본 75 / 작업본 74" in panel._v_checks.text()
    assert not panel._btn_failures.isHidden()


def test_frame_numbers_in_past_notes_are_links(panel: Any) -> None:
    html = sp._frame_links("[1040] 엣지 <정리>\n[1066-1070] 블랙")
    assert html.count('href="frame:') == 2 and "frame:1040" in html and "frame:1066" in html
    assert "&lt;정리&gt;" in html and "<br>" in html

    got: List[int] = []
    panel.past_frame_clicked.connect(got.append)
    panel.set_past_notes(
        [{"version_code": "S_comp_v001", "timestamp": "2026-11-10", "content": "[1040] 엣지"}], ""
    )
    assert panel.past_count() == 1
    panel._past_rows[0]._on_link("frame:1040")
    panel._past_rows[0]._on_link("https://example.invalid")
    assert got == [1040]


def test_memo_lines_keep_their_text_and_count(panel: Any) -> None:
    panel.set_memo([(1, "[1040] 엣지", True), (2, "[1052] 블랙", False)])
    assert panel.memo_texts() == ["[1040] 엣지", "[1052] 블랙"]
    assert "보낼 줄 1" in panel._memo_head.text()
    panel.set_memo([])
    assert panel._memo_head.text() == "메모"


def test_work_line_puts_codes_in_mono(panel: Any) -> None:
    html = sp._mono_codes("업체 A · v017 · sv")
    assert html.count("<span") == 2 and "업체 A" in html
