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


def test_passed_checks_are_listed_line_by_line(panel: Any) -> None:
    # 전부 통과여도 「2/2 통과」 한 줄로 줄이지 않고 항목마다 초록 글씨로 보인다
    panel.set_checks([_check(STATE_PASS, "프레임 74/74 통과"), _check(STATE_PASS, "fps 통과")])
    text = panel._v_checks.text()
    assert "프레임 74/74 통과" in text and "fps 통과" in text and "2/2 통과" not in text
    assert text.count(sp.style.OK) == 2 and text.count("<br>") == 1
    assert panel._btn_failures.isHidden()


def test_failed_check_is_spelled_out(panel: Any) -> None:
    panel.set_checks(
        [_check(STATE_FAIL, "프레임 다름: 편집본 75 / 현재버전 74"), _check(STATE_PASS, "fps 통과")]
    )
    assert "편집본 75 / 현재버전 74" in panel._v_checks.text()
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


def test_memo_is_one_plain_text_box(panel: Any) -> None:
    seen: List[int] = []
    panel.memo_edited.connect(lambda: seen.append(1))
    panel.set_memo_text("엣지 수정해주세요")
    panel.append_memo("경로: W:/ref/a.mov")
    assert panel.memo_text() == "엣지 수정해주세요\n경로: W:/ref/a.mov"
    assert seen  # 고칠 때마다 알린다(임시 저장용)
    panel.clear_memo()
    assert panel.memo_text() == ""


def test_notes_show_everything_first_and_mark_version_comments(panel: Any) -> None:
    panel.set_past_notes(
        [
            {
                "kind": "note",
                "version_code": "S_comp_v002",
                "timestamp": "2026-11-12",
                "content": "b",
            },
            {
                "kind": "version",
                "version_code": "S_comp_v002",
                "timestamp": "2026-11-11",
                "author": "작업자",
                "content": "엣지 정리했습니다",
            },
            {
                "kind": "note",
                "version_code": "S_comp_v001",
                "timestamp": "2026-11-05",
                "content": "a",
            },
        ],
        "S_comp_v002",
    )
    assert panel._past_versions.currentIndex() == 0 and panel.past_count() == 3  # 처음엔 전부
    assert "버전 올리며 쓴 글" in panel._past_rows[1].text()
    assert "버전 올리며 쓴 글" not in panel._past_rows[0].text()
    panel._past_versions.setCurrentIndex(2)  # 버전을 고르면 그 버전 것만
    assert panel.past_count() == 1


def test_work_line_puts_codes_in_mono(panel: Any) -> None:
    html = sp._mono_codes("업체 A · v017 · sv")
    assert html.count("<span") == 2 and "업체 A" in html


def test_cc_people_are_searched_added_and_removed(panel: Any, qtbot: Any) -> None:
    asked: List[str] = []
    panel.cc_search_requested.connect(asked.append)
    panel._cc_input.setText("kim")
    qtbot.waitUntil(lambda: asked == ["kim"], timeout=2000)
    panel.set_cc_results(
        [{"id": 3, "name": "김작업", "login": "kim"}, {"id": 4, "name": "김팀장", "login": "lead"}]
    )
    assert panel._cc_list.count() == 2 and not panel._cc_list.isHidden()
    panel._on_cc_item(panel._cc_list.item(1))
    assert panel.cc_users() == [{"type": "HumanUser", "id": 4}]
    assert panel._cc_input.text() == "" and panel._cc_list.isHidden()
    assert "김팀장" in panel._cc_chips.text()

    # 이미 넣은 사람은 결과에서 빠지고, Enter 는 첫 사람을 넣는다
    panel._cc_input.setText("kim")
    panel.set_cc_results([{"id": 3, "name": "김작업"}, {"id": 4, "name": "김팀장"}])
    assert panel._cc_list.count() == 1
    panel._add_first_cc()
    assert [u["id"] for u in panel.cc_users()] == [4, 3]

    panel._on_cc_link(sp._CC_REMOVE + "4")
    assert [u["id"] for u in panel.cc_users()] == [3]
    panel.clear_cc()
    assert panel.cc_users() == [] and panel._cc_chips.isHidden()


def test_nav_row_shows_position_and_emits(panel: Any) -> None:
    got: List[int] = []
    panel.nav_requested.connect(got.append)
    panel.set_nav("8 / 44", True, False)
    assert panel.nav_text() == "8 / 44" and panel.nav_enabled() == (True, False)
    panel._btn_prev.click()
    panel._btn_next.click()  # 꺼진 버튼은 아무 일도 안 한다
    assert got == [-1]


def test_memo_takes_a_copied_picture_but_pastes_text_as_text(panel: Any) -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QColor, QImage

    got: List[Any] = []
    panel.image_pasted.connect(got.append)
    img = QImage(8, 8, QImage.Format.Format_RGB888)
    img.fill(QColor("#ff0000"))
    pic = QMimeData()
    pic.setImageData(img)
    panel._memo_edit.insertFromMimeData(pic)
    assert len(got) == 1 and panel.memo_text() == ""
    words = QMimeData()
    words.setText("plain words")
    panel._memo_edit.insertFromMimeData(words)
    assert len(got) == 1 and panel.memo_text() == "plain words"


def _png_bytes(color: str = "#3366cc", w: int = 320, h: int = 180) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_note_pictures_show_under_their_note_and_open_big(panel: Any, monkeypatch: Any) -> None:
    from bpe.gui.widgets import clickable_image as ci_mod

    notes = [
        {"note_id": 11, "version_code": "S_comp_v002", "timestamp": "2026-11-13 10:00",
         "author": "SV", "content": "여기 정리"},
        {"note_id": 12, "version_code": "S_comp_v001", "timestamp": "2026-11-12 10:00",
         "author": "SV", "content": "그림 없는 노트"},
        {"kind": "version", "version_code": "S_comp_v002", "timestamp": "2026-11-13 09:00",
         "author": "작업자", "content": "올리며 쓴 글"},
    ]  # fmt: skip
    panel.set_past_notes(notes)
    assert panel.note_image_count(11) == 0
    panel.set_note_images({11: [_png_bytes(), _png_bytes("#cc3333"), b"not an image"]})
    assert panel.note_image_count(11) == 2  # 깨진 그림은 빼고 보인다
    assert panel.note_image_count(12) == 0
    assert not panel._image_hosts[11].isHidden() and panel._image_hosts[12].isHidden()

    # 누르면 크게 보는 창이 뜨고, 같은 노트의 그림끼리 넘겨 볼 수 있다
    opened: List[Any] = []

    class _Dlg:
        def __init__(self, pixmaps: Any, index: int, _parent: Any) -> None:
            opened.append((len(pixmaps), index))

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(ci_mod, "_ImageViewerDialog", _Dlg)
    grid = panel._image_hosts[11].layout()
    thumbs = [grid.itemAt(i).widget() for i in range(grid.count())]
    thumbs[1]._open_full_image_dialog()
    assert opened == [(2, 1)]

    # 버전으로 걸러도, 노트를 다시 읽어도 그림이 남아 있다
    panel._past_versions.setCurrentIndex(1)
    assert panel.note_image_count(11) == 2
    panel.set_past_notes(notes[:1])
    assert panel.note_image_count(11) == 2
    panel.set_past_notes([notes[1]])
    assert 11 not in panel._note_images


def test_annotation_mode_shows_one_note_button(panel: Any) -> None:
    asked: List[int] = []
    panel.note_requested.connect(lambda: asked.append(1))
    panel.show()
    assert not panel._btn_note.isVisibleTo(panel) and panel._btn_retake.isVisibleTo(panel)
    panel.set_annotation(True)
    assert panel.is_annotation()
    assert panel._btn_note.isVisibleTo(panel)
    for b in (panel._btn_retake, panel._btn_cfrm, panel._other):
        assert not b.isVisibleTo(panel)
    panel.set_sendable(False, "샷그리드 정보가 있는 샷에서만 보낼 수 있습니다")
    assert not panel.can_send()
    panel.set_sendable(True)
    assert panel.can_send() and "상태는 그대로" in panel._btn_note.toolTip()
    panel._btn_note.click()
    assert asked == [1]
    panel.set_annotation(False)
    assert panel._btn_retake.isVisibleTo(panel) and not panel._btn_note.isVisibleTo(panel)


# ── 2026-11-16 추가: 지난 Note 글을 끌어 골라 복사하기 ─────────────────────────────


class _FakeClipboard:
    """시험이 사용자의 진짜 클립보드를 건드리지 않게 하는 가짜."""

    def __init__(self) -> None:
        self.value = ""

    def setText(self, text: str) -> None:  # noqa: N802
        self.value = text

    def text(self) -> str:
        return self.value


@pytest.fixture
def clip(monkeypatch: Any) -> _FakeClipboard:
    fake = _FakeClipboard()
    monkeypatch.setattr(sp.QGuiApplication, "clipboard", staticmethod(lambda: fake))
    return fake


_PATH_NOTE = "W:/vfx/project_2025/MMK_028/04_sq/ep06/EP06_S001_0020/comp/ref_v001.mov"


def _select_all(row: Any) -> None:
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(row.text())
    row.setSelection(0, len(doc.toPlainText()))


def test_copied_note_text_has_no_hidden_break_marks(panel: Any, clip: _FakeClipboard) -> None:
    zw = chr(0x200B)
    assert sp._clean_copied("W:/" + zw + "vfx" + chr(0x2029) + "a" + chr(0x2028) + "b") == (
        "W:/vfx\na\nb"
    )
    notes = [
        {"version_code": "S_comp_v001", "timestamp": "2026-11-10", "content": _PATH_NOTE},
        {"version_code": "S_comp_v002", "timestamp": "2026-11-11", "subject": "제목만 있는 Note"},
    ]
    panel.set_past_notes(notes, "")
    row = panel._past_rows[0]
    assert zw in row.text()  # 화면에서는 긴 경로가 줄 바뀔 수 있게 끼워 둔다
    assert not panel.copy_note_selection() and clip.value == ""  # 고른 글이 없으면 아무 일도 없다

    _select_all(row)
    assert row.hasSelectedText()
    assert panel.copy_note_selection()
    assert zw not in clip.value and _PATH_NOTE in clip.value  # 붙여 넣으면 경로가 그대로다

    # 「이 Note 전체 복사」는 본문만(내용이 없으면 제목)
    assert sp._note_plain(notes[0]) == _PATH_NOTE and row.copy_note() and clip.value == _PATH_NOTE
    assert panel._past_rows[1].copy_note() and clip.value == "제목만 있는 Note"
    assert sp._note_plain({"content": "  ", "subject": ""}) == "" and sp._note_plain(None) == ""


def test_dragging_on_a_note_selects_and_a_plain_click_compares(panel: Any, qtbot: Any) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    panel.set_past_notes(
        [
            {"version_code": "S_comp_v001", "timestamp": "2026-11-10", "content": "[1040] 엣지"},
            {"version_code": "S_comp_v002", "timestamp": "2026-11-11", "content": "블랙 확인"},
        ],
        "",
    )
    panel.resize(sp.PANEL_WIDTH, 700)
    panel.show()
    qtbot.waitExposed(panel)
    clicked: List[Any] = []
    panel.past_note_clicked.connect(clicked.append)
    first, second = panel._past_rows
    # 키보드 초점은 받지 않는다 — 받으면 ←/→ 를 스크롤 칸이 가져가 프레임 넘기기가 죽는다
    assert first.focusPolicy() == Qt.FocusPolicy.NoFocus

    y = first.height() // 2
    QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=QPoint(14, y))
    assert len(clicked) == 1 and clicked[0]["version_code"] == "S_comp_v001"  # 그냥 누르면 비교

    # 끌면(글 고르기) 비교가 켜지지 않는다
    QTest.mousePress(first, Qt.MouseButton.LeftButton, pos=QPoint(14, y))
    QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=QPoint(first.width() - 14, y))
    assert len(clicked) == 1

    # 글이 골라져 있는 줄을 놓을 때도 「누름」이 아니다
    _select_all(first)
    first._press_pos = QPoint(14, y)
    QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=QPoint(14, y))
    assert len(clicked) == 1

    # 다른 줄을 누르면 앞 줄에 남은 고름이 풀린다
    _select_all(first)
    assert first.hasSelectedText()
    QTest.mouseClick(second, Qt.MouseButton.LeftButton, pos=QPoint(14, second.height() // 2))
    assert not first.hasSelectedText() and len(clicked) == 2

    # 프레임 번호 링크는 그대로 듣는다
    got: List[int] = []
    panel.past_frame_clicked.connect(got.append)
    first._on_link("frame:1040")
    assert got == [1040]


# ── 2026-11-17 추가: Annotation — 샷의 글 칸(VFX work order · Description)에 적용 ──────────


def test_shot_text_block_shows_only_in_annotation_and_chips_fill_the_box(panel: Any) -> None:
    from bpe.core.confirm_shot_text import KIND_DESCRIPTION, KIND_WORK_ORDER, WORK_ORDER_CHIPS

    nl = chr(10)
    panel.show()
    assert not panel._shot_text_block.isVisibleTo(panel)  # Confirm 에서는 안 보인다
    panel.set_annotation(True)
    assert panel._shot_text_block.isVisibleTo(panel)
    assert list(panel._chip_btns) == list(WORK_ORDER_CHIPS)

    from bpe.gui.confirm import side_panel as sp

    assert sp._SHOT_TEXT_TITLE == "Supervisor Order"
    # 단추를 누르면 워크오더 글에 한 줄씩 들어간다(여러 개 가능)
    panel._chip_btns["AI"].click()
    panel._chip_btns["2D 합성"].click()
    assert panel.shot_text(KIND_WORK_ORDER) == "AI" + nl + "2D 합성"
    assert panel._chip_btns["AI"].isChecked() and panel._chip_btns["2D 합성"].isChecked()
    assert not panel._chip_btns["ENV"].isChecked()
    # 다시 누르면 그 줄만 빠진다
    panel._chip_btns["AI"].click()
    assert panel.shot_text(KIND_WORK_ORDER) == "2D 합성" and not panel._chip_btns["AI"].isChecked()
    # 직접 고쳐 써도 된다 — 단추 말 뒤에 내용을 이어 쓰면 단추는 꺼진다
    panel.set_shot_text(KIND_WORK_ORDER, "2D 합성 불연기 추가")
    assert not panel._chip_btns["2D 합성"].isChecked()
    assert panel.shot_text(KIND_DESCRIPTION) == ""  # 디스크립션 칸은 따로다

    # 이미 적혀 있던 글을 불러온 칸 — 그 줄의 단추는 눌린 모양이고, 누르면 그 줄이 빠진다
    panel.set_shot_text(KIND_WORK_ORDER, "리무브" + nl + "260928 - omit")
    assert panel._chip_btns["리무브"].isChecked()
    panel._chip_btns["AI"].click()
    assert panel.shot_text(KIND_WORK_ORDER) == "리무브" + nl + "260928 - omit" + nl + "AI"
    panel._chip_btns["리무브"].click()
    assert panel.shot_text(KIND_WORK_ORDER) == "260928 - omit" + nl + "AI"
    panel.set_shot_text(KIND_WORK_ORDER, "2D 합성 불연기 추가")

    # 「적용」은 칸마다 따로 — 어느 칸의 어떤 글인지 알려 준다
    got: List[Any] = []
    panel.shot_text_requested.connect(lambda k, t: got.append((k, t)))
    assert not panel._shot_btns[KIND_WORK_ORDER].isEnabled()  # 샷이 열리기 전에는 못 누른다
    panel.set_shot_text_enabled(True)
    panel._shot_btns[KIND_WORK_ORDER].click()
    panel.set_shot_text(KIND_DESCRIPTION, "- 병사 연장")
    panel._shot_btns[KIND_DESCRIPTION].click()
    assert got == [(KIND_WORK_ORDER, "2D 합성 불연기 추가"), (KIND_DESCRIPTION, "- 병사 연장")]

    # 저장하는 동안 그 버튼만 잠긴다
    panel.set_shot_text_busy(KIND_WORK_ORDER, True)
    assert not panel._shot_btns[KIND_WORK_ORDER].isEnabled()
    assert panel._shot_btns[KIND_DESCRIPTION].isEnabled()
    panel.set_shot_text_busy(KIND_WORK_ORDER, False)
    assert panel._shot_btns[KIND_WORK_ORDER].isEnabled()
    assert panel._shot_btns[KIND_WORK_ORDER].text() == "적용"
    assert panel._shot_btns[KIND_DESCRIPTION].text() == "적용"

    panel.set_shot_text_result("샷그리드 워크오더 칸에 적용했습니다", True)
    assert panel._shot_result.isVisibleTo(panel) and "적용했습니다" in panel._shot_result.text()
    panel.clear_shot_text(KIND_WORK_ORDER)
    assert panel.shot_text(KIND_WORK_ORDER) == "" and panel.shot_text(KIND_DESCRIPTION)
    panel.clear_shot_text()
    assert panel.shot_text(KIND_DESCRIPTION) == ""
    panel.set_annotation(False)
    assert not panel._shot_text_block.isVisibleTo(panel)
