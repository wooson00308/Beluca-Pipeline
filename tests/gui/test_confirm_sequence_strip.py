"""이어 재생의 컷 띠 — 칸·자리·누르기."""

from __future__ import annotations

from typing import Any, List

import pytest

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from bpe.gui.confirm.sequence_strip import SequenceStrip
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("창을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)


def test_strip_shows_cuts_and_seeks_where_clicked(qtbot: Any) -> None:
    strip = SequenceStrip()
    qtbot.addWidget(strip)
    strip.resize(900, 36)
    strip.show()
    strip.set_cuts(["S_0010", "S_0020", "S_0030"], [10, 30, 10])
    strip.set_note("3컷 · 1280×720")
    assert strip.cut_names() == ["S_0010", "S_0020", "S_0030"] and strip.note() == "3컷 · 1280×720"
    strip.set_cached(1, 12)
    strip.set_position(25)
    assert strip.position() == 25
    canvas = strip._canvas
    w = canvas.width()
    assert strip.pos_at(0) == 0 and strip.pos_at(w - 1) == 49 and strip.pos_at(w * 0.5) == 25
    sought: List[int] = []
    strip.seek_requested.connect(sought.append)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(int(w * 0.9), 10))
    assert len(sought) == 1 and 43 <= sought[0] <= 46  # 셋째 컷 안
    closed: List[int] = []
    strip.close_requested.connect(lambda: closed.append(1))
    strip._close.click()
    assert closed == [1]
    strip.grab()  # 그리기가 죽지 않는다
    strip.set_counts([10, 0, 10])  # 못 푼 컷은 길이 0
    assert strip.pos_at(w - 1) == 19
    strip.grab()
