"""컨펌 창 오른쪽 칸 — 작업 내용, Note(지난 내용), 메모, 상태 버튼 (시안 2판 모양)."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QGuiApplication, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bpe.core.confirm_checks import STATE_FAIL, STATE_PASS, CheckResult
from bpe.gui.confirm import status_style, style
from bpe.gui.widgets.clickable_image import ClickableImage

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
_ZWSP = "\u200b"  # 폭 0 빈칸 — 긴 경로가 줄 바뀔 자리(복사할 때는 뺀다)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
_THUMB_W, _THUMB_H = 60, 38
_NOTE_THUMB_W, _NOTE_THUMB_H = 150, 94  # Note 에 붙은 그림(한 줄에 둘)
_CC_REMOVE = "cc-remove:"
_CC_SEARCH_DELAY_MS = 300
_CC_LIST_MAX_H = 112
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
    safe = _PATH_BREAK.sub(lambda m: m.group(0) + _ZWSP, escape(text))
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


def _clean_copied(text: str) -> str:
    """복사할 글 다듬기 — 줄 바꿈용으로 끼워 둔 안 보이는 글자를 빼고 줄 구분 글자를 줄 바꿈으로."""
    return text.replace(_ZWSP, "").replace("\u2028", "\n").replace("\u2029", "\n")


def _note_plain(note: Any) -> str:
    """Note 본문 원문(「이 Note 전체 복사」용) — 내용이 없으면 제목."""
    if not isinstance(note, dict):
        return ""
    return (note.get("content") or "").strip() or (note.get("subject") or "").strip()


class _ClickRow(QLabel):
    """누를 수 있는 한 줄(지난 지적). 글을 끌어 고르면 복사할 수 있다."""

    clicked = Signal(object)
    frame_clicked = Signal(int)
    selecting = Signal(object)  # 이 줄에서 글 고르기를 시작했다(다른 줄의 고름은 푼다)

    def __init__(self, html: str, payload: Any) -> None:
        super().__init__(html)
        self._payload = payload
        self._press_pos: Optional[QPoint] = None
        self.setWordWrap(True)
        self.setIndent(0)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        # 글을 고를 수 있어도 키보드 초점은 받지 않는다 — 받으면 ←/→·PgUp/PgDn 을
        # 스크롤 칸이 가져가 프레임·샷 넘기기 단축키가 죽는다. Ctrl+C 는 창이 받아 넘겨준다.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

    def clear_selection(self) -> None:
        if self.hasSelectedText():
            self.setSelection(0, 0)

    def copied_text(self) -> str:
        """끌어 고른 글(복사용으로 다듬은 것). 고른 글이 없으면 빈 글."""
        return _clean_copied(self.selectedText()) if self.hasSelectedText() else ""

    def copy_selection(self) -> bool:
        text = self.copied_text()
        if text:
            QGuiApplication.clipboard().setText(text)
        return bool(text)

    def copy_note(self) -> bool:
        text = _note_plain(self._payload)
        if text:
            QGuiApplication.clipboard().setText(text)
        return bool(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self.selecting.emit(self)
            # 메모 칸 등에 있던 초점을 창으로 돌려, 뒤이은 Ctrl+C 가 이 줄의 글을 복사하게 한다
            top = self.window()
            if top is not None and top is not self:
                top.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pressed, self._press_pos = self._press_pos, None
        if event.button() == Qt.MouseButton.LeftButton and pressed is not None:
            moved = (event.position().toPoint() - pressed).manhattanLength()
            # 끌어서 글을 고른 것이 아니라 그냥 누른 것일 때만 「누름」으로 친다
            if moved < QApplication.startDragDistance() and not self.hasSelectedText():
                self.clicked.emit(self._payload)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = QMenu(self)
        act_copy = menu.addAction("복사")
        act_copy.setEnabled(self.hasSelectedText())
        act_all = menu.addAction("이 Note 전체 복사")
        act_all.setEnabled(bool(_note_plain(self._payload)))
        picked = menu.exec(event.globalPos())
        if picked is act_copy:
            self.copy_selection()
        elif picked is act_all:
            self.copy_note()
        event.accept()


def _images_in_mime(source: QMimeData) -> List[QImage]:
    """클립보드에 든 그림들 — 그림 자체, 또는 탐색기에서 복사한 그림 파일."""
    out: List[QImage] = []
    if source.hasImage():
        data = source.imageData()
        img = data.toImage() if isinstance(data, QPixmap) else data
        if isinstance(img, QImage) and not img.isNull():
            out.append(img)
    elif source.hasUrls():
        for url in source.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(_IMAGE_EXTS):
                img = QImage(path)
                if not img.isNull():
                    out.append(img)
    return out


class _MemoEdit(QPlainTextEdit):
    """메모 글 칸 — 복사한 그림을 Ctrl+V 로 붙이면 글 대신 그림 첨부로 받는다."""

    image_pasted = Signal(object)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        # 표 계산 프로그램처럼 글과 그림이 같이 오는 복사는 글을 붙인다
        if not source.hasText() or source.hasUrls():
            images = _images_in_mime(source)
            if images:
                for img in images:
                    self.image_pasted.emit(img)
                return
        super().insertFromMimeData(source)


class _Thumb(QLabel):
    """붙여 넣은 그림 하나 — 오른쪽 위 × 로 뺀다."""

    remove_clicked = Signal(int)

    def __init__(self, index: int, path: str) -> None:
        super().__init__()
        self._index = index
        self.setFixedSize(_THUMB_W, _THUMB_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background: {style.FIELD}; border: 1px solid {style.EDGE};")
        pm = QPixmap(path)
        if not pm.isNull():
            self.setPixmap(
                pm.scaled(
                    _THUMB_W - 2,
                    _THUMB_H - 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.setToolTip("붙여 넣은 그림 — 노트에 함께 보냅니다")
        x = QPushButton("×", self)
        x.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setToolTip("이 그림 빼기")
        x.setFixedSize(16, 16)
        x.move(_THUMB_W - 17, 1)
        x.setStyleSheet(
            f"QPushButton {{ background: {style.HEADER}; color: {style.TEXT_STRONG}; "
            f"border: 1px solid {style.EDGE}; border-radius: 0px; padding: 0px; "
            f"min-width: 0px; min-height: 0px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {style.FAIL}; }}"
        )
        x.clicked.connect(lambda: self.remove_clicked.emit(self._index))


class ConfirmSidePanel(QWidget):
    status_requested = Signal(str)
    note_requested = Signal()
    ref_frame_requested = Signal()
    nav_requested = Signal(int)
    image_pasted = Signal(object)
    image_remove_requested = Signal(int)
    cc_search_requested = Signal(str)
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
        self._note_images: Dict[int, List[bytes]] = {}  # 노트 id → 붙은 그림들
        self._image_hosts: Dict[int, QWidget] = {}
        self._cc_users: List[Dict[str, Any]] = []
        self._cc_found: List[Dict[str, Any]] = []
        self._cc_timer = QTimer(self)
        self._cc_timer.setSingleShot(True)
        self._cc_timer.setInterval(_CC_SEARCH_DELAY_MS)
        self._cc_timer.timeout.connect(self._emit_cc_search)
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
        self._memo_edit = _MemoEdit()
        self._memo_edit.setPlaceholderText(
            "화면에 글씨 도구(T)로 쓴 글이 여기에 그대로 적힙니다.\n"
            "직접 고치거나 경로·설명을 덧붙여 써도 됩니다.\n"
            "복사한 그림은 Ctrl+V 로 붙입니다."
        )
        self._memo_edit.image_pasted.connect(self.image_pasted)
        self._memo_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._memo_edit.setMinimumHeight(64)
        self._memo_edit.document().setDocumentMargin(4)
        self._memo_edit.setStyleSheet("QPlainTextEdit { padding: 2px 4px; }")
        self._memo_edit.textChanged.connect(self.memo_edited)
        ex.addWidget(self._memo_edit, 1)
        # 붙여 넣은 그림 — 작은 그림으로 줄지어 보이고 × 로 뺀다
        self._thumb_box = QWidget()
        self._thumb_row = QHBoxLayout(self._thumb_box)
        self._thumb_row.setContentsMargins(0, 0, 0, 0)
        self._thumb_row.setSpacing(4)
        self._thumb_scroll = QScrollArea()
        self._thumb_scroll.setWidgetResizable(True)
        self._thumb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thumb_scroll.setFixedHeight(_THUMB_H + 14)
        self._thumb_scroll.setStyleSheet(
            f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: {style.PANEL}; }}"
        )
        self._thumb_scroll.setWidget(self._thumb_box)
        self._thumb_scroll.hide()
        ex.addWidget(self._thumb_scroll)
        self._attach = QLabel("")
        self._attach.setStyleSheet(f"color: {style.DIM}; font-size: {style.FONT_SMALL_PX}px;")
        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(0, 0, 0, 0)
        attach_row.setSpacing(6)
        # 안내 글이 길어도 옆 버튼을 밀어내지 않게 한다
        self._attach.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        attach_row.addWidget(self._attach, 1)
        # 다른 샷의 프레임을 샷 이름으로 찾아 참고 그림으로 붙인다
        self._btn_ref = QPushButton("다른 샷 프레임")
        self._btn_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_ref.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_ref.setToolTip("다른 샷의 프레임을 샷 이름으로 찾아 참고 그림으로 붙입니다")
        self._btn_ref.setStyleSheet(
            f"QPushButton {{ padding: 2px 8px; background: {style.PANEL}; color: {style.TEXT}; "
            f"border: 1px solid {style.EDGE}; font-size: {style.FONT_SMALL_PX}px; }}"
            f"QPushButton:hover {{ background: {style.RAISED}; }}"
        )
        self._btn_ref.clicked.connect(self.ref_frame_requested)
        self._btn_ref.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        attach_row.addWidget(self._btn_ref)
        ex.addLayout(attach_row)
        # 참조(CC) — 이름을 찾아 넣으면 노트의 참조 칸에 들어간다
        self._cc_chips = QLabel("")
        self._cc_chips.setWordWrap(True)
        self._cc_chips.setIndent(0)
        self._cc_chips.setTextFormat(Qt.TextFormat.RichText)
        self._cc_chips.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._cc_chips.setOpenExternalLinks(False)
        self._cc_chips.linkActivated.connect(self._on_cc_link)
        self._cc_chips.hide()
        ex.addWidget(self._cc_chips)
        self._cc_input = QLineEdit()
        self._cc_input.setPlaceholderText("참조(CC)할 사람 이름 검색")
        self._cc_input.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._cc_input.setClearButtonEnabled(True)
        self._cc_input.textChanged.connect(self._on_cc_text)
        self._cc_input.returnPressed.connect(self._add_first_cc)
        ex.addWidget(self._cc_input)
        self._cc_list = QListWidget()
        self._cc_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cc_list.setMaximumHeight(_CC_LIST_MAX_H)
        self._cc_list.setStyleSheet(
            f"QListWidget {{ background: {style.FIELD}; border: 1px solid {style.EDGE}; "
            f"border-radius: 0px; padding: 0px; outline: none; }}"
            f"QListWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {style.EDGE}; }}"
            f"QListWidget::item:hover {{ background: {style.RAISED}; }}"
        )
        self._cc_list.itemClicked.connect(self._on_cc_item)
        self._cc_list.hide()
        ex.addWidget(self._cc_list)
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
        # Annotation 모드: 상태는 그대로 두고 노트만 보낸다(상태 버튼 자리에 이 버튼 하나)
        self._annotation = False
        self._btn_note = QPushButton(" Note 보내기")
        self._btn_note.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_note.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_note.setStyleSheet(
            f"QPushButton {{ height: 32px; background: {style.ACCENT}; color: {style.ON_ACCENT}; "
            f"border: 1px solid {style.EDGE}; {style.mono(13, bold=True)} }}"
            f"QPushButton:hover {{ border: 1px solid {style.TEXT_STRONG}; }}"
            f"QPushButton:disabled {{ color: #6a6a6a; background: #2c2c2c; }}"
        )
        self._btn_note.clicked.connect(self.note_requested)
        self._btn_note.hide()
        actions.addWidget(self._btn_note, 1)
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
        # 샷 넘기기 — 상태 버튼 바로 아래, 같은 높이의 긴 버튼
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(6)
        self._btn_prev = QPushButton(" 이전 샷")
        self._btn_next = QPushButton(" 다음 샷")
        style.set_icon(self._btn_prev, "chev_left", size=14)
        style.set_icon(self._btn_next, "chev_right", size=14)
        self._btn_next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._btn_prev.setToolTip("이전 샷 (PageUp)")
        self._btn_next.setToolTip("다음 샷 (PageDown)")
        for b in (self._btn_prev, self._btn_next):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ height: 32px; background: {style.PANEL}; color: {style.TEXT}; "
                f"border: 1px solid {style.EDGE}; }}"
                f"QPushButton:hover {{ background: {style.RAISED}; }}"
                f"QPushButton:disabled {{ color: #6a6a6a; }}"
            )
        self._btn_prev.clicked.connect(lambda: self.nav_requested.emit(-1))
        self._btn_next.clicked.connect(lambda: self.nav_requested.emit(1))
        self._nav_pos = QLabel("")
        self._nav_pos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_pos.setMinimumWidth(64)
        self._nav_pos.setStyleSheet(f"color: {style.DIM}; border: none; {style.mono()}")
        nav.addWidget(self._btn_prev, 1)
        nav.addWidget(self._nav_pos)
        nav.addWidget(self._btn_next, 1)
        fcol.addLayout(nav)
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
        """검사 항목을 줄마다 보여 준다 — 전부 통과여도 줄이지 않는다(통과는 초록 글씨)."""
        colors = {STATE_PASS: style.OK, STATE_FAIL: style.FAIL}
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
        alive = {int(n["note_id"]) for n in self._past if n.get("note_id") is not None}
        self._note_images = {k: v for k, v in self._note_images.items() if k in alive}
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

    def set_note_images(self, images: Dict[int, List[bytes]]) -> None:
        """노트에 붙은 그림을 그 노트 아래에 작은 그림으로 보인다 — 누르면 크게 뜬다."""
        for note_id, blobs in images.items():
            self._note_images[int(note_id)] = list(blobs)
            self._fill_note_images(int(note_id))

    def note_image_count(self, note_id: int) -> int:
        host = self._image_hosts.get(int(note_id))
        return host.layout().count() if host is not None else 0

    def _fill_note_images(self, note_id: int) -> None:
        host = self._image_hosts.get(note_id)
        if host is None:
            return
        grid = host.layout()
        while grid.count():
            w = grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        shown: List[ClickableImage] = []
        for data in self._note_images.get(note_id) or []:
            ci = ClickableImage(host)
            ci.THUMB_W, ci.THUMB_H = _NOTE_THUMB_W, _NOTE_THUMB_H
            ci.set_image_bytes(data)
            if ci.original_pixmap() is None:  # 그림으로 못 읽는 첨부
                ci.setParent(None)
                ci.deleteLater()
                continue
            ci.setToolTip("누르면 크게 봅니다")
            grid.addWidget(ci, len(shown) // 2, len(shown) % 2)
            shown.append(ci)
        pixmaps = [ci.original_pixmap() for ci in shown]
        if len(shown) > 1:
            for i, ci in enumerate(shown):
                ci.set_siblings(pixmaps, i)  # 크게 본 창에서 앞뒤 그림으로 넘긴다
        host.setVisible(bool(shown))

    def _fill_past(self, *_args: Any) -> None:
        self._past_rows = []
        self._image_hosts = {}
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
            row.selecting.connect(self._on_past_selecting)
            self._past_rows.append(row)
            self._past_col.addWidget(row)
            if n.get("note_id") is not None:
                host = _clear_block()
                grid = QGridLayout(host)
                grid.setContentsMargins(8, 6, 8, 8)
                grid.setSpacing(6)
                grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                host.hide()
                self._image_hosts[int(n["note_id"])] = host
                self._past_col.addWidget(host)
                self._fill_note_images(int(n["note_id"]))
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

    # ── 샷 넘기기 ────────────────────────────────────────────────

    def set_nav(self, text: str, can_prev: bool, can_next: bool) -> None:
        """「8 / 44」 글과 이전·다음 버튼 켜짐."""
        self._nav_pos.setText(text)
        self._btn_prev.setEnabled(can_prev)
        self._btn_next.setEnabled(can_next)

    def nav_text(self) -> str:
        return self._nav_pos.text()

    def nav_enabled(self) -> Tuple[bool, bool]:
        return (self._btn_prev.isEnabled(), self._btn_next.isEnabled())

    # ── 붙여 넣은 그림 ───────────────────────────────────────────

    def set_pasted_images(self, paths: List[str]) -> None:
        while self._thumb_row.count():
            item = self._thumb_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, path in enumerate(paths):
            thumb = _Thumb(i, path)
            thumb.remove_clicked.connect(self.image_remove_requested)
            self._thumb_row.addWidget(thumb)
        self._thumb_row.addStretch(1)
        self._thumb_scroll.setVisible(bool(paths))

    def pasted_count(self) -> int:
        return sum(
            1
            for i in range(self._thumb_row.count())
            if isinstance(self._thumb_row.itemAt(i).widget(), _Thumb)
        )

    # ── 참조(CC) ─────────────────────────────────────────────────

    def cc_users(self) -> List[Dict[str, Any]]:
        """노트의 참조 칸에 넣을 사람들: ``{"type": "HumanUser", "id": …}``."""
        return [{"type": "HumanUser", "id": int(u["id"])} for u in self._cc_users]

    def cc_names(self) -> List[str]:
        return [str(u.get("name") or "") for u in self._cc_users]

    def clear_cc(self) -> None:
        self._cc_users = []
        self._cc_input.clear()
        self._hide_cc_list()
        self._paint_cc()

    def add_cc_user(self, user: Dict[str, Any]) -> bool:
        try:
            uid = int(user["id"])
        except (KeyError, TypeError, ValueError):
            return False
        if any(int(u["id"]) == uid for u in self._cc_users):
            return False
        name = str(user.get("name") or user.get("login") or uid).strip()
        self._cc_users.append({"id": uid, "name": name})
        self._paint_cc()
        return True

    def set_cc_results(self, rows: List[Dict[str, Any]]) -> None:
        """검색 결과를 입력 칸 아래에 펼친다. 이미 넣은 사람은 뺀다."""
        have = {int(u["id"]) for u in self._cc_users}
        self._cc_found = [
            r
            for r in rows
            if isinstance(r, dict) and r.get("id") is not None and r["id"] not in have
        ]
        self._cc_list.clear()
        if not self._cc_input.text().strip():
            self._cc_found = []
        for r in self._cc_found:
            name = str(r.get("name") or "").strip()
            login = str(r.get("login") or "").strip()
            item = QListWidgetItem(f"{name}  ({login})" if login and login != name else name)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._cc_list.addItem(item)
        if self._cc_found:
            self._cc_list.setFixedHeight(
                min(_CC_LIST_MAX_H, self._cc_list.sizeHintForRow(0) * len(self._cc_found) + 4)
            )
        self._cc_list.setVisible(bool(self._cc_found))

    def _paint_cc(self) -> None:
        chips = "  ".join(
            f'<span style="color:{style.TEXT_STRONG}">{escape(str(u["name"]))}</span>'
            f'<a href="{_CC_REMOVE}{u["id"]}" style="color:{style.DIM}; '
            f'text-decoration:none"> ×</a>'
            for u in self._cc_users
        )
        self._cc_chips.setText(f'<span style="color:{style.DIM}">참조</span>  {chips}')
        self._cc_chips.setVisible(bool(self._cc_users))

    def _hide_cc_list(self) -> None:
        self._cc_found = []
        self._cc_list.clear()
        self._cc_list.hide()

    def _on_cc_text(self, text: str) -> None:
        self._cc_timer.stop()
        if text.strip():
            self._cc_timer.start()
        else:
            self._hide_cc_list()

    def _emit_cc_search(self) -> None:
        text = self._cc_input.text().strip()
        if text:
            self.cc_search_requested.emit(text)

    def _take_cc(self, user: Dict[str, Any]) -> None:
        self.add_cc_user(user)
        self._cc_input.clear()
        self._hide_cc_list()

    def _on_cc_item(self, item: QListWidgetItem) -> None:
        user = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(user, dict):
            self._take_cc(user)

    def _add_first_cc(self) -> None:
        if self._cc_found:
            self._take_cc(self._cc_found[0])

    def _on_cc_link(self, href: str) -> None:
        if href.startswith(_CC_REMOVE) and href[len(_CC_REMOVE) :].isdigit():
            uid = int(href[len(_CC_REMOVE) :])
            self._cc_users = [u for u in self._cc_users if int(u["id"]) != uid]
            self._paint_cc()

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
        self._btn_note.setEnabled(on)
        self._btn_note.setToolTip(tip or "메모·그림을 이 샷의 Note 로 보냅니다 (상태는 그대로)")

    def can_send(self) -> bool:
        return (self._btn_note if self._annotation else self._btn_retake).isEnabled()

    def set_annotation(self, on: bool) -> None:
        """Annotation 모드 — 상태 버튼들 대신 「Note 보내기」 하나만 보인다."""
        self._annotation = bool(on)
        for b in (self._btn_retake, self._btn_cfrm, self._other):
            b.setVisible(not on)
        self._btn_note.setVisible(on)

    def is_annotation(self) -> bool:
        return self._annotation

    # ── 신호 ─────────────────────────────────────────────────────

    def _on_past_selecting(self, row: object) -> None:
        """한 줄에서 글 고르기를 시작하면 다른 줄에 남은 고름은 푼다."""
        for other in self._past_rows:
            if other is not row:
                other.clear_selection()

    def copy_note_selection(self) -> bool:
        """지난 Note 에서 끌어 고른 글을 클립보드에 넣는다(창의 Ctrl+C). 고른 글이 없으면 False."""
        return any(row.copy_selection() for row in self._past_rows)

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
