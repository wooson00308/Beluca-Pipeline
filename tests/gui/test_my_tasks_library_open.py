"""My Tasks 「Library」 버튼 — 소스 라이브러리를 BPE 를 잠그지 않는 독립 창으로 연다."""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from PySide6.QtCore import Qt

# 라이브러리 창은 영상 미리보기(QtMultimedia)를 쓴다 — 오디오 라이브러리(libpulse)가
# 없는 CI(Ubuntu)에서는 import 자체가 실패하므로 이 파일을 건너뛴다 (Windows·macOS 는 실행).
pytest.importorskip("PySide6.QtMultimedia", reason="QtMultimedia 를 불러올 수 없는 환경")

import bpe.gui.widgets.source_library_dialog as sdlg  # noqa: E402
from bpe.gui.tabs.my_tasks_tab import MyTasksTab  # noqa: E402


class _FakeDialog:
    instances: List["_FakeDialog"] = []

    def __init__(self, parent, **kwargs) -> None:
        self.parent = parent
        self.kwargs = kwargs
        self.flags: Optional[Any] = None
        self.attrs: List[Any] = []
        self.calls: List[str] = []
        self.visible = False
        self.closed = False
        self.state = Qt.WindowState.WindowNoState
        _FakeDialog.instances.append(self)

    def setWindowFlags(self, flags) -> None:  # noqa: N802
        self.flags = flags

    def setAttribute(self, attr, on=True) -> None:  # noqa: N802
        self.attrs.append((attr, on))

    def show(self) -> None:
        self.calls.append("show")
        self.visible = True

    def exec(self) -> int:  # 모달로 열면 안 된다
        raise AssertionError("exec() 로 열면 BPE 가 잠긴다")

    def is_closed(self) -> bool:
        return self.closed

    def isVisible(self) -> bool:  # noqa: N802
        return self.visible

    def isMinimized(self) -> bool:  # noqa: N802
        return bool(self.state & Qt.WindowState.WindowMinimized)

    def windowState(self):  # noqa: N802
        return self.state

    def setWindowState(self, state) -> None:  # noqa: N802
        self.state = state
        self.calls.append("setWindowState")

    def raise_(self) -> None:
        self.calls.append("raise_")

    def activateWindow(self) -> None:  # noqa: N802
        self.calls.append("activateWindow")


class _Combo:
    def currentData(self):  # noqa: N802
        return 123

    def currentText(self):  # noqa: N802
        return "MMK"


class _TabStub:
    _open_source_library_dialog = MyTasksTab._open_source_library_dialog

    def __init__(self) -> None:
        self._project_combo = _Combo()
        self._projects = [{"id": 123}]
        self._source_library_dlg = None
        self._source_library_dlgs: List[Any] = []


@pytest.fixture(autouse=True)
def fake_dialog(monkeypatch):
    _FakeDialog.instances.clear()
    monkeypatch.setattr(sdlg, "SourceLibraryDialog", _FakeDialog)
    return _FakeDialog


def test_opens_independent_window_without_blocking() -> None:
    tab = _TabStub()
    tab._open_source_library_dialog()
    assert len(_FakeDialog.instances) == 1
    dlg = _FakeDialog.instances[0]
    assert dlg.parent is None
    assert dlg.calls == ["show"]
    assert dlg.kwargs["project_id"] == 123
    assert dlg.kwargs["project_name"] == "MMK"
    assert dlg.flags is not None
    assert dlg.flags & Qt.WindowType.Window
    assert dlg.flags & Qt.WindowType.WindowMinimizeButtonHint
    assert dlg.flags & Qt.WindowType.WindowMaximizeButtonHint
    assert (Qt.WidgetAttribute.WA_QuitOnClose, False) in dlg.attrs
    assert tab._source_library_dlg is dlg
    assert tab._source_library_dlgs == [dlg]


def test_second_click_brings_existing_window_forward() -> None:
    tab = _TabStub()
    tab._open_source_library_dialog()
    tab._open_source_library_dialog()
    assert len(_FakeDialog.instances) == 1
    assert _FakeDialog.instances[0].calls == ["show", "raise_", "activateWindow"]


def test_minimized_window_is_restored_keeping_maximized() -> None:
    tab = _TabStub()
    tab._open_source_library_dialog()
    dlg = _FakeDialog.instances[0]
    dlg.state = Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized
    tab._open_source_library_dialog()
    assert len(_FakeDialog.instances) == 1
    assert not (dlg.state & Qt.WindowState.WindowMinimized)
    assert dlg.state & Qt.WindowState.WindowMaximized
    assert dlg.calls[-3:] == ["setWindowState", "raise_", "activateWindow"]


def test_closed_window_is_replaced_but_kept_alive() -> None:
    tab = _TabStub()
    tab._open_source_library_dialog()
    first = _FakeDialog.instances[0]
    first.closed = True
    first.visible = False
    tab._open_source_library_dialog()
    assert len(_FakeDialog.instances) == 2
    second = _FakeDialog.instances[1]
    assert tab._source_library_dlg is second
    # 닫힌 창도 목록에 남긴다 (안의 스레드가 끝나기 전에 지워지지 않게)
    assert tab._source_library_dlgs == [first, second]
