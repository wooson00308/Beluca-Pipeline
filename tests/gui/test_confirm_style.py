"""컨펌 창의 모양 부품 — 아이콘 경로 풀이, 번호 붙은 버튼."""

from __future__ import annotations

from typing import Any

import pytest

try:
    from bpe.gui.confirm import style
    from bpe.gui.confirm.parts import Grip, KeyButton
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("컨펌 창 모양 부품을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)


def test_svg_path_reads_absolute_and_relative_commands() -> None:
    box = style.svg_path("M4 6h16v12H4z").boundingRect()
    assert (box.left(), box.top(), box.right(), box.bottom()) == (4.0, 6.0, 20.0, 18.0)
    # 이어 쓰는 좌표(l 뒤 여러 쌍)와 곡선
    tri = style.svg_path("M15 5l-7 7 7 7").boundingRect()
    assert (tri.left(), tri.right(), tri.top(), tri.bottom()) == (8.0, 15.0, 5.0, 19.0)
    curve = style.svg_path("M3 17c4-12 6 2 10-6s6-4 8-6")
    end = curve.currentPosition()
    assert (end.x(), end.y()) == (21.0, 5.0)


@pytest.mark.parametrize("name", style.ICON_NAMES)
def test_every_icon_fits_its_box(name: str) -> None:
    _mode, d = style._ICON_PATHS[name]
    box = style.svg_path(d).boundingRect()
    assert box.width() > 0 or box.height() > 0
    assert box.left() >= 0 and box.top() >= 0 and box.right() <= 24 and box.bottom() <= 24


def test_icons_render(qapp: Any) -> None:
    _ = qapp
    for name in style.ICON_NAMES:
        assert not style.make_icon(name).isNull()


def test_key_button_width_follows_label(qapp: Any) -> None:
    _ = qapp
    b = KeyButton("2")
    b.set_label("전 버전")
    short = b.sizeHint().width()
    b.set_label("전 버전 v016")
    assert b.sizeHint().width() > short
    assert b.sizeHint().height() == style.CONTROL_H
    assert b.isCheckable() and b.text() == "" and b.label() == "전 버전 v016"
    assert Grip().width() > 0
