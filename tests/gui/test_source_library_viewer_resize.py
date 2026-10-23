"""소스 라이브러리 창 — 프리뷰(뷰어) 기본 크기와 위아래·좌우 경계선 크기 조절.

실제 공유 서버(W:)는 건드리지 않는다: 라이브러리 설정·인덱스 열기·트리 채우기는
전부 가짜로 바꾸고, 앱 폴더는 ``tmp_app_dir`` 임시 폴더만 쓴다.
"""

from __future__ import annotations

from typing import Any

import pytest

# 영상 미리보기(QtMultimedia)를 못 불러오는 CI(Ubuntu)에서는 건너뛴다.
try:
    import bpe.gui.widgets.source_library_dialog as sdlg
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("라이브러리 창을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)
from PySide6.QtCore import Qt

from bpe.gui.widgets.source_library_grid import CELL_W


def test_default_preview_is_20_percent_bigger() -> None:
    old_h = sdlg._preview_height_for_width(600)
    new_h = sdlg._preview_height_for_width(sdlg._LEFT_DEFAULT_W)
    assert sdlg._LEFT_DEFAULT_W == 720
    assert new_h / old_h == pytest.approx(1.2, abs=0.01)


def test_grid_min_width_fits_three_columns() -> None:
    w = sdlg._grid_min_width(CELL_W, 2, 1, 10)
    assert w >= 3 * CELL_W + 4 * 2 + 2 + 10


@pytest.fixture
def dialog(qtbot, tmp_app_dir, monkeypatch) -> Any:
    _ = tmp_app_dir
    monkeypatch.setattr(sdlg, "get_source_library_settings", lambda: {})
    monkeypatch.setattr(sdlg.libcfg, "load_library", lambda: {})
    monkeypatch.setattr(sdlg.libcfg, "probe_library_read", lambda: None)
    monkeypatch.setattr(sdlg.libcfg, "roots_for_view", lambda _lib: [])
    monkeypatch.setattr(sdlg.SourceLibraryDialog, "_sync_index", lambda self: None)
    monkeypatch.setattr(sdlg.SourceLibraryDialog, "_open_index", lambda self: None)
    monkeypatch.setattr(sdlg.SourceLibraryDialog, "_reload_tree", lambda self, **_k: None)
    dlg = sdlg.SourceLibraryDialog()
    qtbot.addWidget(dlg)
    dlg.resize(1600, 1000)
    dlg.show()
    qtbot.waitExposed(dlg)
    yield dlg
    dlg.close()


def test_splitters_layout(dialog) -> None:
    split = dialog._preview_split
    assert split is not None
    assert split.orientation() == Qt.Orientation.Vertical
    assert split.widget(0) is dialog._preview
    assert not split.childrenCollapsible()
    # 왼쪽 열 폭 상한(예전 700) 이 풀렸다.
    assert dialog._left_col.maximumWidth() > 700
    assert dialog._main_splitter.sizes()[0] == pytest.approx(sdlg._LEFT_DEFAULT_W, abs=4)


def test_preview_height_follows_width_until_dragged(dialog, qtbot) -> None:
    split = dialog._preview_split
    expected = sdlg._preview_height_for_width(dialog._left_col.width())
    qtbot.waitUntil(lambda: abs(split.sizes()[0] - expected) <= 2)

    # 위아래로 끈 높이는 창 크기를 바꿔도 유지된다.
    split.moveSplitter(320, 1)
    held = split.sizes()[0]
    dialog.resize(1650, 960)
    qtbot.wait(20)
    assert split.sizes()[0] == held

    # 좌우로 끌면 다시 폭 비율로 맞춘다 (마지막에 끈 쪽이 이김).
    dialog._main_splitter.moveSplitter(800, 1)
    qtbot.wait(20)
    expected = sdlg._preview_height_for_width(dialog._left_col.width())
    assert dialog._preview_height_user_set is False
    assert split.sizes()[0] == pytest.approx(expected, abs=2)


def test_preview_never_below_minimum(dialog) -> None:
    split = dialog._preview_split
    split.moveSplitter(0, 1)
    assert split.sizes()[0] >= sdlg._PREVIEW_MIN_H
