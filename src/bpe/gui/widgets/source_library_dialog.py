"""소스 라이브러리 팝업 — My Tasks 에서 연다.

구성: 왼쪽에 16:9 프리뷰 + 폴더 트리, 오른쪽에 썸네일 그리드.
하위 폴더가 있으면 리프를 고를 때만 그리드가 채워진다.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bpe.core import media_thumbs
from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core import source_library_publish as publish
from bpe.core.library_reveal import row_reveal_path, windows_explorer_select_args
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.settings import get_source_library_settings
from bpe.core.source_library_scan import row_dir_path, row_pattern_path
from bpe.gui import theme
from bpe.gui.widgets.lock_overlay import LockOverlay
from bpe.gui.widgets.sequence_scrub_widget import MediaPreviewWidget
from bpe.gui.widgets.source_library_grid import SourceLibraryGrid, SourceLibraryModel
from bpe.gui.widgets.source_library_settings_dialog import SourceLibrarySettingsDialog
from bpe.gui.workers.index_sync_worker import IndexSyncWorker
from bpe.gui.workers.library_scan_worker import LibraryScanWorker

logger = get_logger("gui.widgets.source_library_dialog")

_SEARCH_DELAY_MS = 220
_ROLE_KIND = int(Qt.ItemDataRole.UserRole)
_ROLE_PAYLOAD = int(Qt.ItemDataRole.UserRole) + 1

_KIND_GROUP = "group"
_KIND_FOLDER = "folder"
_KIND_NESTED = "nested"
_EMPTY_FOLDERS: List[db.FolderKey] = [("__none__", "__none__")]

_admin_unlocked_this_session = False
"""Source Library 설정 관리자 잠금 — 앱을 켜둔 동안(프로세스 수명) 한 번만 물어본다."""

_nuke_plugin_warning_shown_this_session = False
"""Nuke 플러그인 자동 동기화 결과 안내 — 라이브러리 창 열 때마다 반복하지 않고 한 번만."""


class SourceLibraryDialog(QDialog):
    """소스 라이브러리 브라우저."""

    path_copied = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        project_id: Optional[Any] = None,
        project_name: str = "",
        projects: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Source Library")
        self.setMinimumSize(1500, 820)
        self._clamp_and_resize(2000, 1080)

        self._settings: Dict[str, Any] = get_source_library_settings()
        # project_id/projects 는 My Tasks 호환용으로만 받고 뷰에는 쓰지 않는다.
        _ = project_id
        _ = project_name
        self._projects: List[Dict[str, Any]] = list(projects or [])

        self._library = libcfg.load_library()
        self._pending_load_warning: Optional[str] = libcfg.probe_library_read()
        self._roots: List[str] = libcfg.roots_for_view(self._library)
        self._conn: Optional[sqlite3.Connection] = None
        self._model: Optional[SourceLibraryModel] = None
        self._scan_worker: Optional[LibraryScanWorker] = None
        self._index_sync_worker: Optional[IndexSyncWorker] = None
        self._scan_queue: List[Dict[str, Any]] = []
        self._scan_publish = True
        self._current_row: Dict[str, Any] = {}
        self._selected_rows: List[Dict[str, Any]] = []
        self._shutdown_done = False
        self._path_full = ""
        self._filter_folders: Optional[List[db.FolderKey]] = list(_EMPTY_FOLDERS)
        self._filter_category = ""
        self._filter_dir_rel = ""
        self._filter_roots: List[str] = []
        self._awaiting_subcategory = True
        self._left_col: Optional[QWidget] = None
        self._main_splitter: Optional[QSplitter] = None

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_filter)

        self._build_ui()
        self._sync_index()
        self._open_index()
        self._reload_tree(initial=True)
        # 등록 루트 중 로컬 인덱스에 없는 게 있을 때만 스캔 폴백 (원본은 읽기만).
        # 전역 건수(model.total_count()/db.total_indexed())로 판정하면 안 된다 —
        # 루트를 새로 추가하거나 빼면 유령 데이터 때문에 오작동한다("서버에 등록하면
        # 다른 PC도 자동 공유"라는 요구를 못 지킴). roots_missing_from_local()은
        # 등록 루트 기준으로 보고 내부적으로 예외도 안전 처리한다.
        missing_roots = publish.roots_missing_from_local(self._roots) if self._roots else []
        if missing_roots:
            outdated = publish.shared_grouping_outdated()
            if outdated:
                self._status_label.setText("공유 인덱스가 구버전 형식 — 다시 스캔·게시합니다.")
            if not publish.read_shared_meta().get("published_at") or outdated:
                self.enqueue_library_scan(self._roots, force=False, publish=True)

    def _clamp_and_resize(self, w: int, h: int) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            w = min(w, int(geo.width() * 0.92))
            h = min(h, int(geo.height() * 0.92))
        self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("Source Library")
        title.setObjectName("page_title")
        top.addWidget(title)
        self._count_label = QLabel("")
        self._count_label.setObjectName("page_subtitle")
        top.addWidget(self._count_label)
        top.addStretch()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("이름으로 검색")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(240)
        self._search_edit.textChanged.connect(lambda: self._search_timer.start())
        top.addWidget(self._search_edit)

        gear = QToolButton()
        gear.setText("\u2699")
        gear.setToolTip("라이브러리 설정 (관리자)")
        gear.setFixedSize(36, 28)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(self._on_settings_clicked)
        top.addWidget(gear)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setMinimumWidth(520)
        left.setMaximumWidth(700)
        self._left_col = left
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        self._preview = MediaPreviewWidget()
        self._preview.setMinimumHeight(230)
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        left_lay.addWidget(self._preview, 0)
        left_lay.addSpacing(10)  # 프리뷰와 분류 박스 사이 여백 (라벨↔트리 간격은 유지)

        cat_title = QLabel("분류")
        cat_title.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_LABEL, theme.FONT_SIZE_SMALL)
        )
        left_lay.addWidget(cat_title)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumHeight(280)
        self._tree.setViewportMargins(0, 10, 0, 0)
        self._tree.setStyleSheet(theme.tree_stylesheet())
        self._tree.currentItemChanged.connect(lambda *_: self._on_tree_selection())
        left_lay.addWidget(self._tree, 1)
        splitter.addWidget(left)

        self._grid = SourceLibraryGrid()
        self._grid.item_selected.connect(self._on_item_selected)
        self._grid.item_activated.connect(self._on_item_activated)
        self._grid.selection_rows_changed.connect(self._on_selection_rows)
        splitter.addWidget(self._grid)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 1400])
        self._main_splitter = splitter
        root.addWidget(splitter, 1)
        QTimer.singleShot(0, self._update_preview_aspect)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        # 스캔 취소는 경로 라벨(stretch) **앞**에 둔다 — 보였다 숨었다 할 때 늘고 주는 폭을
        # 라벨이 흡수하므로 오른쪽 버튼들이 좌우로 밀리지 않는다.
        self._scan_cancel_btn = QPushButton("스캔 취소")
        self._scan_cancel_btn.setMinimumHeight(theme.BUTTON_HEIGHT)
        self._scan_cancel_btn.setFixedWidth(90)
        self._scan_cancel_btn.setVisible(False)
        self._scan_cancel_btn.clicked.connect(self._on_cancel_scan)
        bottom.addWidget(self._scan_cancel_btn)

        self._path_label = QLabel("")
        self._path_label.setObjectName("status_msg")
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bottom.addWidget(self._path_label, 1)

        self._copy_btn = QPushButton("경로 복사")
        self._copy_btn.setMinimumWidth(92)
        self._copy_btn.setMinimumHeight(theme.BUTTON_HEIGHT)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy_path)
        bottom.addWidget(self._copy_btn)

        self._open_btn = QPushButton("폴더 열기")
        self._open_btn.setMinimumWidth(92)
        self._open_btn.setMinimumHeight(theme.BUTTON_HEIGHT)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open_folder)
        bottom.addWidget(self._open_btn)

        close_btn = QPushButton("닫기")
        close_btn.setMinimumWidth(80)
        close_btn.setMinimumHeight(theme.BUTTON_HEIGHT)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._status_label = QLabel("")
        self._status_label.setObjectName("status_msg")
        root.addWidget(self._status_label)

        hint = QLabel(
            "다중 선택: Ctrl/Shift+클릭. 그리드에서 Nuke로 드래그하면 Read 노드가 만들어집니다. "
            "소분류를 선택해야 목록이 표시됩니다. "
            "원본은 읽기만 하며 서버 파일을 복사·수정하지 않습니다."
        )
        hint.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_DIM, theme.FONT_SIZE_SMALL)
        )
        root.addWidget(hint)

    # ── 인덱스 / 모델 ───────────────────────────────────────────────

    def _warn_library_load_failed(self) -> None:
        """library.json 이 있는데 읽기·파싱 실패했으면 "최초 사용(비어있음)"과 구분해 알린다."""
        warn = self._pending_load_warning
        if not warn:
            return
        msg = "설정 파일을 못 읽어 이전 상태로 표시 중일 수 있습니다 ({})".format(warn)
        logger.warning("library.json 읽기 실패: %s", warn)
        cur = self._status_label.text() or ""
        if cur:
            self._status_label.setText("{} · {}".format(cur, msg))
        else:
            self._status_label.setText(msg)

    def _warn_ffmpeg_missing(self) -> None:
        """ffmpeg 를 못 찾으면 썸네일이 전부 안 뜨는 이유를 상태줄에 알린다."""
        if media_thumbs.ffmpeg_available():
            return
        msg = "ffmpeg를 찾을 수 없어 썸네일이 안 뜹니다 (배포판을 확인하세요)"
        logger.warning("ffmpeg 사용 불가 — 썸네일 생성 안 됨")
        cur = self._status_label.text() or ""
        if cur:
            self._status_label.setText("{} · {}".format(cur, msg))
        else:
            self._status_label.setText(msg)

    def _warn_nuke_plugin_sync(self) -> None:
        """앱 시작 시 자동 동기화한 Nuke 플러그인 결과(갱신/실패)를 세션당 한 번만 알린다."""
        global _nuke_plugin_warning_shown_this_session
        if _nuke_plugin_warning_shown_this_session:
            return
        try:
            from bpe.core.nuke_plugin_install import last_sync_result
        except Exception:
            return
        result = last_sync_result()
        if not result:
            return
        _nuke_plugin_warning_shown_this_session = True
        msg = ""
        if result.get("error"):
            msg = "Nuke 플러그인 동기화 실패: {}".format(result["error"])
        elif result.get("updated"):
            msg = "Nuke 플러그인이 갱신됐습니다 — Nuke를 이미 켜뒀다면 재시작해야 반영됩니다."
        if not msg:
            return
        cur = self._status_label.text() or ""
        if cur:
            self._status_label.setText("{} · {}".format(cur, msg))
        else:
            self._status_label.setText(msg)

    def _sync_index(self) -> None:
        """빠른 검사(설정 파일·ffmpeg)만 즉시, 실제 네트워크 동기는 백그라운드로.

        예전엔 ``try_pull_index_with_status()``(네트워크 sqlite 복사)를 여기서
        그대로 불러서, 서버가 느리거나 끊기면 창을 여는 순간 전체가 멈춘
        것처럼 보였다. 지금은 현재 로컬 인덱스로 즉시 열어 보여준 뒤,
        동기가 끝나면(새로 받은 게 있을 때만) 조용히 다시 로드한다.
        """
        self._warn_library_load_failed()
        self._warn_ffmpeg_missing()
        self._warn_nuke_plugin_sync()
        self._start_index_sync()

    def _start_index_sync(self) -> None:
        if self._index_sync_worker is not None and self._index_sync_worker.isRunning():
            return
        worker = IndexSyncWorker(self)
        worker.sync_done.connect(self._on_index_sync_done)
        worker.sync_error.connect(self._on_index_sync_error)
        self._index_sync_worker = worker
        worker.start()

    def _on_index_sync_done(self, meta: object) -> None:
        if self._shutdown_done:
            return
        if meta:
            meta_d = meta if isinstance(meta, dict) else {}
            self._status_label.setText(
                "공유 인덱스 동기 ({:,}개, {})".format(
                    int(meta_d.get("items") or 0),
                    meta_d.get("published_at") or "",
                )
            )
            self._warn_empty_group_index()
            # 새로 받은 인덱스를 반영해 조용히 다시 연다 (스캔 중이면 충돌 방지로 건너뜀).
            if not self.is_library_scanning():
                self._reload_after_scan()
            return
        shared = publish.read_shared_meta()
        if shared.get("published_at"):
            if publish.shared_grouping_outdated():
                # pull 이 "구버전 게시본" 사유로 거부된 경우 — "최신"이라고 하면 정반대 오해.
                self._status_label.setText(
                    "공유 인덱스가 구버전 형식이라 받지 않음 — 전체 다시 스캔·게시 필요"
                )
            else:
                self._status_label.setText(
                    "공유 인덱스 최신 ({:,}개)".format(int(shared.get("items") or 0))
                )
        self._warn_empty_group_index()

    def _on_index_sync_error(self, err: str) -> None:
        if self._shutdown_done:
            return
        self._status_label.setText("공유 인덱스 동기 실패: {}".format(err))

    def _warn_empty_group_index(self) -> None:
        """배정은 됐는데 로컬 인덱스가 비어 있는 그룹을 상태줄에 알린다."""
        try:
            gaps = publish.groups_with_empty_index(self._library)
        except Exception as exc:
            logger.debug("그룹 인덱스 경고 실패: %s", exc)
            return
        if not gaps:
            return
        names = [g for g, _roots in gaps[:3]]
        msg = "「{}」인덱스 0개 — 설정에서 전체 스캔 또는 동기 필요".format("」, 「".join(names))
        logger.warning("소스 라이브러리 커버리지: %s", gaps)
        cur = self._status_label.text() or ""
        if cur:
            self._status_label.setText("{} · {}".format(cur, msg))
        else:
            self._status_label.setText(msg)

    def _open_index(self) -> None:
        try:
            self._conn = db.connect()
        except sqlite3.DatabaseError as exc:
            logger.warning("인덱스 열기 실패: %s", exc)
            self._status_label.setText("인덱스를 열 수 없습니다: {}".format(exc))
            return
        self._model = SourceLibraryModel(self._conn, self)
        self._model.set_thumb_px(int(self._settings.get("thumb_px") or 256))
        self._grid.setModel(self._model)

    def _folder_count_map(self) -> Dict[Tuple[str, str], int]:
        if self._conn is None:
            return {}
        try:
            rows = db.list_folders(self._conn, roots=self._roots)
        except sqlite3.DatabaseError:
            return {}
        return {(r, c): n for r, c, n in rows}

    def _count_for_pair(self, root: str, rel: str, counts: Dict[Tuple[str, str], int]) -> int:
        """단일 키 카운트 — 1단계는 벌크 캐시(O(1)), 깊은 dir_rel 은 개별 prefix count."""
        if "/" not in rel:
            return int(counts.get((root, rel), 0))
        if self._conn is None:
            return 0
        try:
            return int(db.count_items(self._conn, folders=[(root, rel)]))
        except sqlite3.DatabaseError:
            return 0

    def _count_for_pairs(
        self, pairs: List[db.FolderKey], counts: Dict[Tuple[str, str], int]
    ) -> int:
        return sum(self._count_for_pair(r, c, counts) for r, c in pairs)

    def _browse_node_key(self, kind: str, payload: Dict[str, Any]) -> Tuple[str, str, str]:
        """확장/선택 복원용 — 가상 폴더는 org_path(전체 경로)를 쓴다."""
        return (
            kind,
            str(payload.get("group") or ""),
            str(payload.get("org_path") or payload.get("nested") or payload.get("category") or ""),
        )

    def _selection_key_for(self, kind: str, payload: Dict[str, Any]) -> str:
        return "{}|{}|{}|{}".format(
            kind,
            payload.get("group") or "",
            payload.get("category") if "category" in payload else "",
            payload.get("org_path") or payload.get("nested") or payload.get("dir_rel") or "",
        )

    def _browse_expand_keys(self) -> set:
        keys = set()

        def walk(item: QTreeWidgetItem) -> None:
            if item.isExpanded():
                kind = str(item.data(0, _ROLE_KIND) or "")
                payload = item.data(0, _ROLE_PAYLOAD) or {}
                if not isinstance(payload, dict):
                    payload = {}
                keys.add(self._browse_node_key(kind, payload))
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is not None:
                walk(top)
        return keys

    def _restore_browse_expand(self, keys: set) -> None:
        if not keys:
            return

        def walk(item: QTreeWidgetItem) -> None:
            kind = str(item.data(0, _ROLE_KIND) or "")
            payload = item.data(0, _ROLE_PAYLOAD) or {}
            if not isinstance(payload, dict):
                payload = {}
            if self._browse_node_key(kind, payload) in keys:
                item.setExpanded(True)
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is not None:
                walk(top)

    def _add_virtual_branch(
        self,
        parent: QTreeWidgetItem,
        vc: Dict[str, Any],
        *,
        gname: str,
        parent_org: str,
        split_roots: List[str],
        payload_roots: List[str],
        counts: Dict[Tuple[str, str], int],
    ) -> None:
        """가상 폴더를 재귀적으로 트리에 붙인다. 리프만 그리드 대상."""
        vname = str(vc.get("name") or "")
        if not vname:
            return
        org_path = libcfg.join_org_path([parent_org, vname]) if parent_org else vname
        direct_keys = libcfg.folder_keys_for_virtual_child(vc, split_roots)
        child_vcs = libcfg.virtual_children(vc)
        vkeys_all = libcfg.folder_keys_for_virtual_subtree(vc, split_roots)
        vn = self._count_for_pairs(vkeys_all, counts)
        has_sub = bool(child_vcs) or len(direct_keys) > 1
        # 리프(하위 없음·키 1개)만 folders 페이로드 — 부모 클릭 시 전체 dump 금지
        leaf_folders: List[db.FolderKey] = [] if has_sub else list(direct_keys)
        v_item = QTreeWidgetItem(["{}  ({:,})".format(vname, vn)])
        v_item.setData(0, _ROLE_KIND, _KIND_NESTED)
        v_item.setData(
            0,
            _ROLE_PAYLOAD,
            {
                "group": gname,
                "nested": vname,
                "org_path": org_path,
                "virtual": True,
                "has_children": has_sub,
                "folders": leaf_folders,
                "roots": list(payload_roots),
            },
        )
        parent.addChild(v_item)
        for child_vc in child_vcs:
            self._add_virtual_branch(
                v_item,
                child_vc,
                gname=gname,
                parent_org=org_path,
                split_roots=split_roots,
                payload_roots=payload_roots,
                counts=counts,
            )
        # 레거시: folders[] 에 여러 abs 가 평탄 들어간 경우 → 각 소분류를 하위 폴더로 표시
        if not child_vcs and len(direct_keys) > 1:
            for root, cat in direct_keys:
                cn = self._count_for_pair(root, cat, counts)
                fname = (cat.rsplit("/", 1)[-1] if cat else "") or "(루트 직속)"
                f_item = QTreeWidgetItem(["{}  ({:,})".format(fname, cn)])
                f_item.setData(0, _ROLE_KIND, _KIND_FOLDER)
                f_item.setData(
                    0,
                    _ROLE_PAYLOAD,
                    {
                        "group": gname,
                        "folders": [(root, cat)],
                        "roots": [root],
                        "category": cat,
                    },
                )
                v_item.addChild(f_item)

    def _reload_tree(self, initial: bool = False) -> None:
        previous = "" if initial else self._current_selection_key()
        expand_keys = set() if initial else self._browse_expand_keys()
        self._tree.blockSignals(True)
        self._tree.clear()
        counts = self._folder_count_map()
        folder_counts = [(r, c, n) for (r, c), n in counts.items()]
        common_roots = libcfg.common_roots_list(self._library)
        all_organized = libcfg.library_organized_paths(self._library)

        for g in libcfg.view_groups(self._library):
            gname = str(g.get("name") or "")
            roots = libcfg.group_roots(g)
            # 키 분할은 common roots (org=folder 빈 folders 에서도 배정 경로 해석)
            split_roots = list(common_roots) if common_roots else list(roots)
            payload_roots = list(common_roots) if common_roots else list(roots)
            # 다른 최상위 폴더(bag)에 들어간 소스도 형제 목록에서 숨김
            organized = all_organized
            cats = [
                (r, c, n)
                for r, c, n in libcfg.category_pairs_for_group(g, folder_counts)
                if not libcfg.is_hidden_folder(self._library, libcfg.folder_abs(r, c))
                and libcfg.folder_abs(r, c) not in organized
            ]
            pairs: List[db.FolderKey] = [(r, c) for r, c, _n in cats]
            bag_keys = libcfg.bag_folder_keys(g, split_roots)
            # 그룹 카운트 = 미정리 + bag + 재귀 가상 트리 전체 키
            n_group = self._count_for_pairs(pairs, counts) + self._count_for_pairs(bag_keys, counts)
            for vc in libcfg.virtual_children(g):
                n_group += self._count_for_pairs(
                    libcfg.folder_keys_for_virtual_subtree(vc, split_roots), counts
                )
            # 최상위 폴더 클릭 = 하위 선택 대기 (전체 dump 금지)
            g_item = QTreeWidgetItem(["{}  ({:,})".format(gname, n_group)])
            g_item.setData(0, _ROLE_KIND, _KIND_GROUP)
            g_item.setData(
                0,
                _ROLE_PAYLOAD,
                {
                    "group": gname,
                    "org_path": gname,
                    "roots": payload_roots if (libcfg.is_org_folder(g) or not roots) else roots,
                    "folders": [],
                    "has_children": True,
                },
            )
            self._tree.addTopLevelItem(g_item)
            # bag 직속 → 폴더 leaf
            for root, cat in bag_keys:
                cn = self._count_for_pair(root, cat, counts)
                fname = (cat.rsplit("/", 1)[-1] if cat else "") or "(루트 직속)"
                f_item = QTreeWidgetItem(["{}  ({:,})".format(fname, cn)])
                f_item.setData(0, _ROLE_KIND, _KIND_FOLDER)
                f_item.setData(
                    0,
                    _ROLE_PAYLOAD,
                    {
                        "group": gname,
                        "folders": [(root, cat)],
                        "roots": [root],
                        "category": cat,
                    },
                )
                g_item.addChild(f_item)
            for vc in libcfg.virtual_children(g):
                self._add_virtual_branch(
                    g_item,
                    vc,
                    gname=gname,
                    parent_org=gname,
                    split_roots=split_roots,
                    payload_roots=payload_roots,
                    counts=counts,
                )
            # 루트 경로에 직접 중첩된 그룹 (설정에서 폴더 안으로 넣은 그룹) — legacy
            for root in roots:
                root_n = libcfg.normalize_path(root)
                for child in libcfg.children_under_anchor(g, root_n):
                    cname = str(child.get("name") or "")
                    child_folders = [
                        libcfg.normalize_path(str(f)) for f in (child.get("folders") or []) if f
                    ]
                    vkeys: List[db.FolderKey] = []
                    for abs_p in child_folders:
                        split = libcfg.split_folder_to_root_category(abs_p, [root_n])
                        if split:
                            vkeys.append(split)
                    if vkeys:
                        n_payload_folders: Optional[List[db.FolderKey]] = vkeys
                        cn = self._count_for_pairs(vkeys, counts)
                    else:
                        n_payload_folders = None
                        cn = 0
                    n_item = QTreeWidgetItem(["{}  ({:,})".format(cname, cn)] if vkeys else cname)
                    n_item.setData(0, _ROLE_KIND, _KIND_NESTED)
                    n_item.setData(
                        0,
                        _ROLE_PAYLOAD,
                        {
                            "group": gname,
                            "nested": cname,
                            "roots": [root_n],
                            "dir_rel": "",
                            "folders": n_payload_folders,
                        },
                    )
                    g_item.addChild(n_item)
            # 미정리 소분류 (organized_paths 제외) — W: 루트 브랜치는 그리지 않음
            for root, cat, cn in cats:
                fname = cat or "(루트 직속)"
                f_item = QTreeWidgetItem(["{}  ({:,})".format(fname, cn)])
                f_item.setData(0, _ROLE_KIND, _KIND_FOLDER)
                f_item.setData(
                    0,
                    _ROLE_PAYLOAD,
                    {
                        "group": gname,
                        "folders": [(root, cat)],
                        "roots": [root],
                        "category": cat,
                    },
                )
                g_item.addChild(f_item)
                if cat:
                    abs_cat = "{}/{}".format(libcfg.normalize_path(root), cat)
                    for child in libcfg.children_under_anchor(g, abs_cat):
                        cname = str(child.get("name") or "")
                        anchor = libcfg.normalize_path(str(child.get("anchor") or ""))
                        split = libcfg.split_folder_to_root_dir_rel(anchor, [root])
                        dir_rel = split[1] if split else cat
                        n_item = QTreeWidgetItem([cname])
                        n_item.setData(0, _ROLE_KIND, _KIND_NESTED)
                        n_item.setData(
                            0,
                            _ROLE_PAYLOAD,
                            {
                                "group": gname,
                                "nested": cname,
                                "roots": [root],
                                "dir_rel": dir_rel,
                                "folders": None,
                            },
                        )
                        f_item.addChild(n_item)

        self._tree.clearSelection()
        self._tree.setCurrentItem(None)
        self._tree.blockSignals(False)
        if initial:
            self._tree.collapseAll()
            self._apply_empty_open()
        else:
            self._restore_browse_expand(expand_keys)
            self._restore_selection(previous)

    def _apply_empty_open(self) -> None:
        """열 때마다: 빈 그리드·프리뷰 정지·트리 접힘."""
        self._awaiting_subcategory = True
        self._filter_folders = list(_EMPTY_FOLDERS)
        self._filter_category = ""
        self._filter_dir_rel = ""
        self._filter_roots = []
        self._current_row = {}
        self._selected_rows = []
        try:
            self._preview.clear()
        except Exception:
            pass
        self._set_path_display("")
        self._set_action_enabled(False)
        self._apply_filter()
        self._status_label.setText("소분류를 선택하세요")

    def _current_selection_key(self) -> str:
        item = self._tree.currentItem()
        if item is None:
            return ""
        kind = str(item.data(0, _ROLE_KIND) or "")
        payload = item.data(0, _ROLE_PAYLOAD) or {}
        if not isinstance(payload, dict):
            return kind
        return self._selection_key_for(kind, payload)

    def _restore_selection(self, key: str) -> None:
        """설정 직후 등 — last_selection 은 쓰지 않음. 키 없으면 빈 화면."""
        if key:
            for item in self._iter_tree_items():
                kind = str(item.data(0, _ROLE_KIND) or "")
                payload = item.data(0, _ROLE_PAYLOAD) or {}
                if not isinstance(payload, dict):
                    continue
                if self._selection_key_for(kind, payload) == key:
                    self._tree.setCurrentItem(item)
                    return
        self._apply_empty_open()

    def _iter_tree_items(self):
        def walk(item: QTreeWidgetItem):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            yield from walk(self._tree.topLevelItem(i))

    def _on_tree_selection(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            self._filter_folders = list(_EMPTY_FOLDERS)
            self._filter_category = ""
            self._filter_dir_rel = ""
            self._filter_roots = []
            self._awaiting_subcategory = True
            self._apply_filter()
            return
        kind = str(item.data(0, _ROLE_KIND) or "")
        payload = item.data(0, _ROLE_PAYLOAD) or {}
        if not isinstance(payload, dict):
            payload = {}
        if kind == _KIND_GROUP:
            self._filter_folders = list(_EMPTY_FOLDERS)
            self._filter_category = ""
            self._filter_dir_rel = ""
            self._filter_roots = []
            self._awaiting_subcategory = True
            self._status_label.setText("소분류를 선택하세요")
        elif kind == _KIND_FOLDER:
            folders = payload.get("folders") or []
            self._filter_folders = [(str(r), str(c)) for r, c in folders]
            self._filter_category = ""
            self._filter_dir_rel = ""
            self._filter_roots = list(payload.get("roots") or [])
            self._awaiting_subcategory = False
            if not self._filter_folders:
                self._filter_folders = list(_EMPTY_FOLDERS)
        elif kind == _KIND_NESTED:
            if payload.get("virtual"):
                if payload.get("has_children") or item.childCount() > 0:
                    self._filter_folders = list(_EMPTY_FOLDERS)
                    self._filter_category = ""
                    self._filter_dir_rel = ""
                    self._filter_roots = []
                    self._awaiting_subcategory = True
                    self._status_label.setText("하위 폴더를 선택하세요")
                else:
                    folders = payload.get("folders") or []
                    self._filter_folders = [(str(r), str(c)) for r, c in folders] or list(
                        _EMPTY_FOLDERS
                    )
                    self._filter_category = ""
                    self._filter_dir_rel = ""
                    self._filter_roots = list(payload.get("roots") or [])
                    self._awaiting_subcategory = False
            elif payload.get("folders") is not None:
                folders = payload.get("folders") or []
                self._filter_folders = [(str(r), str(c)) for r, c in folders] or list(
                    _EMPTY_FOLDERS
                )
                self._filter_category = ""
                self._filter_dir_rel = ""
                self._filter_roots = list(payload.get("roots") or [])
                self._awaiting_subcategory = False
            else:
                self._filter_folders = None
                self._filter_category = ""
                self._filter_dir_rel = str(payload.get("dir_rel") or "")
                self._filter_roots = list(payload.get("roots") or [])
                self._awaiting_subcategory = False
                if not self._filter_dir_rel and not self._filter_roots:
                    self._filter_folders = list(_EMPTY_FOLDERS)
                    self._awaiting_subcategory = True
                elif not self._filter_dir_rel:
                    # 루트 직속 nested: 해당 루트 전체
                    self._filter_folders = None
                    self._filter_dir_rel = ""
                    self._awaiting_subcategory = False
        else:
            self._filter_folders = list(_EMPTY_FOLDERS)
            self._filter_dir_rel = ""
            self._filter_roots = []
            self._awaiting_subcategory = True
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._model is None:
            self._count_label.setText("인덱스가 없습니다")
            return
        self._model.set_filter(
            self._filter_roots,
            category=self._filter_category,
            dir_rel=self._filter_dir_rel,
            query=self._search_edit.text().strip(),
            folders=self._filter_folders,
        )
        self._update_count_label()
        if not self._roots:
            self._count_label.setText("설정(톱니바퀴)에서 소스 폴더를 등록하세요")
        elif self._awaiting_subcategory and not self._search_edit.text().strip():
            self._count_label.setText("소분류를 선택하세요")

    def _update_count_label(self) -> None:
        if self._model is None:
            return
        if self._awaiting_subcategory and not self._search_edit.text().strip():
            self._count_label.setText("소분류를 선택하세요")
            return
        total = self._model.total_count()
        if self._model.is_truncated():
            self._count_label.setText(
                "{:,}개 중 {:,}개만 표시 — 검색으로 좁혀보세요".format(
                    total, self._model.load_limit()
                )
            )
        else:
            self._count_label.setText("{:,}개".format(total))

    # ── 설정 (비밀번호) ─────────────────────────────────────────────

    def _on_settings_clicked(self) -> None:
        global _admin_unlocked_this_session
        if not _admin_unlocked_this_session:
            lock_dlg = QDialog(self)
            lock_dlg.setWindowTitle("Source Library 설정")
            lock_dlg.setMinimumSize(420, 320)
            lay = QVBoxLayout(lock_dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            overlay = LockOverlay(
                lock_dlg,
                title="Source Library 설정",
                hint="관리자만 폴더·그룹을 수정할 수 있습니다.",
            )

            def _unlocked() -> None:
                lock_dlg.accept()

            overlay.unlocked.connect(_unlocked)
            lay.addWidget(overlay)
            if lock_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            # 앱을 켜둔 동안은 다시 안 물어봄 (창을 여러 번 열어도 유지)
            _admin_unlocked_this_session = True

        dlg = SourceLibrarySettingsDialog(self)
        dlg.exec()
        # 설정 반영 (스캔 중이면 pull 생략 — 로컬 writer 와 충돌 방지)
        self._library = libcfg.load_library()
        self._pending_load_warning = libcfg.probe_library_read()
        self._roots = libcfg.roots_for_view(self._library)
        self._filter_roots = []
        self._filter_folders = list(_EMPTY_FOLDERS)
        self._awaiting_subcategory = True
        if not self.is_library_scanning():
            self._sync_index()
            if self._model is not None:
                try:
                    self._model.shutdown()
                except Exception:
                    pass
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._open_index()
        self._reload_tree(initial=True)
        self._update_preview_aspect()

    def _update_preview_aspect(self) -> None:
        """왼쪽 열 폭 기준 16:9 높이."""
        if self._left_col is None:
            return
        w = max(320, self._left_col.width() - 8)
        h = max(180, int(w * 9 / 16 * 1.15))
        self._preview.setFixedHeight(h)

    # ── 스캔 소유 (설정 창이 닫혀도 계속) ─────────────────────────────

    def is_library_scanning(self) -> bool:
        w = self._scan_worker
        return bool(self._scan_queue) or (w is not None and w.isRunning())

    def enqueue_library_scan(
        self,
        roots: Optional[List[str]] = None,
        *,
        force: bool = False,
        publish: bool = True,
        missing_only: bool = False,
    ) -> None:
        """스캔·게시 요청. 설정 다이얼로그도 여기로만 보낸다."""
        wanted = [libcfg.normalize_path(r) for r in (roots or []) if r]
        if not wanted:
            wanted = list(libcfg.roots_for_view(self._library) or self._roots)
        if missing_only and not force:
            wanted = publish.roots_missing_from_local(wanted)
        if not wanted and not force:
            return
        if force and not wanted:
            wanted = list((self._library.get("common") or {}).get("roots") or []) or list(
                self._roots
            )
        job = {
            "roots": wanted,
            "force": bool(force),
            "publish": bool(publish),
            "hidden": list(libcfg.hidden_folders(self._library)),
        }
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._merge_scan_job(job)
            self._status_label.setText("스캔·게시 대기열에 추가됨…")
            return
        self._start_scan_job(job)

    def _merge_scan_job(self, job: Dict[str, Any]) -> None:
        if not self._scan_queue:
            self._scan_queue.append(job)
            return
        last = self._scan_queue[-1]
        roots = list(dict.fromkeys(list(last.get("roots") or []) + list(job.get("roots") or [])))
        last["roots"] = roots
        last["force"] = bool(last.get("force")) or bool(job.get("force"))
        last["publish"] = bool(last.get("publish")) or bool(job.get("publish"))
        last["hidden"] = list(job.get("hidden") or last.get("hidden") or [])

    def _start_scan_job(self, job: Dict[str, Any]) -> None:
        roots = list(job.get("roots") or [])
        if not roots:
            return
        limit_mb = int(self._settings.get("thumb_cache_max_mb") or 2048)
        self._scan_publish = bool(job.get("publish", True))
        worker = LibraryScanWorker(
            roots,
            trim_cache_bytes=limit_mb * 1024 * 1024,
            pack_roots=libcfg.pack_roots(self._library),
            hidden_folders=list(job.get("hidden") or []),
            force=bool(job.get("force")),
            parent=self,
        )
        worker.progress.connect(self._on_scan_progress)
        worker.scan_done.connect(self._on_owner_scan_done)
        worker.scan_aborted.connect(self._on_owner_scan_aborted)
        worker.scan_error.connect(self._on_scan_error)
        self._scan_worker = worker
        self._status_label.setText("스캔·게시 중… (원본은 읽기만)")
        self._scan_cancel_btn.setVisible(True)
        worker.start()

    def _on_cancel_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.stop()
        self._scan_queue = []
        self._status_label.setText("스캔 취소 중…")

    def _on_scan_progress(self, where: str, indexed: int) -> None:
        if self._shutdown_done:
            return
        self._status_label.setText("훑는 중… {} (갱신 {:,}개)".format(where, indexed))

    def _publish_after_scan(self, indexed: int) -> None:
        if not self._scan_publish:
            self._status_label.setText("인덱싱 완료 ({:,}개)".format(indexed))
            self._reload_tree(initial=True)
            return
        self._status_label.setText("인덱싱 완료 ({:,}개) — 게시 중…".format(indexed))
        try:
            conn = db.connect()
            try:
                meta = publish.publish_index(conn)
                total = db.total_indexed(conn)
            finally:
                conn.close()
            self._status_label.setText(
                "스캔·게시 완료 — 인덱스 {:,}개 (이번 갱신 {:,}개)".format(
                    int(meta.get("items") or total), indexed
                )
            )
        except Exception as exc:
            logger.warning("게시 실패: %s", exc)
            self._status_label.setText("게시 실패: {}".format(exc))
        self._reload_after_scan()

    def _reload_after_scan(self) -> None:
        if self._shutdown_done:
            return
        if self._model is not None:
            try:
                self._model.shutdown()
            except Exception:
                pass
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._open_index()
        self._reload_tree(initial=True)

    def _drain_scan_queue(self) -> None:
        if self._shutdown_done:
            return
        if not self._scan_queue:
            return
        nxt = self._scan_queue.pop(0)
        self._start_scan_job(nxt)

    def _on_owner_scan_done(self, indexed: int) -> None:
        if self._shutdown_done:
            return
        self._scan_cancel_btn.setVisible(False)
        self._publish_after_scan(indexed)
        self._drain_scan_queue()

    def _on_owner_scan_aborted(self, indexed: int) -> None:
        if self._shutdown_done:
            return
        self._scan_cancel_btn.setVisible(False)
        self._status_label.setText("스캔 중단 ({:,}개까지)".format(indexed))
        self._scan_queue = []

    def _on_scan_error(self, message: str) -> None:
        if self._shutdown_done:
            return
        self._scan_cancel_btn.setVisible(False)
        self._status_label.setText("인덱싱 오류: {}".format(message))
        self._drain_scan_queue()

    # ── 항목 선택 / 동작 ────────────────────────────────────────────

    def _set_path_display(self, path: str) -> None:
        self._path_full = path
        self._path_label.setToolTip(path)
        fm = QFontMetrics(self._path_label.font())
        width = max(80, self._path_label.width() - 8)
        self._path_label.setText(fm.elidedText(path, Qt.TextElideMode.ElideMiddle, width))

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_preview_aspect()
        if self._path_full:
            self._set_path_display(self._path_full)

    def _active_rows(self) -> List[Dict[str, Any]]:
        if self._selected_rows:
            return list(self._selected_rows)
        if self._current_row:
            return [dict(self._current_row)]
        return []

    def _set_action_enabled(self, enabled: bool) -> None:
        self._copy_btn.setEnabled(enabled)
        self._open_btn.setEnabled(enabled)

    def _on_selection_rows(self, rows: object) -> None:
        if isinstance(rows, list):
            self._selected_rows = [dict(r) for r in rows if isinstance(r, dict)]
        else:
            self._selected_rows = []
        n = len(self._selected_rows)
        self._set_action_enabled(n > 0)
        if n > 1:
            self._status_label.setText("{}개 선택".format(n))

    def _on_item_selected(self, row: object) -> None:
        if not isinstance(row, dict):
            return
        self._current_row = dict(row)
        path = normalize_path_str(row_pattern_path(row))
        self._set_path_display(path)
        self._set_action_enabled(True)
        thumb = self._model.pixmap_for_row(row) if self._model is not None else None
        self._preview.set_item(row_dir_path(row), row, thumb=thumb)

    def _on_item_activated(self, row: object) -> None:
        if isinstance(row, dict):
            self._current_row = dict(row)
            self._on_copy_path()

    def _on_copy_path(self) -> None:
        rows = self._active_rows()
        if not rows:
            return
        paths = [normalize_path_str(row_pattern_path(r)) for r in rows]
        text = "\n".join(paths)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._status_label.setText("경로 복사: {}개".format(len(paths)))
        self.path_copied.emit(paths[0])

    def _reveal_path_in_os(self, target: str) -> bool:
        """OS 탐색기에서 파일/폴더를 연다. Windows는 가능하면 해당 항목 선택.

        반환값: 실제로 열렸다고 판단되면 True, 경로가 사라졌거나 실행 실패면 False.
        """
        path = normalize_path_str(target)
        if not path:
            return False
        if sys.platform == "win32":
            # /select, 와 경로를 분리 — 공백 경로에서 list2cmdline 따옴표 깨짐 방지
            if os.path.exists(path):
                try:
                    subprocess.Popen(windows_explorer_select_args(path))
                    return True
                except OSError as exc:
                    logger.debug("explorer /select 실패: %s", exc)
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            folder = normalize_path_str(folder)
            if folder and os.path.isdir(folder):
                return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            return False
        if sys.platform == "darwin":
            if os.path.exists(path):
                try:
                    subprocess.Popen(["open", "-R", path])
                    return True
                except OSError as exc:
                    logger.debug("open -R 실패: %s", exc)
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        folder = normalize_path_str(folder)
        if folder and os.path.isdir(folder):
            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        return False

    def _on_open_folder(self) -> None:
        rows = self._active_rows()
        if not rows:
            return
        target = row_reveal_path(rows[0])
        opened = self._reveal_path_in_os(target)
        shown = normalize_path_str(target)
        if not opened:
            self._status_label.setText(
                "탐색기를 열지 못했습니다 (경로가 사라졌을 수 있음): {}".format(shown)
            )
            return
        if len(rows) > 1:
            self._status_label.setText(
                "탐색기에서 선택: {}개 중 첫 항목 ({})".format(len(rows), shown)
            )
        else:
            self._status_label.setText("탐색기에서 선택: {}".format(shown))

    # ── 정리 ────────────────────────────────────────────────────────

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._search_timer.stop()
        try:
            self._preview.shutdown()
        except Exception as exc:
            logger.debug("프리뷰 정리 실패: %s", exc)
        worker = self._scan_worker
        if worker is not None:
            worker.stop()
            for signal in (
                worker.progress,
                worker.scan_done,
                worker.scan_aborted,
                worker.scan_error,
            ):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            if worker.isRunning():
                worker.wait(5000)
            self._scan_worker = None
        self._scan_queue = []
        sync_worker = self._index_sync_worker
        if sync_worker is not None:
            for signal in (sync_worker.sync_done, sync_worker.sync_error):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            if sync_worker.isRunning():
                sync_worker.wait(1500)
            self._index_sync_worker = None
        if self._model is not None:
            try:
                self._model.shutdown()
            except Exception as exc:
                logger.debug("썸네일 작업 정리 실패: %s", exc)
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def done(self, result: int) -> None:
        self._shutdown()
        super().done(result)

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._shutdown()
        super().closeEvent(event)


def enforce_thumb_cache_limit() -> None:
    """설정된 상한으로 썸네일 캐시를 정리한다."""
    settings = get_source_library_settings()
    limit_mb = int(settings.get("thumb_cache_max_mb") or 2048)
    media_thumbs.enforce_cache_limit(limit_mb * 1024 * 1024)
