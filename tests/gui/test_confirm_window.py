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
    # 프레임 수는 edit 기준(실패), fps 는 ORG plate 기준(통과), 해상도는 프리셋이 없어 판정 안 함
    assert [c.state for c in win._checks] == ["fail", "pass", "unknown"]
    assert win._banner.isVisible() and "edit 7 / 현재버전 6" in win._banner.text()
    assert win._timeline.count() == 6


def test_flip_diff_and_view_state_label(win: Any) -> None:
    win._show_buffer(KEY_ORG)
    assert win._shown == KEY_ORG and win._last_shown == KEY_CUR
    assert win._hud.text().startswith("1 ORG plate")
    win._show_buffer(KEY_CUR)
    win._toggle_diff()
    assert win._diff and "Difference 3−1" in win._state.text()
    win._set_gamma(2.2)
    assert "Gamma 2.20" in win._state.text() and win._btn_reset.isVisible()
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


def test_draw_rect_then_text_tool_goes_to_memo(win: Any, qtbot: Any) -> None:
    win._set_tool("rect")
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None
    p0 = QPointF(r[0] + r[2] * 0.2, r[1] + r[3] * 0.2).toPoint()
    p1 = QPointF(r[0] + r[2] * 0.6, r[1] + r[3] * 0.6).toPoint()
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    QTest.mouseMove(layer, p1)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    assert not layer.is_editing_text()  # 네모는 그리면 끝 — 글 칸이 뜨지 않는다
    shapes = layer.doc().shapes()
    assert len(shapes) == 1 and shapes[0]["kind"] == "rect" and shapes[0]["text"] == ""
    assert win._panel.memo_text() == ""
    # 글은 글씨 도구로 원하는 자리에 따로 쓴다(네모와 다른 물건)
    win._set_tool("text")
    at = QPointF(r[0] + r[2] * 0.7, r[1] + r[3] * 0.8).toPoint()
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert layer.is_editing_text()
    QTest.keyClicks(layer._edit, "edge")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return)
    shapes = layer.doc().shapes()
    assert [x["kind"] for x in shapes] == ["rect", "text"] and shapes[1]["text"] == "edge"
    frame = win.frame_number()
    assert shapes[0]["frame"] == frame
    x0, y0 = shapes[0]["points"][0]
    assert abs(x0 - 0.2) < 0.02 and abs(y0 - 0.2) < 0.03
    assert win._panel.memo_text() == "edge"  # 화면에 쓴 글이 메모 칸에 그대로 적힌다
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
    for _ in range(3):  # 글 고침 · 글 넣기 · 네모 — 네모와 글이 따로라 한 번씩 되돌린다
        layer.undo()
    assert layer.doc().is_empty() and win._panel.memo_text() == ""


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
    assert len(tools) == 7
    assert all(b.text() == "" and not b.icon().isNull() for b in tools)
    win._set_tool("pen")
    assert win._tool_btns["pen"].isChecked() and not win._tool_btns["select"].isChecked()
    assert win._tool_hint.text() != ""


def test_header_follows_list_and_moves_between_shots(win: Any, monkeypatch: Any) -> None:
    rows = [
        {
            "task_id": i,
            "shot_code": f"S_00{i}0",
            "task_status": "sv",
            "uploader_type": "Group",
            "uploader_name": "업체 A",
        }
        for i in (1, 2, 3)
    ]
    win._task = dict(rows[1])
    win._drawer._set_group("SV_Confirm (vendor)")
    win._drawer.set_rows(rows)
    assert win._btn_list.text().strip() == "SV_Confirm (vendor) 3"
    assert win._panel.nav_text() == "2 / 3"
    assert win._panel.nav_enabled() == (True, True)
    opened = []
    monkeypatch.setattr(win, "_open_task", opened.append)
    win._nav_shot(1)
    assert opened and opened[0]["task_id"] == 3


def test_keyboard_shortcuts(win: Any, qtbot: Any) -> None:
    from bpe.core.confirm_view_math import CHANNEL_LUMA

    def press(key: Any) -> None:
        QTest.keyClick(win, key)

    press(Qt.Key.Key_1)
    assert win._shown == KEY_ORG
    press(Qt.Key.Key_3)
    assert win._shown == KEY_CUR and win._last_shown == KEY_ORG
    press(Qt.Key.Key_D)
    assert win._diff
    press(Qt.Key.Key_D)
    assert not win._diff
    press(Qt.Key.Key_R)
    assert win._channel == CHANNEL_R
    press(Qt.Key.Key_A)
    assert win._channel == CHANNEL_LUMA
    press(Qt.Key.Key_A)
    assert win._channel == CHANNEL_RGB
    press(Qt.Key.Key_Home)
    press(Qt.Key.Key_Right)
    assert win._index == 1
    press(Qt.Key.Key_End)
    assert win._index == 5
    press(Qt.Key.Key_Left)
    assert win._index == 4
    for key, tool in (
        (Qt.Key.Key_N, "rect"),
        (Qt.Key.Key_O, "ellipse"),
        (Qt.Key.Key_P, "pen"),
        (Qt.Key.Key_W, "arrow"),
        (Qt.Key.Key_T, "text"),
        (Qt.Key.Key_V, "select"),
    ):
        press(key)
        assert win._layer.tool() == tool
    press(Qt.Key.Key_Home)
    press(Qt.Key.Key_Space)
    assert win._playing
    qtbot.waitUntil(lambda: win._index > 0, timeout=5000)
    press(Qt.Key.Key_Space)
    assert not win._playing
    press(Qt.Key.Key_Question)
    assert win._help.isVisible()
    press(Qt.Key.Key_Escape)
    assert not win._help.isVisible()


def test_typing_in_a_text_box_does_not_trigger_shortcuts(win: Any) -> None:
    win._frame_edit.setFocus()
    QTest.keyClick(win._frame_edit, Qt.Key.Key_D)
    assert not win._diff
    QTest.keyClick(win, Qt.Key.Key_Escape)  # Esc 는 글 칸에서 빠져나온다


def _drag(layer: Any, points: Any) -> None:
    none = Qt.KeyboardModifier.NoModifier
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, none, points[0])
    for p in points[1:]:
        QTest.mouseMove(layer, p)
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, none, points[-1])


def test_pen_arrow_and_text_tools(win: Any) -> None:
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None

    def at(fx: float, fy: float) -> Any:
        return QPointF(r[0] + r[2] * fx, r[1] + r[3] * fy).toPoint()

    frame = win.frame_number()
    win._set_tool("pen")
    _drag(layer, [at(0.1, 0.1), at(0.2, 0.3), at(0.3, 0.2), at(0.4, 0.4)])
    assert not layer.is_editing_text()  # 펜은 글 칸이 안 뜬다
    pen = layer.doc().shapes()[-1]
    assert pen["kind"] == "pen" and len(pen["points"]) >= 3

    win._set_tool("arrow")
    _drag(layer, [at(0.5, 0.5), at(0.7, 0.3)])
    assert not layer.is_editing_text()  # 화살표도 그리면 끝 — 글 칸이 안 뜬다
    arrow = layer.doc().shapes()[-1]
    assert arrow["kind"] == "arrow" and arrow["text"] == ""

    win._set_tool("text")
    none = Qt.KeyboardModifier.NoModifier
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, none, at(0.2, 0.8))
    assert layer.is_editing_text()
    QTest.keyClicks(layer._edit, "hi")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return)
    text = layer.doc().shapes()[-1]
    assert text["kind"] == "text" and text["text"] == "hi"

    assert win._panel.memo_text() == "hi"
    assert win._timeline.marks() == [frame]

    # 고른 그림만 지우개로 지운다
    win._set_tool("select")
    layer._selected = arrow["id"]
    win._btn_erase.click()
    assert [s["kind"] for s in layer.doc().shapes()] == ["pen", "text"]


def test_lut_file_is_applied_and_remembered(win: Any, tmp_path: Path) -> None:
    from bpe.core.settings import get_confirm_settings

    # 빨강을 없애는 2칸짜리 룩업
    rows = [f"0.0 {g}.0 {b}.0" for b in (0, 1) for g in (0, 1) for _r in (0, 1)]
    cube = tmp_path / "no_red.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "\n".join(rows) + "\n", encoding="utf-8")
    assert not win._btn_lut.isEnabled()  # 룩업을 고르기 전에는 꺼져 있다
    win._apply_lut_file(str(cube), remember=True)
    assert win._lut is not None and win._lut_on and win._btn_lut.isChecked()
    assert get_confirm_settings()["luts"]["_default"] == str(cube)

    cur = win._bufs[KEY_CUR]
    data = cur.frames[0]
    plain = win._view.render_frame_image(data, _W, _H, lut_on=False)
    lut = win._view.render_frame_image(data, _W, _H, lut_on=True)
    assert plain is not None and lut is not None
    reds = [(plain.pixelColor(x, y).red(), x, y) for x in range(0, _W, 4) for y in range(0, _H, 4)]
    top, x, y = max(reds)
    assert top > 100  # 시험 영상에 빨간 곳이 있다
    assert lut.pixelColor(x, y).red() <= 3
    assert abs(lut.pixelColor(x, y).green() - plain.pixelColor(x, y).green()) <= 3

    QTest.keyClick(win, Qt.Key.Key_L)
    assert not win._lut_on
    QTest.keyClick(win, Qt.Key.Key_L)
    assert win._lut_on


def test_diff_keeps_shown_buffer_lit_and_marks_the_subtracted_one(win: Any) -> None:
    win._show_buffer(KEY_ORG)
    win._show_buffer(KEY_CUR)
    win._toggle_diff()
    assert win._buf_btns[KEY_CUR].isChecked() and not win._buf_btns[KEY_ORG].isChecked()
    assert win._buf_marks[KEY_ORG] and not win._buf_marks.get(KEY_PREV)
    assert win._btn_diff.text() == "Difference 3−1"
    win._toggle_diff()
    assert not win._buf_marks[KEY_ORG]


def test_fit_and_fill_buttons_follow_the_view(win: Any) -> None:
    win._view_fit()
    assert win._btn_fit.isChecked() and not win._btn_fill.isChecked()
    win._view.zoom_at(QPointF(50, 50), 2.0)
    assert not win._btn_fit.isChecked() and not win._btn_fill.isChecked()
    win._view_fill()
    assert win._view.fit_state() in ("fill", "fit")
    assert win._btn_fill.isChecked() == (win._view.fit_state() == "fill")


def test_gain_and_gamma_sliders_rest_in_the_middle(win: Any) -> None:
    for slider in (win._gain, win._gamma):
        assert slider.value() == 0 and slider.minimum() == -slider.maximum()
    assert win._gain_value() == 1.0 and win._gamma_value() == 1.0
    win._set_gamma(2.2)
    assert abs(win._gamma_value() - 2.2) < 0.03
    win._set_gamma(0.5)
    assert abs(win._gamma_value() - 0.5) < 0.01


def test_pixel_readout_keeps_its_width(win: Any) -> None:
    import re

    def plain() -> str:
        return re.sub(r"<[^>]+>", "", win._info.text()).replace("&nbsp;", " ")

    win._on_hover(-1, -1)
    empty = plain()
    win._on_hover(10, 10)
    filled = plain()
    assert "x   10 y   10" in filled and "R " in filled
    assert len(empty) == len(filled)  # 값이 생겨도 줄이 밀리지 않는다


def test_note_is_not_sent_when_a_marked_frame_has_no_picture(win: Any, monkeypatch: Any) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    doc = win._layer.doc()
    doc.add(make_shape(KIND_RECT, win._frame_start, [(0.1, 0.1), (0.5, 0.5)], text="a"))
    doc.add(make_shape(KIND_RECT, win._frame_start + 2, [(0.1, 0.1), (0.5, 0.5)], text="b"))
    win._on_doc_changed()
    win._bufs[KEY_CUR].frames.pop(2)  # 그 프레임이 아직 메모리에 없는 상황
    started = []
    monkeypatch.setattr(
        "bpe.gui.confirm.confirm_window.ShotGridWorker", lambda *a, **k: started.append(1)
    )
    win._task = {"shot_id": 1, "project_id": 1}
    win._loaded_task_id = ("shot", 1)  # 태스크가 없는 샷 — 화면의 영상이 이 샷의 것이다
    win._submit("retake")
    assert not started and not win._submit_busy
    assert "2장 중 1장" in win._panel._result.text()


def test_warns_when_file_version_differs_from_shotgrid_latest(
    win: Any, shot: Path, qtbot: Any
) -> None:
    movie = str(shot / "comp" / "devl" / "renders" / "SHOT_A_comp_v002.mov")
    win.open_movie(movie, {"latest_version_code": "SHOT_A_comp_v005"})
    qtbot.waitUntil(lambda: win._count == 6 and bool(win._version_note), timeout=30000)
    assert "v002" in win._version_note and "v005" in win._version_note
    assert "v005" in win._panel._result.text()
    win.open_movie(movie, {"latest_version_code": "SHOT_A_comp_v002"})
    qtbot.waitUntil(lambda: win._count == 6 and len(win._bufs[KEY_CUR].frames) >= 6, timeout=30000)
    assert win._version_note == ""


def test_busy_notice_shows_and_hides(win: Any) -> None:
    assert not win._busy.isVisible()  # 그림이 올라온 뒤에는 감춰져 있다
    win._set_busy("SHOT_A 여는 중…", "서버에서 영상 파일 찾는 중")
    assert win._busy.isVisible() and "SHOT_A" in win._busy.text()
    win._set_busy("")
    assert not win._busy.isVisible()


def test_picking_a_shot_reacts_at_once(win: Any, monkeypatch: Any) -> None:
    class _NoWorker:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.finished = self.error = self

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            pass

        def isRunning(self) -> bool:  # noqa: N802
            return False

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _NoWorker)
    win._toggle_drawer()
    assert win._drawer.isVisible()
    win._open_task({"task_id": 7, "shot_code": "S_0070", "project_code": "PROJ"})
    # 영상을 찾기도 전에: 서랍이 닫히고, 위 막대가 바뀌고, 가운데에 진행 알림이 뜬다
    assert not win._drawer.isVisible() and not win._scrim.isVisible()
    assert win._busy.isVisible() and "S_0070" in win._busy.text()
    assert "S_0070" in win._crumb.text()
    win._on_task_resolved("", win._load_token, {"shot_code": "S_0070"})
    assert "찾지 못했습니다" in win._busy.text()


def test_empty_labels_are_hidden_before_any_movie(qtbot: Any, tmp_app_dir: Path, qapp: Any) -> None:
    _ = (tmp_app_dir, qapp)
    try:
        w = ConfirmWindow()
    except Exception as exc:  # pragma: no cover - GL 없는 환경
        pytest.skip(str(exc))
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert not w._hud.isVisible() and not w._state.isVisible()
    assert not w._btn_reset.isVisible() and not w._busy.isVisible()
    w.close()


def test_ellipse_tool_draws_a_circle_without_a_text_box(win: Any) -> None:
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None
    win._set_tool("ellipse")
    p0 = QPointF(r[0] + r[2] * 0.6, r[1] + r[3] * 0.7).toPoint()  # 오른쪽 아래에서 왼쪽 위로 끈다
    p1 = QPointF(r[0] + r[2] * 0.3, r[1] + r[3] * 0.2).toPoint()
    _drag(layer, [p0, p1])
    assert not layer.is_editing_text()  # 원도 그리면 끝 — 글 칸이 안 뜬다
    shape = layer.doc().shapes()[-1]
    assert shape["kind"] == "ellipse" and shape["text"] == ""
    (x0, y0), (x1, y1) = shape["points"]
    assert x0 < x1 and y0 < y1  # 어느 쪽으로 끌어도 왼쪽 위 → 오른쪽 아래로 정리된다
    assert win._panel.memo_text() == ""
    paths = win._render_note_images()
    try:
        assert len(paths) == 1  # 원도 노트 그림에 그려진다
    finally:
        win._remove_files(paths)


def test_palette_offers_more_colours_and_recolours_the_selected_shape(win: Any) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape
    from bpe.gui.confirm import style as st

    assert len(win._palette_btns) == len(st.PALETTE) >= 12
    assert not win._palette.isVisible()
    win._toggle_palette()
    assert win._palette.isVisible() and win._btn_palette.isChecked()
    blue = "#4a90e2"
    assert blue in st.PALETTE and blue not in win._recent_colors
    win._palette_btns[blue].click()
    assert win._color == blue and win._recent_colors[0] == blue and len(win._recent_colors) == 3
    assert not win._palette.isVisible()  # 고르면 닫힌다
    assert win._swatch_btns[0].styleSheet().count(blue) >= 1

    doc = win._layer.doc()
    sid = doc.add(make_shape(KIND_RECT, win.frame_number(), [(0.1, 0.1), (0.4, 0.4)], text="a"))
    win._on_doc_changed()
    win._layer._selected = sid
    win._swatch_btns[1].click()  # 띠의 다른 색을 누르면 고른 그림 색이 바뀐다
    assert doc.get(sid)["color"] == win._recent_colors[1] == win._color


def test_memo_box_follows_shape_text_but_keeps_what_the_user_typed(win: Any) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    doc = win._layer.doc()
    f = win._frame_start
    a = doc.add(make_shape(KIND_RECT, f, [(0.1, 0.1), (0.3, 0.3)], text="엣지 수정해주세요"))
    win._on_doc_changed()
    assert win._panel.memo_text() == "엣지 수정해주세요"
    win._panel.append_memo("경로: W:/ref/a.mov")  # 사용자가 덧붙인 줄
    b = doc.add(make_shape(KIND_RECT, f + 2, [(0.5, 0.5), (0.7, 0.7)], text="블랙 뜸"))
    win._on_doc_changed()
    assert win._panel.memo_text() == "엣지 수정해주세요\n경로: W:/ref/a.mov\n블랙 뜸"
    doc.update(a, text="엣지 밝은 테 정리")  # 화면의 글을 고치면 그 줄만 바뀐다
    win._on_doc_changed()
    assert win._panel.memo_text() == "엣지 밝은 테 정리\n경로: W:/ref/a.mov\n블랙 뜸"
    doc.remove(b)  # 그림을 지우면 그 줄이 빠진다
    win._on_doc_changed()
    assert win._panel.memo_text() == "엣지 밝은 테 정리\n경로: W:/ref/a.mov"
    # 메모 칸에서 직접 고친 줄은 그림을 지워도 건드리지 않는다
    win._panel.set_memo_text("엣지 꼭 정리!\n경로: W:/ref/a.mov")
    doc.remove(a)
    win._on_doc_changed()
    assert win._panel.memo_text() == "엣지 꼭 정리!\n경로: W:/ref/a.mov"


def test_memo_text_is_the_note_body_and_survives_reopen(
    win: Any, shot: Path, qtbot: Any, monkeypatch: Any
) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    win._layer.doc().add(
        make_shape(KIND_RECT, win._frame_start, [(0.1, 0.1), (0.3, 0.3)], text="a")
    )
    win._on_doc_changed()
    win._panel.append_memo("덧붙임")
    win._save_draft()
    movie = str(shot / "comp" / "devl" / "renders" / "SHOT_A_comp_v002.mov")
    win.open_movie(movie)
    qtbot.waitUntil(lambda: win._count == 6 and len(win._bufs[KEY_CUR].frames) >= 6, timeout=30000)
    assert win._panel.memo_text() == "a\n덧붙임"  # 다시 열어도 그대로, 줄이 두 번 생기지 않는다
    win._pending_status = "retake"
    assert "메모 2줄, 그림 1장" in win._pending_summary()


def test_drag_on_the_picture_scrubs_frames_and_ctrl_drag_zooms(win: Any) -> None:
    win._set_tool("select")
    win._go_first()
    layer = win._layer
    none = Qt.KeyboardModifier.NoModifier
    y = layer.height() // 2
    x0 = layer.width() // 2
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, none, QPointF(x0, y).toPoint())
    QTest.mouseMove(layer, QPointF(x0 + 40, y).toPoint())
    assert win._index >= 2  # 오른쪽으로 끌면 뒤 프레임으로
    QTest.mouseMove(layer, QPointF(x0 - 400, y).toPoint())
    assert win._index == 0  # 왼쪽 끝을 넘지 않는다
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, none, QPointF(x0 - 400, y).toPoint())

    ctrl = Qt.KeyboardModifier.ControlModifier
    before, index = win._view.zoom(), win._index
    QTest.mousePress(layer, Qt.MouseButton.LeftButton, ctrl, QPointF(x0, y).toPoint())
    QTest.mouseMove(layer, QPointF(x0 + 120, y).toPoint())
    QTest.mouseRelease(layer, Qt.MouseButton.LeftButton, ctrl, QPointF(x0 + 120, y).toPoint())
    assert win._view.zoom() > before * 1.5 and win._index == index  # 확대만, 프레임은 그대로
    assert not win._btn_fit.isChecked()


def test_fullscreen_shows_only_the_picture_and_its_controls(win: Any, qtbot: Any) -> None:
    assert win._btn_fit.text() == "Fit (F)" and win._btn_fill.text() == "Fill (H)"
    assert win._btn_fullview.text() == "Fullscreen (F11)"
    win._btn_fullview.click()
    qtbot.waitUntil(win.isFullScreen, timeout=5000)
    hidden = (win._header_bar, win._view_bar, win._info, win._panel)
    assert all(not w.isVisible() for w in hidden)
    assert win._timeline.isVisible() and win._pill.isVisible() and win._btn_exit_full.isVisible()
    QTest.keyClick(win, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not win.isFullScreen(), timeout=5000)
    assert all(w.isVisible() for w in hidden) and not win._btn_exit_full.isVisible()


def test_buffer_buttons_use_the_studio_names(win: Any) -> None:
    labels = [win._buf_btns[k].label() for k in (KEY_ORG, KEY_PREV, KEY_CUR, KEY_EDIT)]
    assert labels == ["ORG plate", "이전버전", "현재버전", "edit"]
    assert "SHOT_A_comp_v002.mov" in win._buf_btns[KEY_CUR].toolTip()


# ── 2026-11-13 추가: 여러 줄 글씨·샷 넘기기 키·붙인 그림·참조·버전 상태·룩업 자동 ─────────


def _start_text(win: Any, x: float = 0.3, y: float = 0.3) -> Any:
    win._set_tool("text")
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None
    pos = QPointF(r[0] + r[2] * x, r[1] + r[3] * y).toPoint()
    QTest.mouseClick(layer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert layer.is_editing_text()
    return layer


def test_text_box_breaks_lines_with_shift_or_alt_enter(win: Any) -> None:
    layer = _start_text(win)
    QTest.keyClicks(layer._edit, "edge")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert layer.is_editing_text()  # 줄만 바뀌고 아직 쓰는 중
    QTest.keyClicks(layer._edit, "grain")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
    QTest.keyClicks(layer._edit, "more")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return)  # Enter 만 누르면 확정
    assert not layer.is_editing_text()
    shapes = layer.doc().shapes()
    assert len(shapes) == 1 and shapes[0]["text"] == "edge\ngrain\nmore"
    assert win._panel.memo_text() == "edge\ngrain\nmore"

    # 여러 줄 글을 고치면 메모 칸의 그 묶음만 바뀌고, 지우면 그 묶음만 빠진다
    win._panel.set_memo_text("앞줄\nedge\ngrain\nmore\n뒷줄")
    layer.doc().update(shapes[0]["id"], text="edge\nfixed")
    win._on_doc_changed()
    assert win._panel.memo_text() == "앞줄\nedge\nfixed\n뒷줄"
    layer.doc().remove(shapes[0]["id"])
    win._on_doc_changed()
    assert win._panel.memo_text() == "앞줄\n뒷줄"


def test_escape_drops_the_text_being_typed(win: Any) -> None:
    layer = _start_text(win)
    QTest.keyClicks(layer._edit, "drop me")
    QTest.keyClick(layer._edit, Qt.Key.Key_Escape)
    assert not layer.is_editing_text() and layer.doc().is_empty()


def test_multi_line_text_is_painted_and_can_be_picked(win: Any) -> None:
    from bpe.core.confirm_annotations import KIND_TEXT, make_shape

    doc = win._layer.doc()
    two = doc.add(make_shape(KIND_TEXT, win._frame_start, [(0.1, 0.1)], text="one\ntwo"))
    one = doc.add(make_shape(KIND_TEXT, win._frame_start + 1, [(0.5, 0.5)], text="one"))
    win._on_doc_changed()
    images = win._render_note_images()
    assert len(images) == 2 and all(Path(p).is_file() for p in images)
    win._remove_files(images)
    # 두 줄 글은 둘째 줄 자리를 눌러도 골라진다(한 줄 글은 그 자리에서 안 골라진다)
    second_row = 0.03 * 1.4 * 1.6
    assert doc.hit_test(win._frame_start, 0.11, 0.1 + second_row) == two
    assert doc.hit_test(win._frame_start + 1, 0.51, 0.5 + second_row) != one


def test_page_keys_move_between_shots_and_buttons_sit_under_status(
    win: Any, monkeypatch: Any
) -> None:
    rows = [
        {
            "task_id": i,
            "shot_code": f"S_00{i}0",
            "task_status": "sv",
            "uploader_type": "Group",
            "uploader_name": "vendor A",
        }
        for i in (1, 2, 3)
    ]
    win._task = dict(rows[1])
    win._drawer._set_group("SV_Confirm (vendor)")
    win._drawer.set_rows(rows)
    opened: list = []
    monkeypatch.setattr(win, "_open_task", opened.append)
    QTest.keyClick(win, Qt.Key.Key_PageDown)
    QTest.keyClick(win, Qt.Key.Key_PageUp)
    assert [r["task_id"] for r in opened] == [3, 1]
    win._panel._btn_next.click()
    assert opened[-1]["task_id"] == 3
    assert not hasattr(win, "_btn_prev")  # 위쪽의 작은 버튼은 없앴다


def test_send_waits_three_seconds() -> None:
    from bpe.gui.confirm import confirm_window as cw

    assert cw._SEND_DELAY_SECS == 3


def test_pasted_image_is_attached_kept_in_the_draft_and_removable(
    win: Any, tmp_app_dir: Path, monkeypatch: Any
) -> None:
    from PySide6.QtGui import QColor, QImage

    img = QImage(40, 30, QImage.Format.Format_RGB888)
    img.fill(QColor("#336699"))
    win._panel._memo_edit.image_pasted.emit(img)
    win._panel._memo_edit.image_pasted.emit(img)
    assert len(win._pasted) == 2 and all(Path(p).is_file() for p in win._pasted)
    assert all(str(tmp_app_dir) in p for p in win._pasted)  # 초안 폴더 안에만 만든다
    assert win._panel.pasted_count() == 2
    assert "붙인 그림 2장" in win._panel._attach.text()

    win._remove_pasted(0)
    assert len(win._pasted) == 1 and win._panel.pasted_count() == 1
    kept = win._pasted[0]

    # 초안을 저장했다가 다시 읽어도 붙인 그림이 남아 있다
    win._save_draft()
    win._pasted = []
    win._load_draft()
    assert win._pasted == [kept]

    # 보낼 때 참조 사람·버전과 함께 간다
    sent: dict = {}

    class _Worker:
        def __init__(self, fn: Any) -> None:
            sent["fn"] = fn
            self.finished = self.error = self

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Worker)
    captured: dict = {}
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.open_submit_session", lambda: (object(), {"name": "me"})
    )
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.submit_confirm", lambda _sg, **kw: captured.update(kw)
    )
    win._panel.add_cc_user({"id": 7, "name": "lead"})
    win._task = {"shot_id": 1, "project_id": 1, "task_id": 5, "latest_version_id": 9}
    win._loaded_task_id = 5  # 이 태스크의 영상이 열려 있다
    win._submit("retake")
    sent["fn"]()
    assert captured["attachment_paths"] == [kept]
    assert captured["addressings_cc"] == [{"type": "HumanUser", "id": 7}]
    assert captured["version_id"] == 9
    win._workers.clear()


def test_after_sending_the_note_list_reloads_and_both_statuses_are_reported(
    win: Any, monkeypatch: Any
) -> None:
    from bpe.shotgrid.confirm_submit import ConfirmSubmitResult

    reloads: list = []
    monkeypatch.setattr(win, "_load_sg_context", lambda: reloads.append(1))
    win._task = {"shot_id": 1, "project_id": 1, "task_status": "sv"}
    win._last_status_code = "cfrm"
    win._panel.add_cc_user({"id": 7, "name": "lead"})
    ok = ConfirmSubmitResult(
        True, True, 55, "", True, "", True, True, "",
        version_needed=True, version_ok=True, version_count=2,
    )  # fmt: skip
    win._on_submitted(ok, [], [])
    text = win._panel._result.text()
    assert "노트 보냄" in text and "태스크 상태 cfrm" in text
    assert "버전 상태 cfrm 로 바꿈(2개)" in text
    assert reloads == [1]  # 방금 보낸 노트가 바로 보이게 다시 읽는다
    assert win._panel.cc_users() == []  # 보낸 뒤 참조는 비운다
    assert win._task["task_status"] == "cfrm"

    # 버전 상태만 실패 → 다시 바꾸기 버튼이 뜨고, 노트는 다시 읽지 않는다
    bad = ConfirmSubmitResult(
        True, True, 55, "", True, "", True, True, "",
        version_needed=True, version_ok=False, version_count=0, version_error="no permission",
    )  # fmt: skip
    win._on_submitted(bad, [], [])
    assert "버전 상태 실패: no permission" in win._panel._result.text()
    assert win._panel._btn_retry.isVisibleTo(win._panel)
    assert reloads == [1]


def test_lut_comes_from_the_preset_and_only_the_plate_gets_it(win: Any, tmp_path: Path) -> None:
    from bpe.core.confirm_standard import ProjectStandard

    rows = [f"0.0 {g}.0 {b}.0" for b in (0, 1) for g in (0, 1) for _r in (0, 1)]
    cube = tmp_path / "preset_look.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "\n".join(rows) + "\n", encoding="utf-8")
    win._standard = ProjectStandard(
        "P", 24.0, (), None, "", "default / sRGB", ("bt709",), "rec709", lut_path=str(cube)
    )
    assert win._lut is None
    win._load_project_lut()
    assert win._lut is not None and win._lut_on and win._lut_path == str(cube)
    b = win._bufs
    assert not win._look_baked(b[KEY_ORG])  # 원본에는 씌운다
    # 시험 영상의 현재버전은 원본과 같은 그림이라, 그림으로 가리면 "로그"다 → 같이 씌운다
    assert win._look_measured.get(KEY_CUR) is False and win._lut_applies(b[KEY_CUR])

    # 그림으로 못 가린 판은 예전 규칙으로: 프리셋이 룩을 입혀 내보내면 작업본·편집본은 그대로
    win._look_measured = {}
    win._show_standard()
    assert win._look_baked(b[KEY_CUR]) and win._look_baked(b[KEY_PREV])
    assert win._look_baked(b[KEY_EDIT])
    look = win._panel._v_look.text()
    assert "preset_look" in look and "씌움" in look and "현재버전 그대로" in look

    # 끈 상태는 다음 샷에서도 그대로, 못 읽는 파일은 한 번만 알린다
    win._lut_on = False
    win._load_project_lut()
    assert not win._lut_on
    win._standard = win._standard._replace(lut_path=str(tmp_path / "missing.cube"))
    win._load_project_lut()
    assert win._lut_path == str(cube) and win._lut_failed.endswith("missing.cube")


def test_shot_folder_and_shotgrid_buttons(win: Any, shot: Path, monkeypatch: Any) -> None:
    opened: list = []
    monkeypatch.setattr(
        "bpe.gui.confirm.confirm_window.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()),
    )
    win._sync_all()
    assert win._btn_shot_dir.isEnabled()
    assert not win._btn_sg.isEnabled()  # 샷그리드 정보 없이 파일만 연 상태
    win._open_shot_folder()
    assert opened and Path(opened[0]) == shot
    win._task = {"shot_id": 321}
    win._sync_all()
    assert win._btn_sg.isEnabled()
    went: list = []
    monkeypatch.setattr("bpe.gui.shotgrid_open_shot.open_shot_canvas_in_browser", went.append)
    win._open_shot_in_shotgrid()
    assert went == [321]


def test_look_is_judged_from_the_picture_and_can_be_overridden(win: Any, tmp_path: Path) -> None:
    import struct

    from bpe.core.confirm_look import sample_grid, sample_trilinear
    from bpe.core.confirm_standard import ProjectStandard

    # 대비를 크게 올리는 룩업(2칸): 어두우면 0, 밝으면 1 쪽으로
    rows = [f"{r}.0 {g}.0 {b}.0" for b in (0, 1) for g in (0, 1) for r in (0, 1)]
    cube = tmp_path / "look.cube"
    cube.write_text(
        "LUT_3D_SIZE 2\nDOMAIN_MIN 0.3 0.3 0.3\nDOMAIN_MAX 0.6 0.6 0.6\n" + "\n".join(rows)
    )
    b = win._bufs
    org = b[KEY_ORG]
    w, h = org.size
    # 원본을 로그처럼 가운데 밝기로 몰린 그림으로 바꿔 놓는다
    flat = b"".join(
        struct.pack(
            "<3H", 22000 + (i * 97) % 14000, 22000 + (i * 61) % 14000, 22000 + (i * 31) % 14000
        )
        for i in range(w * h)
    )
    org.frames[0] = flat
    win._standard = ProjectStandard("P", 24.0, (), None, "", "default / sRGB", (), "rec709")
    win._apply_lut_file(str(cube), remember=False)
    lut = win._lut
    baked = b"".join(
        struct.pack("<3H", *(int(round(c * 65535)) for c in sample_trilinear(lut, p)))
        for p in sample_grid(flat, w, h, cols=w, rows=h)
    )
    # 현재버전은 로그 그대로(외주 납품), 이전버전은 룩이 입혀진 것
    b[KEY_CUR].frames[0] = flat
    b[KEY_PREV].frames[0] = baked
    # 샷을 열 때 먼저 읽어 둔 원본 첫 장(여기서는 바꿔 놓은 그림)과 견준다
    win._plate_probe = sample_grid(flat, w, h)
    win._look_measured, win._look_tried = {}, set()
    win._measure_looks()
    assert win._look_measured[KEY_CUR] is False and win._look_measured[KEY_PREV] is True
    # 먼저 읽어 둔 장이 없으면 올라온 원본 프레임으로 견줘도 같은 답이 나온다
    win._plate_probe = None
    win._look_measured, win._look_tried = {}, set()
    win._measure_looks()
    assert win._look_measured[KEY_CUR] is False and win._look_measured[KEY_PREV] is True
    assert win._lut_applies(b[KEY_ORG]) and win._lut_applies(b[KEY_CUR])  # 로그 판에는 씌운다
    assert not win._lut_applies(b[KEY_PREV])  # 룩 입혀진 판에는 안 씌운다 — 두 번 안 씌워진다
    look = win._panel._v_look.text()
    assert "현재버전 씌움" in look and "이전버전 그대로" in look

    # 자동 판단이 틀렸으면 지금 보는 판만 바꾼다
    win._show_buffer(KEY_PREV)
    assert not win._btn_lut_here.isChecked()
    QTest.keyClick(win, Qt.Key.Key_L, Qt.KeyboardModifier.ShiftModifier)
    assert win._lut_applies(b[KEY_PREV]) and win._btn_lut_here.isChecked()
    assert win._lut_applies(b[KEY_CUR])  # 다른 판은 그대로
    win._btn_lut_here.click()
    assert not win._lut_applies(b[KEY_PREV])

    # L 은 전체 끄기 — 어느 판에도 안 씌운다
    QTest.keyClick(win, Qt.Key.Key_L)
    assert not win._lut_applies(b[KEY_ORG]) and not win._lut_applies(b[KEY_CUR])


def test_note_pictures_are_fetched_after_notes_arrive(win: Any, monkeypatch: Any) -> None:
    jobs: list = []

    class _Worker:
        def __init__(self, fn: Any) -> None:
            jobs.append(fn)
            self.finished = self.error = self

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Worker)
    asked: list = []
    monkeypatch.setattr("bpe.shotgrid.client.get_default_sg", lambda: object())
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_context.note_images", lambda _sg, ids: asked.append(ids) or {}
    )
    notes = [
        {"note_id": 7, "content": "a", "timestamp": "2026-11-13 10:00"},
        {"kind": "version", "content": "b", "timestamp": "2026-11-13 09:00"},
    ]
    win._on_notes(notes, win._load_token)
    assert len(jobs) == 1
    jobs[0]()
    assert asked == [[7]]  # 노트만(버전 글은 빼고) 그림을 찾는다
    win._on_note_images({7: []}, win._load_token)
    win._on_note_images({7: []}, win._load_token - 1)  # 다른 샷으로 넘어간 뒤 온 답은 버린다
    win._workers.clear()


def test_annotation_mode_opens_the_plate_and_sends_a_note_only(
    win: Any, shot: Path, qtbot: Any, monkeypatch: Any
) -> None:
    from bpe.core.confirm_list import MODE_ANNOTATION, MODE_CONFIRM

    monkeypatch.setattr(win._drawer, "load_projects", lambda: None)
    monkeypatch.setattr(win, "_ensure_status_styles", lambda: None)
    win._set_mode(MODE_ANNOTATION)
    # 모드가 바뀌면 열려 있던 샷은 내려놓고 목록이 열린다
    assert win.is_annotation() and win._drawer.isVisible() and win._drawer.mode() == MODE_ANNOTATION
    assert win._count == 0 and not win._bufs[KEY_CUR].available
    assert (
        win._mode_btns[MODE_ANNOTATION].isChecked() and not win._mode_btns[MODE_CONFIRM].isChecked()
    )
    assert win._panel.is_annotation()
    win._toggle_drawer()

    plate = shot / "plate" / "org" / "v001" / "mov" / "SHOT_A_org_v001.mov"
    who = {"type": "HumanUser", "id": 3, "name": "김작업"}
    task = {
        "task_id": 5, "shot_id": 9, "project_id": 1, "shot_code": "SHOT_A", "task_status": "wtg",
        "task_statuses": ["wtg", "assign"], "task_assignees": [who],
        "tasks": [
            {"task_id": 5, "task_content": "comp", "task_status": "wtg"},
            {"task_id": 6, "task_content": "roto", "task_status": "assign"},
        ],
    }  # fmt: skip
    monkeypatch.setattr(win, "_load_sg_context", lambda: None)
    win.open_movie(str(plate), task)
    qtbot.waitUntil(lambda: len(win._bufs[KEY_CUR].frames) >= 6, timeout=30000)

    cur = win._bufs[KEY_CUR]
    assert cur.path == plate and cur.title == "ORG plate" and cur.version_label == "v001"
    assert not win._bufs[KEY_ORG].available and not win._bufs[KEY_PREV].available
    assert win._bufs[KEY_EDIT].available
    assert win._shot_root == shot
    # 판 버튼은 원본과 edit 만 보인다
    assert win._buf_btns[KEY_CUR].isVisibleTo(win) and win._buf_btns[KEY_EDIT].isVisibleTo(win)
    assert not win._buf_btns[KEY_ORG].isVisibleTo(win)
    assert not win._buf_btns[KEY_PREV].isVisibleTo(win)
    assert win._buf_btns[KEY_CUR].label() == "ORG plate"
    assert win._checks == [] and not win._banner.isVisible()  # 납품 규격 검사는 하지 않는다
    assert not win._look_baked(cur)  # 원본은 로그 — 룩업을 씌운다
    assert win._ver_chip.text() == "ORG plate v001"
    assert win._who.text() == "comp wtg · roto assign" and win._status_lbl.text() == "wtg · assign"
    assert win._panel.can_send()

    # 아무것도 안 남기고 누르면 보내지 않는다
    win._on_note_requested()
    assert not win._send_timer.isActive() and "남긴 뒤" in win._panel._result.text()
    win._panel.set_memo_text("하늘 교체 범위 확인")
    win._on_note_requested()
    assert win._send_timer.isActive() and win._pending_status == ""
    assert "상태는 그대로" in win._pending_summary() and "담당 1명" in win._pending_summary()
    win._cancel_pending()

    # 보내는 값: 상태 없음, 버전 없음, 받는 사람 = 그 샷 태스크 담당
    sent: dict = {}

    class _Now:
        def __init__(self, fn: Any) -> None:
            self.finished = self.error = self
            self._fn = fn

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            self._fn()

        def isRunning(self) -> bool:  # noqa: N802
            return False

    def _fake_submit(_sg: Any, **kw: Any) -> None:
        sent.update(kw)

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Now)
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.open_submit_session", lambda: (object(), {"name": "SV"})
    )
    monkeypatch.setattr("bpe.shotgrid.confirm_submit.submit_confirm", _fake_submit)
    # 샷그리드에 edit·org 버전이 하나도 없는 샷 — 노트는 샷에만 붙는다
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.guide_note_target", lambda *_a, **_k: ("", None)
    )
    win._submit("")
    assert sent["status_code"] == "" and sent["version_id"] is None and sent["shot_id"] == 9
    assert sent["note_task_id"] is None  # 붙일 버전이 없으면 걸 태스크도 없다
    assert sent["empty_note_text"] == ""  # Annotation 노트에는 쓴 글만
    assert sent["content"] == "하늘 교체 범위 확인"
    assert sent["subject"] == "SV's Note on SHOT_A"
    assert sent["addressings_to"] == [{"type": "HumanUser", "id": 3}]
    win._submit_busy = False

    # Confirm 으로 돌아가면 상태 버튼과 네 판 버튼이 돌아온다
    win._set_mode(MODE_CONFIRM)
    win._toggle_drawer()
    assert not win.is_annotation() and win._bufs[KEY_CUR].title == "현재버전"
    assert win._buf_btns[KEY_ORG].isVisibleTo(win) and win._panel._btn_retake.isVisibleTo(win)


def test_other_shot_frame_lands_in_pasted_images_with_a_memo_line(win: Any) -> None:
    from PySide6.QtGui import QColor, QImage

    img = QImage(64, 36, QImage.Format.Format_RGB888)
    img.fill(QColor("#335577"))
    win._panel.set_memo_text("하늘 톤은 아래 샷처럼")
    win._on_ref_frame(img, "참고: S_0090 comp v003 1012")
    assert len(win._pasted) == 1 and win._panel.pasted_count() == 1
    assert win._panel.memo_text().splitlines() == [
        "하늘 톤은 아래 샷처럼",
        "참고: S_0090 comp v003 1012",
    ]
    # 창을 띄우면 지금 샷의 에피소드 앞머리가 미리 적혀 있다
    win._task = {"shot_code": "ep02_s048_0010", "project_code": "PROJ"}
    win._open_ref_dialog()
    assert win._ref_dialog is not None and win._ref_dialog._shot_edit.text() == "ep02_"
    win._ref_dialog.close()
    win._remove_pasted(0)


def test_sequence_plays_cuts_in_a_row_and_pause_opens_the_cut(
    win: Any, shot: Path, qtbot: Any, monkeypatch: Any
) -> None:
    renders = shot / "comp" / "devl" / "renders"
    movies = {1: renders / "SHOT_A_comp_v001.mov", 2: renders / "SHOT_A_comp_v002.mov"}
    monkeypatch.setattr(
        "bpe.gui.confirm.confirm_window._resolve_task_movie",
        lambda row: str(movies[row["task_id"]]),
    )
    monkeypatch.setattr(win, "_load_sg_context", lambda: None)
    rows = [
        {"task_id": 2, "shot_id": 12, "project_id": 1, "shot_code": "S_0020", "task_status": "sv"},
        {"task_id": 1, "shot_id": 11, "project_id": 1, "shot_code": "S_0010", "task_status": "sv"},
    ]
    win._start_sequence(rows)
    assert win._strip.isVisible() and "준비" in win._busy.text()
    qtbot.waitUntil(lambda: win.is_sequence() and win._seq_playing, timeout=30000)
    seq = win._seq
    assert [c.shot for c in seq.cuts] == ["S_0010", "S_0020"]  # 샷 이름 순
    assert win._strip.cut_names() == ["S_0010", "S_0020"] and "2컷" in win._strip.note()
    assert not win._bufs[KEY_CUR].available  # 재생 중에는 열린 샷이 없다(줄인 그림만 돈다)
    assert not win._panel.can_send() and not win._busy.isVisible()
    qtbot.waitUntil(lambda: all(len(c.frames) == 6 for c in seq.cuts), timeout=30000)

    # 컷 경계를 넘으면 머리 줄·알림 글이 그 컷으로 바뀐다
    qtbot.waitUntil(lambda: win._seq_cut == 1, timeout=10000)
    assert win._task["shot_code"] == "S_0020" and "S_0020" in win._crumb.text()
    assert win._hud.text().startswith("2/2") and win._panel.nav_text() == "2 / 2"
    # 끝에서 처음으로 돌아온다(반복)
    qtbot.waitUntil(lambda: win._seq_cut == 0, timeout=10000)

    # 멈추면 그 컷이 평소처럼 열리고, 멈춘 프레임에 서 있다
    win._play_timer.stop()
    assert win._seq_show(9)  # 둘째 컷의 넷째 프레임
    win._toggle_play()
    assert not win._seq_playing and win.is_sequence()
    cur = win._bufs[KEY_CUR]
    qtbot.waitUntil(lambda: cur.available and win._index == 3 and 3 in cur.frames, timeout=30000)
    assert cur.path == movies[2] and win._strip.isVisible() and not win._busy.isVisible()
    assert win._bufs[KEY_ORG].available  # 판 바꾸기도 된다
    win._step(1)
    assert win._index == 4 and win._strip.position() == 10  # 컷 띠가 따라온다

    # 이전 샷 = 이어 보는 컷 안에서만
    win._nav_shot(-1)
    qtbot.waitUntil(lambda: win._bufs[KEY_CUR].path == movies[1], timeout=30000)
    assert win._index == 0 and win._panel.nav_text() == "1 / 2"
    win._nav_shot(-1)  # 더 앞은 없다
    assert win._bufs[KEY_CUR].path == movies[1]

    # 다시 재생하면 보던 자리부터 잇고, 그리기 도구를 고르면 멈춘다
    win._set_index(2)
    win._toggle_play()
    assert win._seq_playing and win._seq_pos == 2 and not win._bufs[KEY_CUR].available
    win._play_timer.stop()
    win._set_tool("rect")
    assert not win._seq_playing
    qtbot.waitUntil(lambda: win._bufs[KEY_CUR].available, timeout=30000)

    # 닫으면 띠가 사라지고 열려 있던 컷은 그대로다
    win._close_sequence()
    assert not win.is_sequence() and not win._strip.isVisible()
    assert win._bufs[KEY_CUR].available and seq.cuts[0].frames == {}


# ── 2026-11-14 추가: 보내기가 다른 샷으로 가거나 쓰던 글이 사라지는 길 막기 ─────────────


class _IdleWorker:
    """아무 일도 안 하는 가짜 워커 — 서버에서 영상을 찾는 중인 상태를 만든다."""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.finished = self.error = self

    def connect(self, *_a: Any) -> None:
        pass

    def start(self) -> None:
        pass

    def isRunning(self) -> bool:  # noqa: N802
        return False


def _as_task(win: Any, task_id: int, shot: str) -> None:
    """지금 열려 있는 영상을 샷그리드의 한 샷(태스크)으로 본다."""
    win._task = {
        "task_id": task_id, "shot_id": task_id + 100, "project_id": 1, "shot_code": shot,
        "task_status": "sv", "latest_version_id": task_id + 200,
        "latest_version_code": f"{shot}_comp_v002",
    }  # fmt: skip
    win._loaded_task_id = task_id
    win._sync_all()


def _sent(**kw: Any) -> Any:
    from bpe.shotgrid.confirm_submit import ConfirmSubmitResult

    base = dict(
        note_needed=True, note_ok=True, note_id=55, note_error="", attachment_ok=True,
        attachment_error="", status_needed=True, status_ok=True, status_error="",
        version_needed=True, version_ok=True, version_count=1,
    )  # fmt: skip
    base.update(kw)
    return ConfirmSubmitResult(**base)


def test_picking_another_shot_cancels_the_pending_send(win: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _IdleWorker)
    _as_task(win, 5, "S_A")
    win._panel.set_memo_text("A 샷 지적")
    win._on_status_requested("retake")
    assert win._send_timer.isActive()

    # 3초 세는 중에 다른 샷을 고른다 — 새 샷의 영상은 아직 서버에서 찾는 중
    win._open_task({"task_id": 7, "shot_id": 107, "project_id": 1, "shot_code": "S_B"})
    assert not win._send_timer.isActive() and win._pending_status == ""
    assert win._task["shot_code"] == "S_B" and win._panel.memo_text() == "A 샷 지적"

    # 머리 줄은 새 샷인데 화면의 메모·그림은 앞 샷 것 — 이 상태로는 보낼 수 없다
    win._sync_all()
    assert not win._panel.can_send()
    win._on_status_requested("retake")
    assert not win._send_timer.isActive()
    win._submit("retake")
    assert not win._submit_busy and "보내지 않았습니다" in win._panel._result.text()

    # 새 샷의 영상을 못 찾아도 그대로 못 보낸다
    win._on_task_resolved("", win._load_token, dict(win._task))
    win._sync_all()
    assert not win._panel.can_send()


def test_result_of_a_shot_we_left_does_not_touch_the_open_shot(
    win: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    reloads: list = []
    monkeypatch.setattr(win, "_load_sg_context", lambda: reloads.append(1))
    # A 를 보내는 중에 B 로 넘어와 메모를 쓰고 있다
    _as_task(win, 7, "S_B")
    win._panel.set_memo_text("B 샷에 쓰는 중")
    _start_text(win)
    QTest.keyClicks(win._layer._edit, "b note")
    QTest.keyClick(win._layer._edit, Qt.Key.Key_Return)
    assert len(win._layer.doc().shapes()) == 1
    old_draft = tmp_path / "S_A_comp_v002.json"
    old_draft.write_text("{}", encoding="utf-8")
    ticket = {
        "task_id": 5, "shot": "S_A", "draft": old_draft, "retry": False, "code": "retake",
        "task": {"task_id": 5, "shot_id": 105, "project_id": 1, "shot_code": "S_A"},
    }  # fmt: skip

    win._on_submitted(_sent(), [], [], ticket)
    # B 의 메모·그림·상태는 그대로다
    assert "B 샷에 쓰는 중" in win._panel.memo_text() and len(win._layer.doc().shapes()) == 1
    assert win._task["task_status"] == "sv" and reloads == []
    # 결과 글에는 어느 샷 것인지 적히고, A 의 초안은 지워져 다시 열어도 보낸 글이 안 나온다
    text = win._panel._result.text()
    assert text.startswith("S_A") and "노트 보냄" in text and "retake" in text
    assert not old_draft.exists() and not win._submit_busy

    # 보내기에 실패한 것도 어느 샷인지 알린다(A 의 글은 초안에 남아 있다)
    old_draft.write_text("{}", encoding="utf-8")
    win._on_submit_error("timeout", [], ticket)
    assert win._panel._result.text().startswith("S_A") and old_draft.exists()
    assert "B 샷에 쓰는 중" in win._panel.memo_text()


def test_text_being_typed_goes_out_with_the_note(win: Any) -> None:
    _as_task(win, 5, "S_A")
    layer = _start_text(win)
    QTest.keyClicks(layer._edit, "edge here")
    # Enter 를 안 치고 바로 상태 버튼을 누른다
    QTest.mouseClick(win._panel._btn_retake, Qt.MouseButton.LeftButton)
    assert win._send_timer.isActive()
    assert not layer.is_editing_text()
    shapes = layer.doc().shapes()
    assert len(shapes) == 1 and shapes[0]["text"] == "edge here"
    assert "edge here" in win._panel.memo_text()
    assert "메모 1줄" in win._pending_summary()
    win._cancel_pending()


def test_retry_goes_to_the_shot_it_was_sent_for(win: Any, monkeypatch: Any) -> None:
    _as_task(win, 7, "S_B")
    win._panel.set_memo_text("B 샷에 쓰는 중")
    task_a = {"task_id": 5, "shot_id": 105, "project_id": 1, "shot_code": "S_A"}
    ticket = {
        "task_id": 5, "shot": "S_A", "draft": None, "retry": False, "code": "retake",
        "task": task_a,
    }  # fmt: skip
    # A 의 노트는 갔는데 상태 바꾸기만 실패했다(결과는 B 화면에 도착)
    win._on_submitted(_sent(status_ok=False, status_error="no permission"), [], [], ticket)
    assert win._panel._btn_retry.isVisibleTo(win._panel)
    calls: list = []
    monkeypatch.setattr(win, "_submit", lambda *a, **k: calls.append((a, k)))
    win._retry_status_only()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "retake" and kwargs["existing_note_id"] == 55
    assert kwargs["task"]["task_id"] == 5  # 지금 열린 B 가 아니라 A 의 상태를 다시 바꾼다


def test_retry_keeps_what_was_typed_meanwhile(win: Any) -> None:
    _as_task(win, 5, "S_A")
    win._panel.set_memo_text("다시 누르기 전에 더 쓴 글")
    ticket = {
        "task_id": 5, "shot": "S_A", "draft": None, "retry": True, "code": "retake",
        "task": dict(win._task),
    }  # fmt: skip
    win._on_submitted(_sent(), [], [], ticket)
    assert win._panel.memo_text() == "다시 누르기 전에 더 쓴 글"  # 상태만 다시 바꾼 것이다
    assert "태스크 상태 retake" in win._panel._result.text()
    assert "노트 보냄" not in win._panel._result.text()
    assert win._task["task_status"] == "retake"


def test_pictures_stay_when_their_upload_failed(win: Any, tmp_path: Path) -> None:
    _as_task(win, 5, "S_A")
    layer = _start_text(win)
    QTest.keyClicks(layer._edit, "edge")
    QTest.keyClick(layer._edit, Qt.Key.Key_Return)
    pasted = tmp_path / "paste.png"
    pasted.write_bytes(b"x")
    win._pasted = [str(pasted)]
    win._panel.set_pasted_images(win._pasted)
    ticket = {
        "task_id": 5, "shot": "S_A", "draft": None, "retry": False, "code": "retake",
        "task": dict(win._task),
    }  # fmt: skip
    failed = _sent(attachment_ok=False, attachment_error="upload failed")
    win._on_submitted(failed, [], [str(pasted)], ticket)
    # 글은 갔지만 그림은 안 올라갔다 — 그린 그림과 붙인 그림은 그대로 남는다
    assert len(layer.doc().shapes()) == 1 and pasted.exists()
    assert win._pasted == [str(pasted)] and win._panel.pasted_count() == 1
    text = win._panel._result.text()
    assert "그림 실패: upload failed" in text and "남겨" in text

    # 제대로 간 뒤에는 전처럼 비운다
    win._on_submitted(_sent(), [], [str(pasted)], ticket)
    assert layer.doc().shapes() == [] and not pasted.exists() and win._pasted == []
    assert win._panel.memo_text() == ""


# ── 2026-11-16 추가: 지난 Note 글 복사 — 누른 뒤에도 단축키가 듣는다 ──────────────────


def test_note_text_copies_with_ctrl_c_and_arrow_keys_still_step(win: Any, monkeypatch: Any) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QApplication, QScrollArea

    from bpe.gui.confirm import side_panel as sp

    class _Clip:
        value = ""

        def setText(self, text: str) -> None:  # noqa: N802
            self.value = text

    clip = _Clip()
    monkeypatch.setattr(sp.QGuiApplication, "clipboard", staticmethod(lambda: clip))
    path = "W:/vfx/project_2025/SHOT_A/comp/ref_v001.mov"
    win._panel.set_past_notes(
        [{"version_code": "SHOT_A_comp_v001", "timestamp": "2026-11-10", "content": path}], ""
    )
    QApplication.processEvents()
    row = win._panel._past_rows[0]

    # Note 줄을 눌러도 초점이 그 줄이나 스크롤 칸으로 가지 않아 ← → 가 프레임을 넘긴다
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(14, row.height() // 2))
    focused = QApplication.focusWidget()
    assert focused is not row and not isinstance(focused, QScrollArea)
    before = win._index
    QTest.keyClick(focused or win, Qt.Key.Key_Right)
    assert win._index == before + 1

    # 끌어 고른 글은 Ctrl+C 로 복사된다(경로에 안 보이는 글자가 섞이지 않는다)
    doc = QTextDocument()
    doc.setHtml(row.text())
    row.setSelection(0, len(doc.toPlainText()))
    QTest.keyClick(win, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert path in clip.value and chr(0x200B) not in clip.value


# ── 2026-11-16 추가: 샷 폴더·샷그리드 버튼은 프로그램 아이콘(탐색기 · 내 작업 탭과 같은 그림) ──


def test_shot_folder_and_shotgrid_buttons_use_app_icons(win: Any) -> None:
    import sys

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QPushButton

    from bpe.gui.confirm import confirm_window as cw
    from bpe.gui.shotgrid_open_shot import shotgrid_open_shot_icon_png_path

    assert not win._btn_shot_dir.icon().isNull() and not win._btn_sg.icon().isNull()
    # 샷그리드 그림은 내 작업 탭의 「ShotGrid에서 열기」와 같은 파일에서 온다
    assert shotgrid_open_shot_icon_png_path().is_file() and not cw._shotgrid_icon().isNull()
    assert win._btn_sg.iconSize().width() == cw._APP_ICON_PX
    if sys.platform == "win32":
        assert not cw._explorer_icon().isNull()
        assert win._btn_shot_dir.iconSize().width() == cw._APP_ICON_PX
    # 아이콘을 못 읽는 환경에서는 원래 선 그림이 그대로 남는다
    plain = QPushButton()
    cw.style.set_icon(plain, "shot_dir", size=16)
    cw._use_app_icon(plain, QIcon())
    assert not plain.icon().isNull() and plain.iconSize().width() == 16
    # 「영상 파일 열기」는 말한 버튼이 아니라 그대로 선 그림이다
    assert win._btn_open.iconSize().width() == 16


# ── 2026-11-16 추가: 글 칸은 폭이 고정이고 넘치면 줄이 바뀐다 · 도형과 글은 따로 ─────────


def test_text_box_keeps_its_width_and_wraps_long_text(win: Any) -> None:
    from PySide6.QtWidgets import QApplication

    layer = _start_text(win)
    edit = layer._edit
    QApplication.processEvents()
    width, x = edit.width(), edit.x()
    one_line = edit.height()
    QTest.keyClicks(edit, "a")
    QApplication.processEvents()
    short = edit.height()  # 안내 글이 사라진 뒤의 한 줄 높이
    assert short <= one_line
    QTest.keyClicks(edit, "edge cleanup needed here " * 8)
    QApplication.processEvents()
    assert edit.width() == width and edit.x() == x  # 글이 길어져도 옆으로 커지거나 밀리지 않는다
    assert edit.height() > short  # 대신 아래로 줄이 바뀐다
    # 칸 안에서 실제로 줄이 바뀐 수만큼 높이가 잡혀 글이 가려지지 않는다
    doc = edit.document()
    block, real = doc.begin(), 0
    while block.isValid():
        real += max(1, block.layout().lineCount())
        block = block.next()
    fm = edit.fontMetrics()
    assert edit.height() >= fm.lineSpacing() * (real - 1) + fm.height()
    QTest.keyClick(edit, Qt.Key.Key_Return)
    shape = layer.doc().shapes()[-1]
    assert "\n" not in shape["text"]  # 저장되는 글에는 줄 바꿈을 끼워 넣지 않는다(메모 줄은 원문)
    assert win._panel.memo_text() == shape["text"]


def test_long_text_wraps_the_same_on_screen_and_in_the_note_picture(win: Any) -> None:
    from bpe.core.confirm_annotations import KIND_TEXT, TEXT_WRAP_WIDTH, make_shape
    from bpe.gui.confirm.annotation_layer import text_box, wrap_rows

    text = "edge cleanup needed around the helmet and the left shoulder strap " * 2
    shape = make_shape(KIND_TEXT, win._frame_start, [(0.1, 0.1)], text=text.strip())
    small = (0.0, 0.0, 640.0, 360.0)
    big = (0.0, 0.0, 1920.0, 1080.0)
    rows = wrap_rows(shape, small, shape["text"])
    assert len(rows) >= 3 and "".join(rows).replace(" ", "") == shape["text"].replace(" ", "")
    assert rows == wrap_rows(shape, big, shape["text"])  # 창 크기·노트 그림과 무관하게 같은 줄
    _rows, box = text_box(shape, big, shape["text"])
    assert box.width() <= TEXT_WRAP_WIDTH * 1920 + 20  # 한 줄 폭은 영상 폭의 30% 를 넘지 않는다
    # 짧은 글은 한 줄 그대로, 직접 넣은 줄 바꿈은 지킨다
    assert wrap_rows(shape, big, "one\ntwo") == ["one", "two"]

    # 줄이 바뀐 글의 아랫줄을 눌러도 골라진다
    layer = win._layer
    sid = layer.doc().add(shape)
    win._on_doc_changed()
    r = win._view.image_rect()
    assert r is not None
    w, h = layer._text_extent(layer.doc().get(sid))
    assert w <= TEXT_WRAP_WIDTH + 0.12 and h > 0
    hit = layer.doc().hit_test(win._frame_start, 0.1 + w * 0.5, 0.1 + h * 0.9, layer._text_extent)
    assert hit == sid
    assert layer.doc().hit_test(win._frame_start, 0.1 + w + 0.2, 0.1, layer._text_extent) is None


def test_old_shape_with_text_can_still_be_edited_but_plain_shape_cannot(win: Any) -> None:
    from bpe.core.confirm_annotations import KIND_RECT, make_shape

    layer = win._layer
    r = win._view.image_rect()
    assert r is not None
    frame = win.frame_number()
    old = layer.doc().add(
        make_shape(KIND_RECT, frame, [(0.1, 0.1), (0.3, 0.3)], text="old note")
    )  # 예전 초안: 글이 달린 네모
    plain = layer.doc().add(make_shape(KIND_RECT, frame, [(0.6, 0.6), (0.8, 0.8)]))
    win._on_doc_changed()
    assert win._panel.memo_text() == "old note"  # 옛 글은 그대로 메모에 적힌다
    win._set_tool("select")
    none = Qt.KeyboardModifier.NoModifier

    def at(fx: float, fy: float) -> Any:
        return QPointF(r[0] + r[2] * fx, r[1] + r[3] * fy).toPoint()

    QTest.mouseDClick(layer, Qt.MouseButton.LeftButton, none, at(0.7, 0.7))
    assert not layer.is_editing_text() and layer.selected_id() == plain  # 글 없는 도형은 고르기만
    QTest.mouseDClick(layer, Qt.MouseButton.LeftButton, none, at(0.2, 0.2))
    assert layer.is_editing_text() and layer.selected_id() == old  # 글 달린 옛 도형은 고칠 수 있다
    QTest.keyClick(layer._edit, Qt.Key.Key_Escape)


# ── 2026-11-16 추가: 보낸 뒤 반응 — 머리 줄 상태 칸 강조 + 목록 줄에 바로 「보냄」 ──────────


def _list_rows(win: Any) -> None:
    win._drawer.set_rows(
        [
            {
                "task_id": tid,
                "shot_id": tid + 100,
                "shot_code": shot,
                "task_status": "sv",
                "uploader_type": "HumanUser",
                "uploader_name": "작업자",
                "latest_version_code": f"{shot}_comp_v002",
                "latest_version_created_at": "2026-11-10",
            }
            for tid, shot in ((5, "S_A"), (7, "S_B"))
        ]  # fmt: skip
    )


def _row_html_of(win: Any, task_id: int) -> str:
    return win._drawer._row_html(next(r for r in win._drawer._rows if r["task_id"] == task_id))


def _ticket(task_id: int, shot: str, code: str = "retake") -> Any:
    return {
        "task_id": task_id, "shot": shot, "draft": None, "retry": False, "code": code,
        "task": {"task_id": task_id, "shot_id": task_id + 100, "project_id": 1, "shot_code": shot},
    }  # fmt: skip


def test_sending_flashes_the_header_and_marks_the_list_row(win: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(win, "_load_sg_context", lambda: None)
    _list_rows(win)
    _as_task(win, 5, "S_A")
    assert win._status_lbl.text() == "sv" and "보냄" not in _row_html_of(win, 5)

    win._on_submitted(_sent(), [], [], _ticket(5, "S_A"))
    # 머리 줄 상태 칸이 무엇에서 무엇으로 바뀌었는지 잠깐 강조한다
    assert win._status_lbl.text() == "sv → retake" and win._flash_timer.isActive()
    assert "background" in win._status_lbl.styleSheet()
    # 목록의 그 줄은 다시 조회하지 않아도 바로 새 상태와 「보냄」
    assert "보냄" in _row_html_of(win, 5) and "retake" in _row_html_of(win, 5)
    assert "보냄" not in _row_html_of(win, 7)
    win._end_status_flash()
    assert win._status_lbl.text() == "retake" and "background" not in win._status_lbl.styleSheet()
    assert not win._flash_timer.isActive()

    # 그 샷을 목록에서 다시 열어도 머리 줄은 새 상태다
    again = win._with_sent_status({"task_id": 5, "shot_code": "S_A", "task_status": "sv"})
    assert again["task_status"] == "retake"
    assert win._with_sent_status({"task_id": 7, "task_status": "sv"})["task_status"] == "sv"


def test_result_of_a_shot_we_left_marks_only_its_list_row(win: Any) -> None:
    _list_rows(win)
    _as_task(win, 7, "S_B")  # A 를 보내는 중에 B 로 넘어왔다
    win._on_submitted(_sent(), [], [], _ticket(5, "S_A"))
    assert win._status_flash is None and win._status_lbl.text() == "sv"  # B 의 머리 줄은 그대로
    assert "보냄" in _row_html_of(win, 5) and "retake" in _row_html_of(win, 5)
    assert "보냄" not in _row_html_of(win, 7)


def test_note_only_send_says_note_sent(win: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(win, "_load_sg_context", lambda: None)
    _list_rows(win)
    _as_task(win, 5, "S_A")
    res = _sent(status_needed=False, version_needed=False)
    win._on_submitted(res, [], [], _ticket(5, "S_A", code=""))
    assert win._status_lbl.text() == "Note 보냄"  # 상태는 안 바꿨다 — Note 가 갔다는 것만 알린다
    assert "보냄" in _row_html_of(win, 5) and "sv" in _row_html_of(win, 5)
    win._end_status_flash()
    assert win._status_lbl.text() == "sv"

    # 보내기에 실패하면 강조도 표시도 없다
    _as_task(win, 7, "S_B")
    failed = _sent(note_ok=False, note_error="timeout", status_ok=False, version_ok=False)
    win._on_submitted(failed, [], [], _ticket(7, "S_B"))
    assert win._status_flash is None and "보냄" not in _row_html_of(win, 7)


# ── 2026-11-17 추가: Annotation 그림은 그린 영상에 딸리고, 노트는 edit·org 버전에 붙는다 ──────


def test_annotation_drawings_belong_to_the_video_they_were_drawn_on(
    win: Any, shot: Path, qtbot: Any, monkeypatch: Any
) -> None:
    from bpe.core.confirm_list import MODE_ANNOTATION

    monkeypatch.setattr(win._drawer, "load_projects", lambda: None)
    monkeypatch.setattr(win, "_ensure_status_styles", lambda: None)
    monkeypatch.setattr(win, "_load_sg_context", lambda: None)
    win._set_mode(MODE_ANNOTATION)
    win._toggle_drawer()
    plate = shot / "plate" / "org" / "v001" / "mov" / "SHOT_A_org_v001.mov"
    task = {
        "task_id": 5,
        "shot_id": 9,
        "project_id": 1,
        "shot_code": "SHOT_A",
        "task_status": "wtg",
    }
    win.open_movie(str(plate), task)
    qtbot.waitUntil(
        lambda: len(win._bufs[KEY_CUR].frames) >= 6 and len(win._bufs[KEY_EDIT].frames) >= 6,
        timeout=30000,
    )
    layer = win._layer
    r = win._view.image_rect()
    assert r is not None

    def at(fx: float, fy: float) -> Any:
        return QPointF(r[0] + r[2] * fx, r[1] + r[3] * fy).toPoint()

    frame = win.frame_number()
    # 원본을 보면서 네모를 그린다
    assert win._shown == KEY_CUR and layer.source() == "org"
    win._set_tool("rect")
    _drag(layer, [at(0.1, 0.1), at(0.3, 0.3)])
    assert [s["source"] for s in layer.doc().shapes()] == ["org"]

    # edit 으로 바꾸면 원본에 그린 네모는 안 보이고, 새 그림은 edit 것이 된다
    win._show_buffer(KEY_EDIT)
    assert layer.source() == "edit"
    assert layer.doc().shapes_at(frame, layer.source()) == []
    win._set_tool("arrow")
    _drag(layer, [at(0.5, 0.5), at(0.7, 0.3)])
    assert [s["source"] for s in layer.doc().shapes()] == ["org", "edit"]
    assert [s["kind"] for s in layer.doc().shapes_at(frame, "edit")] == ["arrow"]
    win._show_buffer(KEY_CUR)
    assert [s["kind"] for s in layer.doc().shapes_at(frame, layer.source())] == ["rect"]

    # 노트 그림은 그린 영상마다 한 장 — 같은 프레임이어도 두 장이다
    assert win._attachment_marks() == [(KEY_EDIT, frame), (KEY_CUR, frame)]
    paths = win._render_note_images()
    try:
        assert len(paths) == 2 and all(Path(p).is_file() for p in paths)
        assert [win._note_image_meta[p] for p in paths] == [("edit", 0), ("org", 0)]
    finally:
        win._remove_files(paths)

    # 보낼 때: 버전은 샷그리드에서 찾은 edit 버전, 그림 이름은 샷그리드가 붙이는 꼴
    sent: dict = {}

    class _Now:
        def __init__(self, fn: Any) -> None:
            self.finished = self.error = self
            self._fn = fn

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            self._fn()

        def isRunning(self) -> bool:  # noqa: N802
            return False

    def _fake_submit(_sg: Any, **kw: Any) -> None:
        sent.update(kw)
        sent["names"] = [Path(p).name for p in kw["attachment_paths"]]
        sent["existed"] = all(Path(p).is_file() for p in kw["attachment_paths"])

    asked: dict = {}

    def _fake_target(_sg: Any, shot_id: int, **kw: Any) -> Any:
        asked.update(kw, shot_id=shot_id)
        return "edit", {"id": 321, "code": "SHOT_A_edit_v001", "task": "edit", "task_id": 88}

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Now)
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.open_submit_session", lambda: (object(), {"name": "SV"})
    )
    monkeypatch.setattr("bpe.shotgrid.confirm_submit.submit_confirm", _fake_submit)
    monkeypatch.setattr("bpe.shotgrid.confirm_submit.guide_note_target", _fake_target)
    win._submit("")
    assert asked["shot_id"] == 9 and asked["drawn"] == ["edit", "org"] and asked["shown"] == "org"
    assert asked["codes"] == {"org": "SHOT_A_org_v001", "edit": "SHOT_A_edit_v001"}
    assert sent["version_id"] == 321
    # 노트에는 그 버전(edit)의 태스크가 걸린다 — 샷그리드에서 직접 단 노트와 같게
    assert sent["note_task_id"] == 88
    # 제목은 샷그리드에서 직접 올린 노트와 같은 꼴(버전 이름 + 샷 이름)
    assert sent["subject"] == "SV's Note on SHOT_A_edit_v001 and SHOT_A"
    assert sent["status_code"] == "" and sent["empty_note_text"] == ""
    # 같은 순번의 그림 두 장은 이름이 겹치지 않게 뒤 것이 다음 번호가 된다
    assert sent["names"] == ["annot_version_321.0.png", "annot_version_321.1.png"]
    assert sent["existed"] and not Path(sent["attachment_paths"][0]).parent.exists()
    win._submit_busy = False


# ── 2026-11-17 추가: 샷의 글 칸에 적용 — 노트와 따로, 불러온 글을 고친 그대로 ─────────────


def test_shot_text_is_loaded_and_applied_apart_from_the_note(win: Any, monkeypatch: Any) -> None:
    from bpe.core.confirm_shot_text import KIND_DESCRIPTION, KIND_WORK_ORDER, clean_text

    nl = chr(10)
    calls: list = []
    on_sg = {KIND_WORK_ORDER: "2D 합성", KIND_DESCRIPTION: "- 와이어 리무브"}

    class _Now:
        """바로 실행하고 결과를 끝난 신호로 넘기는 가짜 워커."""

        def __init__(self, fn: Any) -> None:
            self._fn = fn
            self._done: list = []
            self._failed: list = []
            self.finished, self.error = self, self

        def connect(self, cb: Any) -> None:
            (self._done if not self._done else self._failed).append(cb)

        def start(self) -> None:
            try:
                value = self._fn()
            except Exception as exc:  # noqa: BLE001
                self._failed[0](str(exc))
            else:
                self._done[0](value)

        def isRunning(self) -> bool:  # noqa: N802
            return False

    def _fake_apply(_sg: Any, shot_id: int, kind: str, text: str, *, expected: Any = None) -> Any:
        calls.append((shot_id, kind, text, expected))
        if "실패" in text:
            raise RuntimeError("no permission")
        if clean_text(expected or "") != clean_text(on_sg[kind]):
            return False, on_sg[kind]  # 그 사이 샷그리드의 글이 바뀌었다
        on_sg[kind] = clean_text(text)
        return True, on_sg[kind]

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Now)
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.open_submit_session", lambda: (object(), {"name": "SV"})
    )
    monkeypatch.setattr("bpe.shotgrid.shot_text.apply_shot_text", _fake_apply)
    _list_rows(win)
    _as_task(win, 5, "S_A")
    win._task["vfx_work_order"] = "2D 합성"
    win._task["shot_description"] = "- 와이어 리무브"
    win._fill_work_info()
    win._load_shot_text()
    assert win._panel._shot_btns[KIND_WORK_ORDER].isEnabled()
    # 칸에는 샷그리드에 이미 적혀 있는 글이 불러와져 있다
    assert win._panel.shot_text(KIND_WORK_ORDER) == "2D 합성"
    assert win._panel.shot_text(KIND_DESCRIPTION) == "- 와이어 리무브"

    # 고친 것이 없으면 샷그리드에 묻지 않는다
    win._on_shot_text_requested(KIND_WORK_ORDER, "2D 합성" + nl)
    assert calls == [] and "바뀐 글이 없습니다" in win._panel._shot_result.text()

    # 그대로 두고 덧붙였다 — 칸의 글 그대로 적용되고 화면과 목록 줄에 바로 반영된다
    win._panel.set_shot_text(KIND_WORK_ORDER, "2D 합성" + nl + "AI" + nl + "ENV 빙벽" + nl)
    win._panel.set_memo_text("노트에 쓸 글")
    win._on_shot_text_requested(KIND_WORK_ORDER, win._panel.shot_text(KIND_WORK_ORDER))
    kept = "2D 합성" + nl + "AI" + nl + "ENV 빙벽"
    assert calls == [(105, KIND_WORK_ORDER, kept, "2D 합성")]
    assert win._task["vfx_work_order"] == kept
    assert "ENV 빙벽" in win._panel.work_order_text()
    assert win._panel.shot_text(KIND_WORK_ORDER) == kept  # 칸에는 적용된 글이 그대로 있다
    assert "워크오더 칸에 적용했습니다" in win._panel._shot_result.text()
    row = next(r for r in win._drawer._rows if r["task_id"] == 5)
    assert row["vfx_work_order"] == kept
    # 노트 쪽(메모·보내기)은 건드리지 않는다
    assert win._panel.memo_text() == "노트에 쓸 글" and not win._send_timer.isActive()
    assert not win._submit_busy

    # 불러온 글을 지우고 다른 글을 썼다 — 새 글로 바뀐다
    win._on_shot_text_requested(KIND_DESCRIPTION, "피 추가")
    assert win._task["shot_description"] == "피 추가" and on_sg[KIND_DESCRIPTION] == "피 추가"
    assert win._panel.shot_text(KIND_DESCRIPTION) == "피 추가"

    # 그 사이 다른 사람이 샷그리드에서 고쳤다 — 덮어쓰지 않고 지금 글을 칸에 불러온다
    on_sg[KIND_WORK_ORDER] = kept + nl + "260928 - omit"
    win._on_shot_text_requested(KIND_WORK_ORDER, "NOCG")
    assert on_sg[KIND_WORK_ORDER] == kept + nl + "260928 - omit"
    assert win._panel.shot_text(KIND_WORK_ORDER) == kept + nl + "260928 - omit"
    assert "바뀌어 적용하지 않았습니다" in win._panel._shot_result.text()
    assert win._task["vfx_work_order"] == kept + nl + "260928 - omit"
    # 그 글을 보고 다시 적용하면 된다
    win._on_shot_text_requested(KIND_WORK_ORDER, "NOCG")
    assert on_sg[KIND_WORK_ORDER] == "NOCG" and win._panel.shot_text(KIND_WORK_ORDER) == "NOCG"

    # 저장에 실패하면 쓰던 글이 칸에 남는다
    win._panel.set_shot_text(KIND_WORK_ORDER, "실패할 글")
    win._on_shot_text_requested(KIND_WORK_ORDER, "실패할 글")
    assert win._panel.shot_text(KIND_WORK_ORDER) == "실패할 글"
    assert "적용 실패" in win._panel._shot_result.text() and "no permission" in (
        win._panel._shot_result.text()
    )
    assert win._panel._shot_btns[KIND_WORK_ORDER].isEnabled() and not win._shot_text_busy

    # 샷이 바뀌면 칸이 새 샷의 글로 바뀐다 — 앞 샷에 쓰던 글이 다음 샷에 적용되지 않게
    nxt = {"task_id": 7, "shot_id": 107, "shot_code": "S_B", "vfx_work_order": "MATTE"}
    win._reset_shot(task=nxt)
    assert win._panel.shot_text(KIND_WORK_ORDER) == "MATTE"
    assert win._panel.shot_text(KIND_DESCRIPTION) == ""
    win._reset_shot()
    assert win._panel.shot_text(KIND_WORK_ORDER) == ""
    # 샷그리드 샷이 열려 있지 않으면 누를 수 없고, 눌러도 아무 일도 없다
    win._sync_all()
    assert not win._panel._shot_btns[KIND_WORK_ORDER].isEnabled()
    before = len(calls)
    win._on_shot_text_requested(KIND_WORK_ORDER, "AI")
    assert len(calls) == before


def test_shots_without_a_task_are_not_mistaken_for_each_other(win: Any) -> None:
    from bpe.core.confirm_list import row_ident

    a = {"task_id": None, "shot_id": 301, "project_id": 1, "shot_code": "S_X"}
    b = {"task_id": None, "shot_id": 302, "project_id": 1, "shot_code": "S_Y"}
    win._task = dict(a)
    win._loaded_task_id = row_ident(a)
    win._sync_all()
    assert win._task_is_open()
    assert win._result_is_for_open_shot({"task_id": None, "ident": row_ident(a)})

    # 머리 줄만 다른 샷으로 바뀐 사이 — 태스크 번호가 둘 다 없어도 같은 샷으로 보지 않는다
    win._task = dict(b)
    assert not win._task_is_open()
    assert not win._result_is_for_open_shot({"task_id": None, "ident": row_ident(a)})
    win._sync_all()
    assert not win._panel.can_send()

    # 새 샷의 영상이 올라온 뒤에는 그 샷의 결과만 지금 샷의 것이다
    win._loaded_task_id = row_ident(b)
    assert win._task_is_open()
    assert win._result_is_for_open_shot({"task_id": None, "ident": row_ident(b)})
    assert not win._result_is_for_open_shot({"task_id": None, "ident": row_ident(a)})
    # 태스크가 있는 샷의 옛 표(ident 없이 task_id 만)도 그대로 맞는다
    _as_task(win, 5, "S_A")
    assert win._result_is_for_open_shot({"task_id": 5})
    assert not win._result_is_for_open_shot({"task_id": 7})


def test_confirm_note_carries_the_task_being_confirmed(win: Any, monkeypatch: Any) -> None:
    sent: dict = {}

    class _Now:
        def __init__(self, fn: Any) -> None:
            self.finished = self.error = self
            self._fn = fn

        def connect(self, *_a: Any) -> None:
            pass

        def start(self) -> None:
            self._fn()

        def isRunning(self) -> bool:  # noqa: N802
            return False

    def _fake_submit(_sg: Any, **kw: Any) -> None:
        sent.update(kw)

    def _no_guide(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("Confirm 노트는 edit·org 버전을 찾지 않는다")

    monkeypatch.setattr("bpe.gui.confirm.confirm_window.ShotGridWorker", _Now)
    monkeypatch.setattr(
        "bpe.shotgrid.confirm_submit.open_submit_session", lambda: (object(), {"name": "SV"})
    )
    monkeypatch.setattr("bpe.shotgrid.confirm_submit.submit_confirm", _fake_submit)
    monkeypatch.setattr("bpe.shotgrid.confirm_submit.guide_note_target", _no_guide)
    _as_task(win, 5, "S_A")
    win._panel.set_memo_text("엣지 정리")
    win._submit("retake")
    # 노트는 지금처럼 작업 버전에 붙고, 그 버전의 태스크(확인하는 태스크)가 Tasks 칸에 걸린다
    assert sent["version_id"] == 205 and sent["task_id"] == 5
    assert sent["note_task_id"] == 5
    assert sent["status_code"] == "retake" and "empty_note_text" not in sent
    win._submit_busy = False
