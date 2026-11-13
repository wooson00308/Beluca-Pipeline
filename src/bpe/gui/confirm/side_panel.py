"""컨펌 창 오른쪽 칸 — 작업 내용, 지난 지적, 메모, 상태 버튼."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_checks import STATE_FAIL, STATE_PASS, CheckResult
from bpe.gui import theme

PANEL_WIDTH = 360
_ROLE_ID = Qt.ItemDataRole.UserRole
_WARN = "#f0c060"


def _header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background: {theme.INPUT_BG}; color: {theme.TEXT_LABEL}; font-weight: bold; "
        f"font-size: {theme.FONT_SIZE_SMALL}px; padding: 6px 10px;"
    )
    return lbl


class ConfirmSidePanel(QWidget):
    status_requested = Signal(str)
    cancel_requested = Signal()
    retry_requested = Signal()
    past_note_clicked = Signal(object)
    memo_toggled = Signal(int, bool)
    insert_failures_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(f"background: {theme.PANEL_BG};")
        self._past: List[Dict[str, Any]] = []
        self._past_version = ""
        self._memo_guard = False
        self._build_ui()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(_header("작업 내용"))
        self._work = QLabel("샷그리드 정보 없음 — 파일만 열었습니다")
        self._work.setWordWrap(True)
        self._work.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._work.setContentsMargins(10, 8, 10, 4)
        col.addWidget(self._work)
        self._checks = QLabel("")
        self._checks.setWordWrap(True)
        self._checks.setContentsMargins(10, 0, 10, 8)
        col.addWidget(self._checks)
        self._btn_failures = QPushButton("검사 실패 문장을 메모에 넣기")
        self._btn_failures.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_failures.clicked.connect(self.insert_failures_requested)
        self._btn_failures.hide()
        col.addWidget(self._btn_failures)

        past_head = QHBoxLayout()
        past_head.setContentsMargins(0, 0, 0, 0)
        past_head.setSpacing(0)
        past_head.addWidget(_header("지난 지적"), 1)
        self._past_versions = QComboBox()
        self._past_versions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._past_versions.currentIndexChanged.connect(self._on_past_version)
        past_head.addWidget(self._past_versions)
        col.addLayout(past_head)
        self._past_list = QListWidget()
        self._past_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._past_list.setWordWrap(True)
        self._past_list.setFixedHeight(190)
        self._past_list.itemClicked.connect(self._on_past_clicked)
        col.addWidget(self._past_list)

        self._memo_head = _header("메모")
        col.addWidget(self._memo_head)
        self._memo_list = QListWidget()
        self._memo_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._memo_list.setWordWrap(True)
        self._memo_list.setFixedHeight(120)
        self._memo_list.itemChanged.connect(self._on_memo_changed)
        col.addWidget(self._memo_list)
        self._extra = QPlainTextEdit()
        self._extra.setPlaceholderText("경로나 설명을 덧붙여 쓰기")
        self._extra.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        col.addWidget(self._extra, 1)
        self._attach = QLabel("")
        self._attach.setStyleSheet(f"color: {theme.TEXT_LABEL};")
        self._attach.setContentsMargins(10, 4, 10, 4)
        col.addWidget(self._attach)

        self._pending = QFrame()
        self._pending.setStyleSheet(f"background: {theme.INPUT_BG};")
        prow = QHBoxLayout(self._pending)
        prow.setContentsMargins(10, 6, 10, 6)
        self._pending_lbl = QLabel("")
        self._pending_lbl.setWordWrap(True)
        prow.addWidget(self._pending_lbl, 1)
        self._btn_cancel = QPushButton("취소")
        self._btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_cancel.clicked.connect(self.cancel_requested)
        prow.addWidget(self._btn_cancel)
        self._pending.hide()
        col.addWidget(self._pending)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setContentsMargins(10, 4, 10, 4)
        self._result.hide()
        col.addWidget(self._result)
        self._btn_retry = QPushButton("상태만 다시 바꾸기")
        self._btn_retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_retry.clicked.connect(self.retry_requested)
        self._btn_retry.hide()
        col.addWidget(self._btn_retry)

        actions = QHBoxLayout()
        actions.setContentsMargins(10, 8, 10, 10)
        actions.setSpacing(6)
        self._btn_retake = QPushButton("retake")
        self._btn_cfrm = QPushButton("cfrm")
        for b, color in ((self._btn_retake, theme.ERROR), (self._btn_cfrm, theme.ACCENT)):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumHeight(38)
            b.setStyleSheet(
                f"QPushButton {{ min-width: 0px; font-weight: bold; border: 1px solid {color}; "
                f"color: {color}; "
                f"border-radius: 4px; }} QPushButton:disabled {{ color: {theme.TEXT_DIM}; "
                f"border-color: {theme.BORDER}; }}"
            )
        self._btn_retake.clicked.connect(lambda: self.status_requested.emit("retake"))
        self._btn_cfrm.clicked.connect(lambda: self.status_requested.emit("cfrm"))
        actions.addWidget(self._btn_retake, 1)
        actions.addWidget(self._btn_cfrm, 1)
        self._other = QComboBox()
        self._other.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._other.addItem("그 밖", "")
        self._other.activated.connect(self._on_other)
        self._other.setFixedWidth(84)
        actions.addWidget(self._other)
        col.addLayout(actions)

    # ── 채우기 ───────────────────────────────────────────────────

    def set_other_statuses(self, items: List[Tuple[str, str]]) -> None:
        self._other.clear()
        self._other.addItem("그 밖", "")
        for code, label in items:
            self._other.addItem(f"{code} · {label}", code)

    def set_work_info(self, text: str) -> None:
        self._work.setText(text)

    def set_checks(self, results: List[CheckResult]) -> None:
        colors = {STATE_PASS: theme.SUCCESS, STATE_FAIL: theme.ERROR}
        lines = [
            f'<span style="color:{colors.get(r.state, theme.TEXT_LABEL)}">{r.message}</span>'
            for r in results
        ]
        self._checks.setText("<br>".join(lines))
        self._btn_failures.setVisible(any(r.state == STATE_FAIL for r in results))

    def set_past_notes(self, notes: List[Dict[str, Any]], current_version: str = "") -> None:
        """*notes*: ``version_code``·``timestamp``·``author``·``content`` 를 가진 dict 들."""
        self._past = list(notes)
        versions: List[str] = []
        for n in self._past:
            v = str(n.get("version_code") or "버전 없음")
            if v not in versions:
                versions.append(v)
        self._past_versions.blockSignals(True)
        self._past_versions.clear()
        self._past_versions.addItem("전체", "")
        for v in versions:
            self._past_versions.addItem(v, v)
        pick = 0
        for i, v in enumerate(versions):
            if v != current_version:
                pick = i + 1
                break
        self._past_versions.setCurrentIndex(pick)
        self._past_versions.blockSignals(False)
        self._past_version = str(self._past_versions.currentData() or "")
        self._fill_past()

    def _fill_past(self) -> None:
        self._past_list.clear()
        rows = [
            n
            for n in self._past
            if not self._past_version
            or str(n.get("version_code") or "버전 없음") == self._past_version
        ]
        if not rows:
            item = QListWidgetItem("지적이 없습니다")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._past_list.addItem(item)
            return
        for n in rows:
            head = " · ".join(
                x
                for x in (
                    str(n.get("version_code") or ""),
                    str(n.get("timestamp") or "")[:10],
                    str(n.get("author") or ""),
                )
                if x
            )
            item = QListWidgetItem(f"{head}\n{(n.get('content') or '').strip()}")
            item.setData(_ROLE_ID, n)
            self._past_list.addItem(item)

    def set_memo(self, lines: List[Tuple[int, str, bool]]) -> None:
        self._memo_guard = True
        self._memo_list.clear()
        for shape_id, text, on in lines:
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setData(_ROLE_ID, shape_id)
            self._memo_list.addItem(item)
        self._memo_guard = False
        n = sum(1 for _i, _t, on in lines if on)
        self._memo_head.setText(f"메모 · 보낼 줄 {n}" if lines else "메모")

    def set_attach_text(self, text: str) -> None:
        self._attach.setText(text)

    def extra_text(self) -> str:
        return self._extra.toPlainText()

    def append_extra(self, text: str) -> None:
        cur = self._extra.toPlainText().rstrip()
        self._extra.setPlainText((cur + "\n" if cur else "") + text)

    def clear_extra(self) -> None:
        self._extra.clear()

    def extra_has_focus(self) -> bool:
        return self._extra.hasFocus()

    def set_pending(self, text: Optional[str]) -> None:
        self._pending.setVisible(bool(text))
        self._pending_lbl.setText(text or "")

    def set_result(self, text: str, ok: bool, *, can_retry: bool = False) -> None:
        self._result.setVisible(bool(text))
        self._result.setText(text)
        self._result.setStyleSheet(f"color: {theme.SUCCESS if ok else _WARN};")
        self._btn_retry.setVisible(can_retry)

    def set_sendable(self, on: bool, tip: str = "") -> None:
        for b in (self._btn_retake, self._btn_cfrm, self._other):
            b.setEnabled(on)
            b.setToolTip(tip)

    # ── 신호 ─────────────────────────────────────────────────────

    def _on_past_version(self, _i: int) -> None:
        self._past_version = str(self._past_versions.currentData() or "")
        self._fill_past()

    def _on_past_clicked(self, item: QListWidgetItem) -> None:
        note = item.data(_ROLE_ID)
        if isinstance(note, dict):
            self.past_note_clicked.emit(note)

    def _on_memo_changed(self, item: QListWidgetItem) -> None:
        if self._memo_guard:
            return
        shape_id = item.data(_ROLE_ID)
        if shape_id is not None:
            self.memo_toggled.emit(int(shape_id), item.checkState() == Qt.CheckState.Checked)

    def _on_other(self, index: int) -> None:
        code = str(self._other.itemData(index) or "")
        self._other.setCurrentIndex(0)
        if code:
            self.status_requested.emit(code)
