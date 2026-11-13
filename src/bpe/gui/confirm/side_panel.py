"""컨펌 창 오른쪽 칸 — 작업 내용, Note(지난 내용), 메모, 상태 버튼 (시안 2판 모양)."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_checks import STATE_FAIL, STATE_PASS, CheckResult
from bpe.gui.confirm import status_style, style

PANEL_WIDTH = style.PANEL_WIDTH
_NO_VERSION = "버전 없음"
_KEY_COLUMN_W = 76
_HEADER_H = 28
_STATUS_ICON = 18
_STATUS_ROW_H = 30
_STATUS_LIST_W = 300
_FRAME_REF = re.compile(r"\[(\d+)((?:\s*[-–~]\s*\d+)?)\]")
_FRAME_LINK = "frame:"
_PATH_BREAK = re.compile(r"[\\/_]")
_CODE_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]*\d[A-Za-z0-9_.\-]*$|^[a-z]{2,6}$")


def _header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style.section_header_style())
    lbl.setFixedHeight(_HEADER_H)
    lbl.setIndent(0)
    return lbl


def _note_body(note: Dict[str, Any]) -> str:
    """노트 본문. 내용이 비어 있으면 제목을, 그것도 없으면 그림만 있는 노트라고 알린다."""
    text = (note.get("content") or "").strip() or (note.get("subject") or "").strip()
    if not text:
        return f'<span style="color:{style.DIM}">글 없음 (그림만 있는 Note)</span>'
    return _frame_links(text)


def _mono_codes(text: str) -> str:
    """버전·상태 같은 영문·숫자 낱말만 폭 고른 글씨로(한글은 본문 글씨 그대로)."""
    parts = [
        f'<span style="{style.mono()}">{escape(tok)}</span>'
        if _CODE_TOKEN.match(tok)
        else escape(tok)
        for tok in text.split(" ")
    ]
    return " ".join(parts)


def _frame_links(text: str) -> str:
    """지적 글 안의 ``[1040]`` 을 누를 수 있는 프레임 번호로 바꾼다(글은 먼저 escape)."""

    def repl(m: "re.Match[str]") -> str:
        return (
            f'<a href="{_FRAME_LINK}{m.group(1)}" style="color:{style.PAST}; '
            f'text-decoration:none; {style.mono()}">[{m.group(1)}{m.group(2)}]</a>'
        )

    # 긴 경로가 칸 밖으로 잘리지 않게, 경로 구분 글자 뒤에서 줄이 바뀔 수 있게 한다
    safe = _PATH_BREAK.sub(lambda m: m.group(0) + "​", escape(text))
    return _FRAME_REF.sub(repl, safe).replace("\n", "<br>")


def _key(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {style.DIM};")
    lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return lbl


def _value() -> QLabel:
    lbl = QLabel("")
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def _clear_block() -> QWidget:
    """바탕을 칠하지 않는 묶음 칸(앱 전역 스타일의 바탕색이 덮이지 않게)."""
    w = QWidget()
    w.setObjectName("confirm_block")
    w.setStyleSheet("QWidget#confirm_block { background: transparent; }")
    return w


def _short_version(code: str) -> str:
    low = code.lower()
    return code[low.rfind("_v") + 1 :] if "_v" in low else code


class _ClickRow(QLabel):
    """누를 수 있는 한 줄(지난 지적)."""

    clicked = Signal(object)
    frame_clicked = Signal(int)

    def __init__(self, html: str, payload: Any) -> None:
        super().__init__(html)
        self._payload = payload
        self.setWordWrap(True)
        self.setIndent(0)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.setOpenExternalLinks(False)
        self.linkActivated.connect(self._on_link)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_selected(False)

    def _on_link(self, href: str) -> None:
        if href.startswith(_FRAME_LINK) and href[len(_FRAME_LINK) :].isdigit():
            self.frame_clicked.emit(int(href[len(_FRAME_LINK) :]))

    def set_selected(self, on: bool) -> None:
        bg = style.RAISED if on else "transparent"
        edge = style.PAST if on else "transparent"
        self.setStyleSheet(
            f"padding: 6px 10px 6px 8px; border-bottom: 1px solid {style.EDGE}; "
            f"border-left: 2px solid {edge}; background: {bg};"
        )

    def payload(self) -> Any:
        return self._payload

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._payload)
        super().mousePressEvent(event)


class ConfirmSidePanel(QWidget):
    status_requested = Signal(str)
    cancel_requested = Signal()
    retry_requested = Signal()
    past_note_clicked = Signal(object)
    past_frame_clicked = Signal(int)
    preset_picked = Signal(str)
    memo_edited = Signal()
    insert_failures_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("confirm_panel")
        self.setStyleSheet(
            f"QWidget#confirm_panel {{ background: {style.PANEL}; "
            f"border-left: 1px solid {style.EDGE}; }}"
        )
        self._past: List[Dict[str, Any]] = []
        self._past_rows: List[_ClickRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(1, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(_header("작업 내용"))
        info = _clear_block()
        grid = QGridLayout(info)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, _KEY_COLUMN_W)
        grid.setColumnStretch(1, 1)
        self._v_order, self._v_desc = _value(), _value()
        self._v_who, self._v_checks = _value(), _value()
        self._v_basis, self._v_look = _value(), _value()
        self._k_desc = _key("샷 설명")
        self._k_basis, self._k_look = _key("기준"), _key("룩")
        self._k_preset = _key("프리셋")
        self._preset_box = QComboBox()
        self._preset_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preset_box.setToolTip("이 프로젝트의 프리셋이 여러 개입니다 — 검사 기준으로 쓸 것")
        self._preset_box.activated.connect(self._on_preset)
        rows = (
            (_key("워크 오더"), self._v_order),
            (self._k_desc, self._v_desc),
            (_key("작업"), self._v_who),
            (self._k_basis, self._v_basis),
            (self._k_preset, self._preset_box),
            (self._k_look, self._v_look),
            (_key("검사"), self._v_checks),
        )
        for r, (k, v) in enumerate(rows):
            grid.addWidget(k, r, 0)
            grid.addWidget(v, r, 1)
        col.addWidget(info)
        self._btn_failures = QPushButton("검사 실패 문장을 메모에 넣기")
        self._btn_failures.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_failures.setStyleSheet(style.warn_button_style())
        self._btn_failures.clicked.connect(self.insert_failures_requested)
        self._btn_failures.hide()
        wrap = QHBoxLayout()
        wrap.setContentsMargins(10, 0, 10, 8)
        wrap.addWidget(self._btn_failures)
        col.addLayout(wrap)

        past_head = QFrame()
        past_head.setStyleSheet(
            f"QFrame {{ background: {style.HEADER}; border-top: 1px solid {style.EDGE}; "
            f"border-bottom: 1px solid {style.EDGE}; }}"
        )
        past_head.setFixedHeight(_HEADER_H + 1)
        ph = QHBoxLayout(past_head)
        ph.setContentsMargins(10, 0, 10, 0)
        ph.setSpacing(6)
        title = QLabel("Note")
        title.setIndent(0)
        title.setStyleSheet(
            f"color: {style.LABEL}; font-size: {style.FONT_SMALL_PX}px; font-weight: bold; "
            f"border: none;"
        )
        ph.addWidget(title, 1)
        self._past_versions = QComboBox()
        self._past_versions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._past_versions.setMinimumWidth(84)
        self._past_versions.setStyleSheet(f"QComboBox {{ height: 20px; {style.mono()} }}")
        self._past_versions.currentIndexChanged.connect(self._fill_past)
        ph.addWidget(self._past_versions)
        col.addWidget(past_head)

        self._past_box = QWidget()
        self._past_col = QVBoxLayout(self._past_box)
        self._past_col.setContentsMargins(0, 0, 0, 0)
        self._past_col.setSpacing(0)
        past_scroll = QScrollArea()
        past_scroll.setWidgetResizable(True)
        past_scroll.setFrameShape(QFrame.Shape.NoFrame)
        past_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        past_scroll.setStyleSheet(
            f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: {style.PANEL}; }}"
        )
        past_scroll.setWidget(self._past_box)
        past_scroll.setMinimumHeight(120)
        col.addWidget(past_scroll, 2)

        self._memo_head = _header("메모")
        self._memo_head.setStyleSheet(
            style.section_header_style() + f"border-top: 1px solid {style.EDGE};"
        )
        self._memo_head.setFixedHeight(_HEADER_H + 1)
        col.addWidget(self._memo_head)
        ex = QVBoxLayout()
        ex.setContentsMargins(10, 8, 10, 6)
        ex.setSpacing(4)
        # 화면에 쓴 글이 한 줄씩 그대로 적히는 글 칸 — 여기서 바로 고치거나 덧붙여 쓴다
        self._memo_edit = QPlainTextEdit()
        self._memo_edit.setPlaceholderText(
            "화면에 네모·원·화살표를 그리고 쓴 글이 여기에 그대로 적힙니다.\n"
            "직접 고치거나 경로·설명을 덧붙여 써도 됩니다."
        )
        self._memo_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._memo_edit.setMinimumHeight(64)
        self._memo_edit.document().setDocumentMargin(4)
        self._memo_edit.setStyleSheet("QPlainTextEdit { padding: 2px 4px; }")
        self._memo_edit.textChanged.connect(self.memo_edited)
        ex.addWidget(self._memo_edit, 1)
        self._attach = QLabel("")
        self._attach.setStyleSheet(f"color: {style.DIM}; font-size: {style.FONT_SMALL_PX}px;")
        ex.addWidget(self._attach)
        col.addLayout(ex, 3)

        foot = QFrame()
        foot.setStyleSheet(
            f"QFrame {{ background: {style.HEADER}; border-top: 1px solid {style.EDGE}; }}"
        )
        fcol = QVBoxLayout(foot)
        fcol.setContentsMargins(10, 8, 10, 8)
        fcol.setSpacing(6)

        self._pending = _clear_block()
        prow = QHBoxLayout(self._pending)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(6)
        self._pending_lbl = QLabel("")
        self._pending_lbl.setWordWrap(True)
        self._pending_lbl.setStyleSheet(f"color: {style.WARN}; border: none;")
        prow.addWidget(self._pending_lbl, 1)
        self._btn_cancel = QPushButton("취소")
        self._btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_cancel.clicked.connect(self.cancel_requested)
        prow.addWidget(self._btn_cancel)
        self._pending.hide()
        fcol.addWidget(self._pending)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.hide()
        fcol.addWidget(self._result)
        self._btn_retry = QPushButton("상태만 다시 바꾸기")
        self._btn_retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_retry.clicked.connect(self.retry_requested)
        self._btn_retry.hide()
        fcol.addWidget(self._btn_retry)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self._btn_retake = QPushButton(" retake")
        self._btn_cfrm = QPushButton(" cfrm")
        for b in (self._btn_retake, self._btn_cfrm):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setIconSize(QSize(_STATUS_ICON, _STATUS_ICON))
        self._btn_retake.clicked.connect(lambda: self.status_requested.emit("retake"))
        self._btn_cfrm.clicked.connect(lambda: self.status_requested.emit("cfrm"))
        actions.addWidget(self._btn_retake, 1)
        actions.addWidget(self._btn_cfrm, 1)
        # 그 밖의 상태 — 펼치면 줄마다 상태 색·아이콘이 보이는 큼직한 목록
        self._other = QComboBox()
        self._other.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._other.setFixedWidth(96)
        self._other.setView(QListView())
        self._other.setIconSize(QSize(_STATUS_ICON, _STATUS_ICON))
        self._other.setMaxVisibleItems(24)
        self._other.view().setMinimumWidth(_STATUS_LIST_W)
        self._other.setStyleSheet(
            "QComboBox { height: 32px; }"
            f"QComboBox QAbstractItemView {{ background: {style.PANEL}; color: {style.TEXT}; "
            f"border: 1px solid {style.EDGE}; font-size: {style.FONT_PX + 1}px; outline: none; }}"
            f"QComboBox QAbstractItemView::item {{ min-height: {_STATUS_ROW_H}px; "
            f"padding: 2px 10px; border-bottom: 1px solid {style.EDGE}; }}"
            f"QComboBox QAbstractItemView::item:selected {{ background: {style.ON}; "
            f"color: {style.TEXT_STRONG}; }}"
        )
        self._status_items: List[Tuple[str, str]] = []
        self._other.addItem("Status", "")
        self._other.activated.connect(self._on_other)
        actions.addWidget(self._other)
        fcol.addLayout(actions)
        col.addWidget(foot)
        self.refresh_status_styles()
        self.set_work_info("", "", "")
        self.set_standard("", "", [], "")
        self._fill_past()

    # ── 채우기 ───────────────────────────────────────────────────

    def set_other_statuses(self, items: List[Tuple[str, str]]) -> None:
        self._status_items = list(items)
        self.refresh_status_styles()

    def refresh_status_styles(self) -> None:
        """상태 색·아이콘을 버튼과 목록에 다시 입힌다(샷그리드에서 읽어 온 뒤에도 부른다)."""
        self._other.clear()
        self._other.addItem("Status", "")
        for code, label in self._status_items:
            text = f"{code}   {status_style.name(code) or label}"
            self._other.addItem(status_style.icon(code, _STATUS_ICON), text, code)
        # retake = 테두리만, cfrm = 채움 — 둘 다 그 상태의 색으로
        r_bg, _r_fg = status_style.colors("retake")
        self._btn_retake.setIcon(status_style.icon("retake", _STATUS_ICON))
        self._btn_retake.setStyleSheet(
            f"QPushButton {{ height: 32px; background: {style.PANEL}; color: {r_bg}; "
            f"border: 1px solid {r_bg}; {style.mono(13, bold=True)} }}"
            f"QPushButton:hover {{ background: {style.RAISED}; }}"
            f"QPushButton:disabled {{ color: #6a6a6a; border-color: {style.EDGE}; }}"
        )
        c_bg, c_fg = status_style.colors("cfrm")
        self._btn_cfrm.setIcon(status_style.icon("cfrm", _STATUS_ICON))
        self._btn_cfrm.setStyleSheet(
            f"QPushButton {{ height: 32px; background: {c_bg}; color: {c_fg}; "
            f"border: 1px solid {style.EDGE}; {style.mono(13, bold=True)} }}"
            f"QPushButton:hover {{ border: 1px solid {style.TEXT_STRONG}; }}"
            f"QPushButton:disabled {{ color: #6a6a6a; background: #2c2c2c; }}"
        )

    def set_work_info(self, order: str, description: str, who: str) -> None:
        """워크 오더·샷 설명·작업 줄. 비어 있으면 '없음'으로 보여 준다."""
        none = f'<span style="color:{style.DIM}">없음</span>'
        self._v_order.setText(escape(order).replace("\n", "<br>") if order.strip() else none)
        has_desc = bool(description.strip())
        self._k_desc.setVisible(has_desc)
        self._v_desc.setVisible(has_desc)
        self._v_desc.setText(escape(description).replace("\n", "<br>"))
        self._v_who.setText(_mono_codes(who) if who.strip() else none)

    def work_order_text(self) -> str:
        return self._v_order.text()

    def set_checks(self, results: List[CheckResult]) -> None:
        """전부 통과면 한 줄로 줄이고, 실패·모름이 있으면 줄마다 보여 준다."""
        colors = {STATE_PASS: style.OK, STATE_FAIL: style.FAIL}
        passed = sum(1 for r in results if r.state == STATE_PASS)
        if results and passed == len(results):
            lines = [
                f'<span style="color:{style.OK}; {style.mono()}">'
                f"{passed}/{len(results)} 통과</span>"
            ]
            self._v_checks.setToolTip("\n".join(r.message for r in results))
        else:
            lines = [
                f'<span style="color:{colors.get(r.state, style.DIM)}; {style.mono()}">'
                f"{escape(r.message)}</span>"
                for r in results
            ]
            self._v_checks.setToolTip("")
        self._v_checks.setText("<br>".join(lines))
        self._btn_failures.setVisible(any(r.state == STATE_FAIL for r in results))

    def set_standard(self, basis: str, look: str, names: List[str], current: str) -> None:
        """무엇을 기준으로 검사했는지, MOV 의 룩, (여러 개일 때) 프리셋 고르기."""
        for key, value, text in (
            (self._k_basis, self._v_basis, basis),
            (self._k_look, self._v_look, look),
        ):
            key.setVisible(bool(text))
            value.setVisible(bool(text))
            value.setText(_mono_codes(text) if text else "")
        many = len(names) > 1
        self._k_preset.setVisible(many)
        self._preset_box.setVisible(many)
        self._preset_box.blockSignals(True)
        self._preset_box.clear()
        self._preset_box.addItems(list(names))
        if current in names:
            self._preset_box.setCurrentText(current)
        self._preset_box.blockSignals(False)

    def basis_text(self) -> str:
        return self._v_basis.text()

    def _on_preset(self, _index: int) -> None:
        self.preset_picked.emit(self._preset_box.currentText())

    def set_past_notes(self, notes: List[Dict[str, Any]], current_version: str = "") -> None:
        """*notes*: ``version_code``·``timestamp``·``author``·``content`` 를 가진 dict 들.

        ``kind`` 가 ``"version"`` 인 줄은 작업자가 버전을 올리며 적은 글이다.
        """
        self._past = list(notes)
        versions: List[str] = []
        for n in self._past:
            v = str(n.get("version_code") or _NO_VERSION)
            if v not in versions:
                versions.append(v)
        self._past_versions.blockSignals(True)
        self._past_versions.clear()
        self._past_versions.addItem("전체", "")
        for v in versions:
            self._past_versions.addItem(_short_version(v), v)
        del current_version  # 처음에는 늘 전부 보여 준다(버전은 필요할 때만 고른다)
        self._past_versions.setCurrentIndex(0)
        self._past_versions.blockSignals(False)
        self._fill_past()

    def _fill_past(self, *_args: Any) -> None:
        self._past_rows = []
        while self._past_col.count():
            item = self._past_col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        version = str(self._past_versions.currentData() or "")
        rows = [
            n
            for n in self._past
            if not version or str(n.get("version_code") or _NO_VERSION) == version
        ]
        if not rows:
            empty = QLabel("Note 가 없습니다")
            empty.setStyleSheet(f"color: {style.DIM}; padding: 8px 10px;")
            self._past_col.addWidget(empty)
        for n in rows:
            head = " · ".join(
                x
                for x in (
                    _short_version(str(n.get("version_code") or "")),
                    str(n.get("timestamp") or "")[:10],
                    str(n.get("author") or ""),
                )
                if x
            )
            tag = (
                f' <span style="color:{style.OK}; font-size:{style.FONT_SMALL_PX}px">'
                f"버전 올리며 쓴 글</span>"
                if n.get("kind") == "version"
                else ""
            )
            html = (
                f'<span style="color:{style.DIM}; {style.mono(style.FONT_SMALL_PX)}">'
                f"{escape(head)}</span>{tag}<br>{_note_body(n)}"
            )
            row = _ClickRow(html, n)
            row.clicked.connect(self._on_past_clicked)
            row.frame_clicked.connect(self.past_frame_clicked)
            self._past_rows.append(row)
            self._past_col.addWidget(row)
        self._past_col.addStretch(1)

    def past_count(self) -> int:
        return len(self._past_rows)

    def memo_text(self) -> str:
        return self._memo_edit.toPlainText()

    def set_memo_text(self, text: str) -> None:
        if text != self._memo_edit.toPlainText():
            self._memo_edit.setPlainText(text)

    def append_memo(self, text: str) -> None:
        cur = self._memo_edit.toPlainText().rstrip()
        self._memo_edit.setPlainText((cur + "\n" if cur else "") + text)

    def clear_memo(self) -> None:
        self._memo_edit.clear()

    def set_attach_text(self, text: str) -> None:
        self._attach.setText(text)

    def set_pending(self, text: Optional[str]) -> None:
        self._pending.setVisible(bool(text))
        self._pending_lbl.setText(text or "")

    def set_result(self, text: str, ok: bool, *, can_retry: bool = False) -> None:
        self._result.setVisible(bool(text))
        self._result.setText(text)
        color = style.OK if ok else style.WARN
        self._result.setStyleSheet(
            f"color: {color}; font-size: {style.FONT_SMALL_PX}px; border: none;"
        )
        self._btn_retry.setVisible(can_retry)

    def set_sendable(self, on: bool, tip: str = "") -> None:
        for b in (self._btn_retake, self._btn_cfrm, self._other):
            b.setEnabled(on)
            b.setToolTip(tip)

    def can_send(self) -> bool:
        return self._btn_retake.isEnabled()

    # ── 신호 ─────────────────────────────────────────────────────

    def _on_past_clicked(self, note: object) -> None:
        for row in self._past_rows:
            row.set_selected(row.payload() is note)
        if isinstance(note, dict):
            self.past_note_clicked.emit(note)

    def _on_other(self, index: int) -> None:
        code = str(self._other.itemData(index) or "")
        self._other.setCurrentIndex(0)
        if code:
            self.status_requested.emit(code)
