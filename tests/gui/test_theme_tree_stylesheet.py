"""트리 QSS 회귀 — 화살표는 QSS 가 아니라 LibraryTree.drawBranches 담당."""

from __future__ import annotations

from bpe.gui import theme


def test_tree_stylesheet_has_no_branch_rules():
    """::branch QSS 는 사각형으로 렌더링되는 함정 — 다시 들어오면 안 된다."""
    qss = theme.tree_stylesheet()
    assert "::branch" not in qss
    assert "background-color: {}".format(theme.PANEL_BG) in qss
    assert "font-size: {}px".format(theme.FONT_SIZE_TREE) in qss
    assert theme.ACCENT in qss


def test_tree_arrow_constants_sane():
    """drawBranches 가 쓰는 상수 — 인덴트 칸(20px)과 행높이 안에 들어와야 한다."""
    assert 0 < theme.TREE_ARROW_DEPTH < theme.TREE_ARROW_SIZE < 20
