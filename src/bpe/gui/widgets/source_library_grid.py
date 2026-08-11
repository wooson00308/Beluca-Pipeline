# @cursor-change: 2026-08-07, 0.10.x, 소스 라이브러리 가상화 그리드 (드래그 아웃)
"""소스 라이브러리 썸네일 그리드.

수만 개 항목을 다루므로 항목마다 위젯을 만들지 않는다. ``QListView`` + 모델로
가상화하고, 썸네일은 **화면에 보이는 셀이 그려질 때만** 백그라운드에서 만든다.

가벼움을 위한 장치:

* DB 조회는 페이지 단위(:data:`_PAGE_SIZE`)로 나눠 스크롤할 때 조금씩 가져온다.
* 동시에 진행 중인 썸네일 작업 수를 :data:`_MAX_INFLIGHT` 로 묶어 빠르게 스크롤해도
  ffmpeg 작업이 밀리지 않는다.
* 메모리에 올려 두는 ``QPixmap`` 수를 :data:`_PIX_CACHE_MAX` 로 제한한다.
* 호버 스크럽은 하지 않는다 — 마우스를 올려도 배경 ffmpeg 가 뜨지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Set

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from bpe.core import media_thumbs
from bpe.core import source_library_db as db
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.source_library_scan import (
    KIND_MOVIE,
    row_first_frame_path,
    row_frame_label,
    row_pattern_path,
    row_representative_path,
)
from bpe.gui import theme

logger = get_logger("gui.widgets.source_library_grid")

ROW_ROLE = int(Qt.ItemDataRole.UserRole)
THUMB_ROLE = int(Qt.ItemDataRole.UserRole) + 1

_PAGE_SIZE = 300
_MAX_INFLIGHT = 16
_PIX_CACHE_MAX = 400
# 브라우징용 디코드 상한 — 셀(168)보다 조금만 크게. 크면 ffmpeg 만 느려진다.
_THUMB_PX_CAP = 192
# 스크롤이 멈춘 뒤 보이는 셀을 한꺼번에 요청하기 전 대기
_SETTLE_MS = 80
# 한 번에 그리드에 올리는 최대 항목 수. 이보다 많으면 앞부분만 보여주고 좁히도록 안내한다.
MAX_LOADED_ROWS = 4000

THUMB_W = 168
THUMB_H = 94
_TEXT_H = 34
CELL_W = THUMB_W + 10
CELL_H = THUMB_H + _TEXT_H + 10


def thumb_key(row: Dict[str, Any]) -> str:
    """썸네일 캐시 키 — 대표 파일 경로 + 인덱스에 기록된 크기/수정시각."""
    return media_thumbs.make_key(
        row_representative_path(row),
        int(row.get("size_bytes") or 0),
        float(row.get("mtime") or 0.0),
    )


class _TaskSignals(QObject):
    thumb_ready = Signal(str, int)  # 캐시 키, generation


class _ThumbTask(QRunnable):
    """썸네일 한 장을 만드는 백그라운드 작업 (ffmpeg 1회)."""

    def __init__(
        self,
        signals: _TaskSignals,
        row: Dict[str, Any],
        key: str,
        thumb_px: int,
        generation: int,
    ) -> None:
        super().__init__()
        self._signals = signals
        self._row = dict(row)
        self._key = key
        self._thumb_px = int(thumb_px)
        self._generation = int(generation)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            src = normalize_path_str(row_representative_path(self._row))
            if str(self._row.get("kind") or "") == KIND_MOVIE:
                media_thumbs.ensure_movie_thumbnail(src, self._key, self._thumb_px)
            else:
                media_thumbs.ensure_still_thumbnail(src, self._key, self._thumb_px)
        except Exception as exc:
            logger.debug("썸네일 작업 실패: %s", exc)
        self._signals.thumb_ready.emit(self._key, self._generation)


class SourceLibraryModel(QAbstractListModel):
    """인덱스(SQLite)를 페이지 단위로 읽어오는 가상화 모델."""

    def __init__(self, conn: sqlite3.Connection, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._rows: List[Dict[str, Any]] = []
        self._total = 0
        self._roots: List[str] = []
        self._category = ""
        self._dir_rel = ""
        self._query = ""
        self._folders: Optional[List[db.FolderKey]] = None
        self._thumb_px = media_thumbs.THUMB_PX_DEFAULT
        self._generation = 0
        self._cursor: Optional[db.ItemCursor] = None

        self._pix: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._pending_thumbs: Set[str] = set()
        self._failed: Set[str] = set()
        # 캐시 키 → 그 키를 쓰는 행 번호. 썸네일이 완성됐을 때 다시 그릴 셀을 O(1)로 찾는다.
        self._rows_by_thumb_key: Dict[str, List[int]] = {}

        self._signals = _TaskSignals()
        self._signals.thumb_ready.connect(self._on_thumb_ready)
        self._pool = QThreadPool(self)
        # ffmpeg 프로세스가 동시에 너무 많이 뜨지 않게 제한한다.
        self._pool.setMaxThreadCount(3)

    # ── 필터 / 데이터 로딩 ──────────────────────────────────────────

    def set_thumb_px(self, px: int) -> None:
        self._thumb_px = max(64, min(_THUMB_PX_CAP, int(px)))

    def set_filter(
        self,
        roots: Sequence[str],
        category: str = "",
        dir_rel: str = "",
        query: str = "",
        folders: Optional[Sequence[db.FolderKey]] = None,
    ) -> None:
        """조건을 바꾸고 첫 페이지만 다시 읽는다 (진행 중 썸네일 작업은 버린다)."""
        self._roots = [str(r) for r in roots]
        self._category = category or ""
        self._dir_rel = dir_rel or ""
        self._query = query or ""
        self._folders = list(folders) if folders else None
        self._generation += 1
        self._pending_thumbs.clear()
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._rows_by_thumb_key = {}
        self._cursor = None
        try:
            self._total = db.count_items(
                self._conn,
                roots=self._roots,
                category=self._category,
                dir_rel=self._dir_rel,
                query=self._query,
                folders=self._folders,
            )
        except sqlite3.DatabaseError as exc:
            logger.warning("인덱스 조회 실패: %s", exc)
            self._total = 0
        self.endResetModel()
        self._fetch_page()

    def _fetch_page(self) -> None:
        remaining = self.load_limit() - len(self._rows)
        if remaining <= 0:
            return
        try:
            page = db.fetch_items(
                self._conn,
                roots=self._roots,
                category=self._category,
                dir_rel=self._dir_rel,
                query=self._query,
                limit=min(_PAGE_SIZE, remaining),
                after=self._cursor,
                folders=self._folders,
            )
        except sqlite3.DatabaseError as exc:
            logger.warning("인덱스 페이지 조회 실패: %s", exc)
            return
        if not page:
            self._total = len(self._rows)
            return
        self._cursor = db.cursor_of(page[-1])
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(page) - 1)
        for offset, row in enumerate(page):
            # 해시는 행을 읽어올 때 한 번만 계산한다 (매 페인트마다 다시 하면 낭비).
            tkey = thumb_key(row)
            row["thumb_key"] = tkey
            self._rows_by_thumb_key.setdefault(tkey, []).append(start + offset)
        self._rows.extend(page)
        self.endInsertRows()

    def total_count(self) -> int:
        """필터에 걸리는 전체 항목 수 (아직 화면에 안 읽어온 것 포함)."""
        return self._total

    def load_limit(self) -> int:
        """실제로 그리드에 올릴 항목 수 (상한 적용)."""
        return min(self._total, MAX_LOADED_ROWS)

    def is_truncated(self) -> bool:
        """상한 때문에 일부만 보여주는 상태인지."""
        return self._total > MAX_LOADED_ROWS

    # ── QAbstractListModel ─────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid():
            return False
        return len(self._rows) < self.load_limit()

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # noqa: N802
        if parent.isValid():
            return
        self._fetch_page()

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return str(row.get("name") or "")
        if role == ROW_ROLE:
            return row
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return normalize_path_str(row_pattern_path(row))
        if role == THUMB_ROLE:
            return self._pixmap_for(row)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled
        return base

    # ── 썸네일 ──────────────────────────────────────────────────────

    def _pixmap_for(self, row: Dict[str, Any]) -> Optional[QPixmap]:
        key = str(row.get("thumb_key") or thumb_key(row))
        pm = self._pix.get(key)
        if pm is not None:
            return pm
        cached = media_thumbs.thumb_file(key)
        if cached.is_file():
            loaded = QPixmap(str(cached))
            if not loaded.isNull():
                self._store_pixmap(key, loaded)
                return loaded
        self._request_thumb(row, key)
        return None

    def pixmap_for_row(self, row: Dict[str, Any]) -> Optional[QPixmap]:
        """프리뷰에 즉시 띄울 캐시된 썸네일 (없으면 None — ffmpeg 요청은 하지 않음)."""
        key = str(row.get("thumb_key") or thumb_key(row))
        pm = self._pix.get(key)
        if pm is not None:
            return pm
        cached = media_thumbs.thumb_file(key)
        if cached.is_file():
            loaded = QPixmap(str(cached))
            if not loaded.isNull():
                self._store_pixmap(key, loaded)
                return loaded
        return None

    def _store_pixmap(self, key: str, pm: QPixmap) -> None:
        # 셀 크기에 맞춰 미리 줄여 둔다 — 스크롤할 때마다 다시 스케일하지 않도록.
        if pm.width() > THUMB_W or pm.height() > THUMB_H:
            pm = pm.scaled(
                QSize(THUMB_W, THUMB_H),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self._pix[key] = pm
        while len(self._pix) > _PIX_CACHE_MAX:
            self._pix.popitem(last=False)

    def _request_thumb(self, row: Dict[str, Any], key: str) -> None:
        if key in self._pending_thumbs or key in self._failed:
            return
        if media_thumbs.is_failed(key):
            self._failed.add(key)
            return
        # 빠르게 스크롤할 때 작업이 무한정 쌓이지 않도록 동시 요청 수를 묶는다.
        if len(self._pending_thumbs) >= _MAX_INFLIGHT:
            return
        self._pending_thumbs.add(key)
        self._pool.start(_ThumbTask(self._signals, row, key, self._thumb_px, self._generation))

    def _on_thumb_ready(self, key: str, generation: int) -> None:
        self._pending_thumbs.discard(key)
        if generation != self._generation:
            return
        path = media_thumbs.thumb_file(key)
        if not path.is_file():
            self._failed.add(key)
            return
        pm = QPixmap(str(path))
        if pm.isNull():
            self._failed.add(key)
            return
        self._store_pixmap(key, pm)
        self._emit_changed_for_key(key)

    def _emit_changed_for_key(self, key: str) -> None:
        """같은 캐시 키를 쓰는 셀만 다시 그리게 한다."""
        for i in self._rows_by_thumb_key.get(key, []):
            if 0 <= i < len(self._rows):
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [THUMB_ROLE])

    def shutdown(self) -> None:
        """팝업이 닫힐 때 대기 중인 썸네일 작업을 정리한다."""
        self._generation += 1
        self._pool.clear()
        self._pool.waitForDone(3000)


class _ItemDelegate(QStyledItemDelegate):
    """셀 하나를 직접 그린다 (셀마다 위젯을 만들지 않기 위해)."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._name_font = QFont()
        self._name_font.setPixelSize(theme.FONT_SIZE_SMALL)
        self._sub_font = QFont()
        self._sub_font.setPixelSize(theme.FONT_SIZE_SMALL - 1)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(CELL_W, CELL_H)

    def paint(  # noqa: N802
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        row = index.data(ROW_ROLE) or {}
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(rect, QColor(theme.PANEL_BG))

        img_rect = QRect(rect.x(), rect.y(), rect.width(), rect.height() - _TEXT_H)
        pm = index.data(THUMB_ROLE)
        if isinstance(pm, QPixmap) and not pm.isNull():
            if pm.width() > img_rect.width() or pm.height() > img_rect.height():
                pm = pm.scaled(
                    img_rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            x = img_rect.x() + (img_rect.width() - pm.width()) // 2
            y = img_rect.y() + (img_rect.height() - pm.height()) // 2
            painter.fillRect(img_rect, QColor("#101012"))
            painter.drawPixmap(x, y, pm)
        else:
            painter.fillRect(img_rect, QColor("#101012"))
            painter.setPen(QPen(QColor(theme.TEXT_DIM)))
            painter.setFont(self._sub_font)
            painter.drawText(img_rect, int(Qt.AlignmentFlag.AlignCenter), "…")

        text_rect = QRect(
            rect.x() + 4,
            img_rect.bottom() + 2,
            rect.width() - 8,
            _TEXT_H - 4,
        )
        painter.setFont(self._name_font)
        painter.setPen(QPen(QColor(theme.TEXT if selected or hovered else theme.TEXT_LABEL)))
        fm = QFontMetrics(self._name_font)
        name = fm.elidedText(
            str(row.get("name") or ""), Qt.TextElideMode.ElideMiddle, text_rect.width()
        )
        painter.drawText(
            QRect(text_rect.x(), text_rect.y(), text_rect.width(), 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name,
        )
        painter.setFont(self._sub_font)
        painter.setPen(QPen(QColor(theme.TEXT_DIM)))
        painter.drawText(
            QRect(text_rect.x(), text_rect.y() + 15, text_rect.width(), 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            row_frame_label(row),
        )

        border = theme.ACCENT if selected else (theme.BORDER_FOCUS if hovered else theme.BORDER)
        painter.setPen(QPen(QColor(border), 2 if selected else 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.restore()


class SourceLibraryGrid(QListView):
    """썸네일 그리드 — 다중 선택·앱 밖 드래그를 지원한다."""

    item_selected = Signal(object)  # Dict[str, Any] — 마지막(현재) 선택
    item_activated = Signal(object)
    selection_rows_changed = Signal(object)  # List[Dict]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(_PAGE_SIZE)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CELL_W, CELL_H))
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(False)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setItemDelegate(_ItemDelegate(self))
        self.setStyleSheet(
            "QListView {{ background-color: {bg}; border: 1px solid {bd};"
            " border-radius: 4px; }}".format(bg=theme.BG, bd=theme.BORDER)
        )
        self.doubleClicked.connect(self._on_double_clicked)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_MS)
        self._settle_timer.timeout.connect(self._prefetch_visible)
        sb = self.verticalScrollBar()
        if sb is not None:
            sb.valueChanged.connect(lambda *_: self._settle_timer.start())

    def setModel(self, model: Any) -> None:  # noqa: N802
        super().setModel(model)
        sel = self.selectionModel()
        if sel is not None:
            sel.currentChanged.connect(self._on_current_changed)
            sel.selectionChanged.connect(self._on_selection_changed)

    def selected_rows(self) -> List[Dict[str, Any]]:
        """선택된 항목들 (표시 순서)."""
        rows: List[Dict[str, Any]] = []
        seen: Set[int] = set()
        for idx in self.selectedIndexes():
            if not idx.isValid():
                continue
            r = int(idx.row())
            if r in seen:
                continue
            seen.add(r)
            data = idx.data(ROW_ROLE)
            if isinstance(data, dict):
                rows.append(dict(data))
        return rows

    def _on_current_changed(self, current: QModelIndex, _prev: QModelIndex) -> None:
        row = current.data(ROW_ROLE) if current.isValid() else None
        if row:
            self.item_selected.emit(row)

    def _on_selection_changed(self, *_args: Any) -> None:
        self.selection_rows_changed.emit(self.selected_rows())

    def _on_double_clicked(self, index: QModelIndex) -> None:
        row = index.data(ROW_ROLE)
        if row:
            self.item_activated.emit(row)

    def _prefetch_visible(self) -> None:
        """스크롤이 멈춘 뒤 화면에 보이는 셀의 썸네일을 요청한다."""
        model = self.model()
        if not isinstance(model, SourceLibraryModel):
            return
        vp = self.viewport()
        if vp is None:
            return
        rect = vp.rect()
        tall = QRect(rect.x(), rect.y(), rect.width(), rect.height() + CELL_H)
        first = self.indexAt(tall.topLeft())
        last = self.indexAt(tall.bottomRight())
        if not first.isValid():
            return
        start = first.row()
        end = last.row() if last.isValid() else min(start + 40, model.rowCount() - 1)
        end = max(end, start)
        for r in range(start, end + 1):
            idx = model.index(r, 0)
            if idx.isValid():
                # THUMB_ROLE 조회가 캐시 미스 시 ffmpeg 요청을 건다
                idx.data(THUMB_ROLE)

    # ── 드래그 아웃 (Nuke 등 외부 앱으로) ──────────────────────────

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802
        rows = self.selected_rows()
        if not rows:
            index = self.currentIndex()
            if index.isValid():
                one = index.data(ROW_ROLE)
                if isinstance(one, dict):
                    rows = [one]
        if not rows:
            return
        mime = QMimeData()
        urls = []
        for row in rows:
            file_path = normalize_path_str(row_first_frame_path(row))
            urls.append(QUrl.fromLocalFile(file_path))
        mime.setUrls(urls)
        # text(Tcl 스니펫) MIME 을 일부러 안 싣는다 — Nuke 가 urls 보다 text 를 우선
        # 해석하는 것으로 보이는데, 한글 경로가 Tcl 텍스트 파싱에서 깨진다.
        # urls(QUrl.fromLocalFile) 만 남기면 Nuke 네이티브 드롭으로 Read 노드가
        # 만들어져 한글 경로가 안 깨진다. 시퀀스 프레임 범위는
        # nuke_plugin.library_import 의 onCreate 콜백이 인덱스 값으로 사후 교정한다.
        logger.info("라이브러리 드래그 시작: %d개", len(rows))
        drag = QDrag(self)
        drag.setMimeData(mime)
        index = self.currentIndex()
        pm = index.data(THUMB_ROLE) if index.isValid() else None
        if isinstance(pm, QPixmap) and not pm.isNull():
            small = pm.scaled(
                QSize(96, 54),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            drag.setPixmap(small)
            drag.setHotSpot(QPoint(small.width() // 2, small.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)
