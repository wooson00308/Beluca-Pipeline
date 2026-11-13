"""컨펌 창 — 가짜 샷 폴더(작은 시험 영상)로 여는 것부터 그리기·노트 그림까지.

그래픽 장치나 ffmpeg 가 없는 환경(CI)에서는 건너뛴다. 서버(W:)와 실제 ShotGrid 는
쓰지 않는다: 영상은 tmp_path 에 만들고, 앱 폴더는 tmp_app_dir 로 격리한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

import pytest

try:
    from bpe.gui.confirm.confirm_window import KEY_CUR, KEY_EDIT, KEY_ORG, KEY_PREV, ConfirmWindow
    from bpe.gui.confirm.gl_selfcheck import run_gl_selfcheck
    from bpe.gui.confirm.timeline import ConfirmTimeline
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("컨펌 창을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from bpe.core.confirm_view_math import CHANNEL_R, CHANNEL_RGB
from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe

_BIN = Path(__file__).resolve().parents[2] / "installer" / "ffmpeg-bin"
_W, _H = 128, 72


def _tool(name: str, found: Optional[str]) -> Optional[str]:
    if found:
        return found
    p = _BIN / (name + ".exe")
    return str(p) if p.is_file() else None


def _make(ffmpeg: str, path: Path, frames: int, pattern: str = "testsrc") -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    made = subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            f"{pattern}=size={_W}x{_H}:rate=24", "-frames:v", str(frames),
            "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", str(path),
        ],
        capture_output=True,
    )  # fmt: skip
    return made.returncode == 0 and path.is_file()


@pytest.fixture
def shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: Any) -> Path:
    """원본·편집본·v001·v002 가 있는 가짜 샷. 편집본만 프레임이 하나 많다."""
    _ = qapp
    if not run_gl_selfcheck().context_ok:
        pytest.skip("OpenGL 3.3 을 쓸 수 없는 환경")
    ffmpeg = _tool("ffmpeg", resolve_ffmpeg())
    ffprobe = _tool("ffprobe", resolve_ffprobe())
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe 가 없는 환경")
    monkeypatch.setenv("FFMPEG_PATH", ffmpeg)
    monkeypatch.setenv("FFPROBE_PATH", ffprobe)
    root = tmp_path / "SHOT_A"
    renders = root / "comp" / "devl" / "renders"
    ok = _make(ffmpeg, renders / "SHOT_A_comp_v001.mov", 6, "testsrc2")
    ok = _make(ffmpeg, renders / "SHOT_A_comp_v002.mov", 6) and ok
    ok = _make(ffmpeg, root / "plate" / "org" / "v001" / "mov" / "SHOT_A_org_v001.mov", 6) and ok
    ok = _make(ffmpeg, root / "edit" / "SHOT_A_edit_v001.mov", 7) and ok
    if not ok:
        pytest.skip("시험 영상을 만들 수 없는 ffmpeg")
    return root


@pytest.fixture
def win(qtbot: Any, tmp_app_dir: Path, shot: Path) -> Any:
    _ = tmp_app_dir
    w = ConfirmWindow()
    qtbot.addWidget(w)
    w.resize(1100, 700)
    w.show()
    qtbot.waitExposed(w)
    w.open_movie(str(shot / "comp" / "devl" / "renders" / "SHOT_A_comp_v002.mov"))

    def _loaded() -> bool:
        b = w._bufs
        return w._count == 6 and all(len(b[k].frames) >= 6 for k in (KEY_CUR, KEY_PREV, KEY_ORG))

    qtbot.waitUntil(_loaded, timeout=30000)
    yield w
    w.close()


def test_opens_all_four_buffers_and_checks_against_edit(win: Any) -> None:
    b = win._bufs
    assert all(b[k].available for k in (KEY_ORG, KEY_PREV, KEY_CUR, KEY_EDIT))
    assert b[KEY_PREV].version_label == "v001" and b[KEY_CUR].version_label == "v002"
    assert b[KEY_CUR].size == (_W, _H)
    # 편집본이 7프레임, 작업본이 6프레임 → 실패가 크게 떠야 한다
    assert [c.state for c in win._checks] == ["fail", "pass", "pass"]
    assert win._banner.isVisible() and "편집본 7 / 작업본 6" in win._banner.text()
    assert win._timeline.count() == 6


def test_flip_diff_and_view_state_label(win: Any) -> None:
    win._show_buffer(KEY_ORG)
    assert win._shown == KEY_ORG and win._last_shown == KEY_CUR
    assert win._hud.text().startswith("1 원본")
    win._show_buffer(KEY_CUR)
    win._toggle_diff()
    assert win._diff and "차이 3−1" in win._state.text()
    win._gamma.setValue(220)
    assert "감마 2.20" in win._state.text() and win._btn_reset.isVisible()
    win._set_channel(CHANNEL_R)
    assert win._channel == CHANNEL_R
    win._set_channel(CHANNEL_R)
    assert win._channel == CHANNEL_RGB  # 한 번 더 누르면 RGB
    win._reset_view()
    assert not win._diff and win._gamma_value() == 1.0 and not win._state.isVisible()


def test_frame_stepping_and_numbers(win: Any) -> None:
    start = win._frame_start
    win._go_first()
    assert win.frame_number() == start
    win._step(1)
    win._step(1)
    assert win.frame_number() == start + 2
    win._go_last()
    assert win.frame_number() == start + 5
    win._step(1)
    assert win.frame_number() == start + 5  # 끝을 넘지 않는다
    win._frame_edit.setText(str(start + 3))
    win._on_frame_typed()
    assert win._index == 3


def test_draw_rect_then_type_goes_to_memo(win: Any, qtbot: Any) -> None:
    win._set_tool("rect")
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None
    p0 = QPointF(r[0] + r[2] * 0.2, r[1] + r[3] * 0.2).toPoint()
    p1 = QPointF(r[0] + r[2] * 0.6, r[1] + r[3] * 0.6).toPoint()
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    QTest.mouseMove(layer, p1)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    assert layer.is_editing_text()  # 네모를 그리면 바로 글 칸
    QTest.keyClicks(layer._edit, "edge")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return)
    shapes = layer.doc().shapes()
    assert len(shapes) == 1 and shapes[0]["text"] == "edge"
    frame = win.frame_number()
    assert shapes[0]["frame"] == frame
    x0, y0 = shapes[0]["points"][0]
    assert abs(x0 - 0.2) < 0.02 and abs(y0 - 0.2) < 0.03
    assert win._panel.memo_texts() == [f"[{frame}] edge"]
    assert win._timeline.marks() == [frame]

    # 확대해도 그림은 영상의 같은 자리에 붙어 있다
    before = layer.doc().shapes()[0]["points"]
    win._view.zoom_at(QPointF(50, 50), 2.0)
    assert layer.doc().shapes()[0]["points"] == before
    r2 = win._view.image_rect()
    assert r2 is not None and r2[2] > r[2] * 1.9

    # 다른 프레임으로 가면 안 보이고, 되돌리기로 사라진다
    win._step(1 if win._index == 0 else -1)
    assert layer.doc().shapes_at(win.frame_number()) == []
    layer.undo()
    layer.undo()
    assert layer.doc().is_empty() and win._panel.memo_texts() == []


def test_note_images_are_made_per_marked_frame(win: Any) -> None:
    from PySide6.QtGui import QImage

    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    doc = win._layer.doc()
    f0 = win._frame_start
    doc.add(make_shape(KIND_RECT, f0, [(0.1, 0.1), (0.5, 0.5)], text="a"))
    doc.add(make_shape(KIND_RECT, f0 + 3, [(0.2, 0.2), (0.6, 0.6)], text="b"))
    win._on_doc_changed()
    paths = win._render_note_images()
    try:
        assert len(paths) == 2
        img = QImage(paths[0])
        assert (img.width(), img.height()) == (_W, _H)
    finally:
        win._remove_files(paths)
    assert not any(Path(p).exists() for p in paths)


def test_draft_is_saved_under_app_dir_and_restored(
    win: Any, tmp_app_dir: Path, shot: Path, qtbot: Any
) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    win._layer.doc().add(
        make_shape(KIND_RECT, win._frame_start, [(0.1, 0.1), (0.4, 0.4)], text="x")
    )
    win._save_draft()
    drafts = list((tmp_app_dir / "confirm_drafts").glob("*.json"))
    assert len(drafts) == 1 and "SHOT_A_comp_v002" in drafts[0].name
    movie = str(shot / "comp" / "devl" / "renders" / "SHOT_A_comp_v002.mov")
    win.open_movie(movie)
    qtbot.waitUntil(lambda: win._count == 6 and len(win._bufs[KEY_CUR].frames) >= 6, timeout=30000)
    assert len(win._layer.doc().shapes()) == 1


def test_status_buttons_need_shotgrid_context(win: Any) -> None:
    assert not win._panel.can_send()  # 파일만 열었을 때는 보내기 버튼이 꺼져 있다
    win._on_status_requested("retake")
    assert not win._send_timer.isActive()


def test_close_frees_frames_and_stops_workers(qtbot: Any, tmp_app_dir: Path, shot: Path) -> None:
    _ = tmp_app_dir
    w = ConfirmWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.open_movie(str(shot / "comp" / "devl" / "renders" / "SHOT_A_comp_v002.mov"))
    qtbot.waitUntil(lambda: w._count == 6, timeout=30000)
    w.close()
    assert w.is_closed()
    assert all(not b.frames for b in w._bufs.values())
    assert not w._decoders and not w._workers


def test_timeline_maps_x_to_frame(qapp: Any) -> None:
    _ = qapp
    t = ConfirmTimeline()
    t.resize(800, 50)
    t.set_range(1001, 100)
    assert t.index_at(0) == 0
    assert t.index_at(799) == 99
    mid = t.index_at(400)
    assert 48 <= mid <= 51
    assert t._label_step() in (5, 10)


def test_drawing_tools_are_icons_not_words(win: Any) -> None:
    # 그리기 도구는 글자 버튼이 아니라 아이콘 띠다(시안 2판 기준)
    tools = list(win._tool_btns.values()) + [win._btn_erase]
    assert len(tools) == 6
    assert all(b.text() == "" and not b.icon().isNull() for b in tools)
    win._set_tool("pen")
    assert win._tool_btns["pen"].isChecked() and not win._tool_btns["select"].isChecked()
    assert win._tool_hint.text() != ""


def test_header_follows_list_and_moves_between_shots(win: Any, monkeypatch: Any) -> None:
    rows = [
        {
            "task_id": i,
            "shot_code": f"S_00{i}0",
            "uploader_type": "Group",
            "uploader_name": "업체 A",
        }
        for i in (1, 2, 3)
    ]
    win._task = dict(rows[1])
    win._drawer.set_rows(rows)
    assert win._btn_list.text() == "외주 3" and win._pos.text() == "2 / 3"
    assert win._btn_prev.isEnabled() and win._btn_next.isEnabled()
    opened = []
    monkeypatch.setattr(win, "_open_task", opened.append)
    win._nav_shot(1)
    assert opened and opened[0]["task_id"] == 3
