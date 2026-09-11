# @cursor-change: 2026-08-10, 0.13.x, DnD 커서·빼기 가드·빈클릭 해제
"""소스 라이브러리 관리자 설정 — 폴더 등록·자유 폴더 트리·스캔·게시.

왼쪽: 등록 루트를 펼쳐 소분류(소스)를 보고 드래그.
오른쪽: CS/MMK/커스텀 폴더에 서버 구조를 보존해 정리.
폴더 드래그: 가운데=안으로, 위·아래 줄=형제 순서.
원본 미디어는 절대 삭제·이동하지 않는다.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QByteArray, QMimeData, Qt
from PySide6.QtGui import QAction, QDrag, QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui import theme
from bpe.gui.widgets.library_tree import LibraryTree

logger = get_logger("gui.widgets.source_library_settings_dialog")

_ROLE_KIND = int(Qt.ItemDataRole.UserRole)
_ROLE_PATH = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_PARENT = int(Qt.ItemDataRole.UserRole) + 2
_ROLE_VIRTUAL = int(Qt.ItemDataRole.UserRole) + 3
_KIND_GROUP = "group"
_KIND_ROOT = "root"
_KIND_CATEGORY = "category"
_KIND_DUMMY = "__dummy__"
_KIND_NESTED = "nested"
_KIND_VIRTUAL = "virtual"
_KIND_VASSIGN = "vassign"
_KIND_UNFILED = "unfiled"
_MIME = "application/x-bpe-library-root"
_MIME_CAT = "application/x-bpe-library-category"
_MIME_VIRTUAL = "application/x-bpe-library-virtual"
_MIME_VASSIGN = "application/x-bpe-library-vassign"
_MIME_GROUP = "application/x-bpe-library-group"
_MIME_NESTED = "application/x-bpe-library-nested"


class _GroupTree(LibraryTree):
    """그룹 트리 — 루트를 그룹으로 드래그해 배정한다."""

    def __init__(self, owner: "SourceLibrarySettingsDialog") -> None:
        super().__init__()
        self._owner = owner
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setViewportMargins(0, 10, 0, 0)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802
        roots = [i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_ROOT]
        cats = [
            i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_CATEGORY
        ]
        virtuals = [
            i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_VIRTUAL
        ]
        vassigns = [
            i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_VASSIGN
        ]
        nesteds = [
            i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_NESTED
        ]
        groups = [
            i for i in self.selectedItems() if str(i.data(0, _ROLE_KIND) or "") == _KIND_GROUP
        ]
        mime = QMimeData()
        if roots:
            paths = [str(i.data(0, _ROLE_PATH) or "") for i in roots]
            paths = [p for p in paths if p]
            if not paths:
                return
            mime.setData(_MIME, QByteArray("\n".join(paths).encode("utf-8")))
            mime.setText("\n".join(paths))
        elif cats:
            paths = [str(i.data(0, _ROLE_PATH) or "") for i in cats]
            paths = [p for p in paths if p]
            if not paths:
                return
            mime.setData(_MIME_CAT, QByteArray("\n".join(paths).encode("utf-8")))
            mime.setText("\n".join(paths))
        elif vassigns and not virtuals and not nesteds and not groups:
            lines: List[str] = []
            labels: List[str] = []
            for it in vassigns:
                abs_p = str(it.data(0, _ROLE_PATH) or "")
                folder_org = str(it.data(0, _ROLE_VIRTUAL) or "")
                if not abs_p or not folder_org:
                    continue
                lines.append("{}|{}".format(folder_org, abs_p))
                labels.append(abs_p.rsplit("/", 1)[-1] or abs_p)
            if not lines:
                return
            mime.setData(_MIME_VASSIGN, QByteArray("\n".join(lines).encode("utf-8")))
            mime.setText("\n".join(labels))
        elif len(groups) == 1 and not virtuals and not nesteds and not vassigns:
            it = groups[0]
            gname = str(it.data(0, _ROLE_PATH) or "")
            if not gname:
                return
            mime.setData(_MIME_GROUP, QByteArray(gname.encode("utf-8")))
            mime.setText(gname)
        elif virtuals and not nesteds and not groups and not vassigns:
            from_paths: List[str] = []
            labels: List[str] = []
            for it in virtuals:
                from_path = str(it.data(0, _ROLE_PATH) or "")
                if not from_path or len(libcfg.parse_org_path(from_path)) < 2:
                    continue
                from_paths.append(from_path)
                labels.append(libcfg.parse_org_path(from_path)[-1])
            if not from_paths:
                return
            mime.setData(_MIME_VIRTUAL, QByteArray("\n".join(from_paths).encode("utf-8")))
            mime.setText("\n".join(labels))
        elif len(nesteds) == 1:
            it = nesteds[0]
            nname = str(it.data(0, _ROLE_PATH) or "")
            parent = str(it.data(0, _ROLE_PARENT) or "")
            if not nname or not parent:
                return
            mime.setData(
                _MIME_NESTED,
                QByteArray("{}|{}".format(parent, nname).encode("utf-8")),
            )
            mime.setText(nname)
        else:
            self._owner.set_status("같은 종류끼리만 함께 드래그할 수 있습니다.")
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        md = event.mimeData()
        if md is not None and (
            md.hasFormat(_MIME)
            or md.hasFormat(_MIME_CAT)
            or md.hasFormat(_MIME_VIRTUAL)
            or md.hasFormat(_MIME_VASSIGN)
            or md.hasFormat(_MIME_GROUP)
            or md.hasFormat(_MIME_NESTED)
            or md.hasUrls()
        ):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802
        md = event.mimeData()
        if md is not None and (
            md.hasFormat(_MIME)
            or md.hasFormat(_MIME_CAT)
            or md.hasFormat(_MIME_VIRTUAL)
            or md.hasFormat(_MIME_VASSIGN)
            or md.hasFormat(_MIME_GROUP)
            or md.hasFormat(_MIME_NESTED)
            or md.hasUrls()
        ):
            # 인디케이터 갱신 후 재-accept — super만 두면 커스텀 MIME가 ignore되어 ○/ 커서
            super().dragMoveEvent(event)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self.itemAt(event.position().toPoint()) is None:
                self.clearSelection()
                self.setCurrentItem(None)
        super().mousePressEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        md = event.mimeData()
        if md is None:
            return
        target = self.itemAt(event.position().toPoint())
        ind = self.dropIndicatorPosition()
        edge = ind in (
            QAbstractItemView.DropIndicatorPosition.AboveItem,
            QAbstractItemView.DropIndicatorPosition.BelowItem,
        )
        after = ind == QAbstractItemView.DropIndicatorPosition.BelowItem
        if md.hasFormat(_MIME_GROUP):
            gname = bytes(md.data(_MIME_GROUP)).decode("utf-8", "replace").strip()
            if gname:
                if edge and target is not None:
                    self._owner.reorder_top_level_drop(gname, target, after=after)
                else:
                    self._owner.drop_top_level_group(gname, target)
            event.acceptProposedAction()
            return
        if md.hasFormat(_MIME_NESTED):
            raw = bytes(md.data(_MIME_NESTED)).decode("utf-8", "replace")
            parts = raw.split("|", 1)
            if len(parts) == 2:
                self._owner.drop_nested_group(parts[0], parts[1], target)
            event.acceptProposedAction()
            return
        if md.hasFormat(_MIME_VIRTUAL):
            raw = bytes(md.data(_MIME_VIRTUAL)).decode("utf-8", "replace").strip()
            from_paths = [p.strip() for p in raw.split("\n") if p.strip()]
            if from_paths:
                if edge and target is not None:
                    self._owner.reorder_virtual_groups_drop(from_paths, target, after=after)
                else:
                    self._owner.drop_virtual_groups(from_paths, target)
            event.acceptProposedAction()
            return
        if md.hasFormat(_MIME_VASSIGN):
            raw = bytes(md.data(_MIME_VASSIGN)).decode("utf-8", "replace").strip()
            pairs: List[Tuple[str, str]] = []
            for line in raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if "|" in line:
                    folder_org, abs_p = line.split("|", 1)
                elif "\t" in line:
                    folder_org, abs_p = line.split("\t", 1)
                else:
                    # 레거시: folder_org\nabs (단일)
                    continue
                folder_org = folder_org.strip()
                abs_p = libcfg.normalize_path(abs_p.strip())
                if folder_org and abs_p:
                    pairs.append((folder_org, abs_p))
            # 레거시 단일 payload: "folder\nabs" (파이프 없음)
            if not pairs and "\n" in raw and "|" not in raw:
                folder_org, abs_p = raw.split("\n", 1)
                folder_org = folder_org.strip()
                abs_p = libcfg.normalize_path(abs_p.strip())
                if folder_org and abs_p:
                    pairs.append((folder_org, abs_p))
            if pairs:
                self._owner.drop_vassigns(pairs, target)
            event.acceptProposedAction()
            return
        if md.hasFormat(_MIME_CAT):
            raw = bytes(md.data(_MIME_CAT)).decode("utf-8", "replace")
            paths = [libcfg.normalize_path(p) for p in raw.split("\n") if p.strip()]
            self._owner.assign_categories_to_virtual_drop(paths, target)
            event.acceptProposedAction()
            return
        if md.hasUrls() and not md.hasFormat(_MIME):
            for url in md.urls():
                local = url.toLocalFile()
                if local:
                    self._owner.add_root_path(local)
            event.acceptProposedAction()
            return
        if not md.hasFormat(_MIME):
            return
        raw = bytes(md.data(_MIME)).decode("utf-8", "replace")
        paths = [libcfg.normalize_path(p) for p in raw.split("\n") if p.strip()]
        group_name = self._owner.resolve_drop_group(target)
        self._owner.assign_roots_to_group(paths, group_name)
        event.acceptProposedAction()


class SourceLibrarySettingsDialog(QDialog):
    """관리자 전용 — 루트 등록·그룹 배정 + 자동 스캔·게시."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        projects: Optional[List[Dict[str, Any]]] = None,
        initial_project_id: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Source Library 설정")
        self.setMinimumSize(1400, 720)
        self._clamp_resize(1680, 900)
        _ = projects
        _ = initial_project_id

        self._library = libcfg.load_library()
        load_warning = libcfg.probe_library_read()
        self._shutdown_done = False
        try:
            self._loaded_at_mtime: Optional[float] = libcfg.config_path().stat().st_mtime
        except OSError:
            self._loaded_at_mtime = None
        self._external_change_detected = False

        self._build_ui()
        self._reload_roots_list()
        self._reload_group_tree()
        if load_warning:
            logger.warning("library.json 읽기 실패: %s", load_warning)
            self._status.setText(
                "설정 파일을 못 읽어 이전 상태로 표시 중일 수 있습니다 ({})".format(load_warning)
            )

    def _clamp_resize(self, w: int, h: int) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            w = min(w, int(geo.width() * 0.92))
            h = min(h, int(geo.height() * 0.92))
        self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        warn = QLabel(
            "원본 파일은 절대 삭제·이동되지 않습니다. "
            "왼쪽 소분류를 오른쪽 폴더(Compositing Source·MMK·직접 만든 폴더)로 드래그하면 "
            "서버 폴더 이름 그대로 하위에 생깁니다. "
            "아무것도 안 골라도 「새 폴더」로 폴더가 생기고, 폴더를 고르면 그 안에 만듭니다. "
            "「Compositing Source」는 삭제만 불가하며, 소스를 바로 넣을 수 있습니다."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_DIM, theme.FONT_SIZE_SMALL)
        )
        root.addWidget(warn)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(self._section_title("등록된 소스 (펼쳐서 소분류 드래그)"))
        self._roots_tree = LibraryTree()
        self._roots_tree.setHeaderHidden(True)
        self._roots_tree.setViewportMargins(0, 10, 0, 0)
        self._roots_tree.setDragEnabled(True)
        self._roots_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._roots_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        left.addWidget(self._roots_tree, 1)
        folder_btns = QHBoxLayout()
        add_btn = QPushButton("폴더 추가")
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(self._on_add_root)
        folder_btns.addWidget(add_btn)
        rem_btn = QPushButton("등록 해제")
        rem_btn.setFixedWidth(100)
        rem_btn.setToolTip("라이브러리 등록만 해제합니다. 원본 파일은 지우지 않습니다.")
        rem_btn.clicked.connect(self._on_remove_root)
        folder_btns.addWidget(rem_btn)
        folder_btns.addStretch()
        left.addLayout(folder_btns)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(self._section_title("폴더 정리 (왼쪽 소스를 폴더로 드래그)"))
        self._group_tree = _GroupTree(self)
        self._group_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._group_tree.customContextMenuRequested.connect(self._on_group_context_menu)
        right.addWidget(self._group_tree, 1)

        grp_btns = QHBoxLayout()
        for text, slot, w in (
            ("새 폴더", self._on_new_group, 88),
            ("이름 변경", self._on_rename_group, 92),
            ("폴더 삭제", self._on_delete_group, 92),
        ):
            b = QPushButton(text)
            b.setFixedWidth(w)
            b.clicked.connect(slot)
            grp_btns.addWidget(b)
        grp_btns.addStretch()
        right.addLayout(grp_btns)
        body.addLayout(right, 2)
        root.addLayout(body, 2)

        self._status = QLabel("")
        self._status.setObjectName("status_msg")
        root.addWidget(self._status)

        bottom = QHBoxLayout()
        scan_btn = QPushButton("전체 스캔")
        scan_btn.setProperty("primary", True)
        scan_btn.setFixedWidth(100)
        scan_btn.setToolTip(
            "등록된 모든 폴더를 강제로 다시 훑어 공유 인덱스를 갱신합니다. "
            "일상 등록은 자동 스캔·게시되므로 폴더 내용이 바뀌었을 때만 쓰면 됩니다. "
            "원본 파일은 읽기만 합니다."
        )
        scan_btn.clicked.connect(self._on_scan_publish)
        bottom.addWidget(scan_btn)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setToolTip(
            "고른 폴더에서 바뀐 부분만 다시 훑어 새 파일을 반영합니다 (약 30초, 원본은 읽기만). "
            "새 클립이 있을 때만 팀 공유 목록을 갱신합니다. "
            "Compositing Source는 「전체 스캔」으로 갱신합니다."
        )
        refresh_btn.clicked.connect(self._on_refresh_request)
        bottom.addWidget(refresh_btn)
        bottom.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._roots_tree.startDrag = self._start_roots_drag  # type: ignore[method-assign]
        self._roots_tree.itemExpanded.connect(self._on_roots_tree_expanded)

    def _start_roots_drag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802
        """왼쪽에서는 소분류만 오른쪽으로 드래그 (루트 통째 배정 UI 제거)."""
        cats = [
            i
            for i in self._roots_tree.selectedItems()
            if str(i.data(0, _ROLE_KIND) or "") == _KIND_CATEGORY
        ]
        paths = [str(i.data(0, _ROLE_PATH) or "") for i in cats]
        paths = [p for p in paths if p]
        if not paths:
            self._status.setText(
                "소분류를 펼친 뒤 항목을 드래그하세요 (경로 통째로는 옮기지 않습니다)."
            )
            return
        mime = QMimeData()
        mime.setData(_MIME_CAT, QByteArray("\n".join(paths).encode("utf-8")))
        mime.setText("\n".join(paths))
        drag = QDrag(self._roots_tree)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def _tree_expand_keys(self, tree: QTreeWidget) -> Set[Tuple[str, str, str]]:
        keys: Set[Tuple[str, str, str]] = set()

        def walk(item: QTreeWidgetItem) -> None:
            if item.isExpanded():
                keys.add(
                    (
                        str(item.data(0, _ROLE_KIND) or ""),
                        str(item.data(0, _ROLE_PATH) or ""),
                        str(item.data(0, _ROLE_PARENT) or ""),
                    )
                )
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top is not None:
                walk(top)
        return keys

    def _restore_tree_expand(self, tree: QTreeWidget, keys: Set[Tuple[str, str, str]]) -> None:
        if not keys:
            return

        def walk(item: QTreeWidgetItem) -> None:
            key = (
                str(item.data(0, _ROLE_KIND) or ""),
                str(item.data(0, _ROLE_PATH) or ""),
                str(item.data(0, _ROLE_PARENT) or ""),
            )
            if key in keys:
                item.setExpanded(True)
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top is not None:
                walk(top)

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: {}; font-size: {}px;".format(theme.TEXT_LABEL, theme.FONT_SIZE_SMALL)
        )
        return lbl

    def resolve_drop_group(self, target: Optional[QTreeWidgetItem]) -> str:
        """드롭 대상에서 최상위 그룹 이름을 찾는다. 없으면 배정 해제."""
        item = target
        while item is not None:
            kind = str(item.data(0, _ROLE_KIND) or "")
            path = str(item.data(0, _ROLE_PATH) or "")
            if kind in (_KIND_GROUP, _KIND_UNFILED):
                return path
            if kind == _KIND_VIRTUAL:
                segs = libcfg.parse_org_path(path)
                return segs[0] if segs else ""
            parent_g = str(item.data(0, _ROLE_PARENT) or "")
            if parent_g:
                segs = libcfg.parse_org_path(parent_g)
                return segs[0] if segs else parent_g
            item = item.parent()
        return ""

    def set_status(self, text: str) -> None:
        """자식 위젯(_GroupTree 등)이 상태줄을 갱신할 때 쓰는 공개 진입점."""
        self._status.setText(text)

    def _check_external_change(self) -> None:
        """이 창을 연 뒤 다른 사람(또는 다른 창)이 library.json 을 먼저 저장했는지 확인.

        완전한 동시편집 잠금은 아니다(버전 체크·락 도입은 이번 범위 밖) — 저장은
        그대로 진행하되, 겹쳤을 수 있다는 걸 알려주는 가벼운 완화책.
        """
        try:
            current_mtime = libcfg.config_path().stat().st_mtime
        except OSError:
            return
        if self._loaded_at_mtime is not None and current_mtime > self._loaded_at_mtime + 1e-6:
            self._external_change_detected = True

    def _persist(self) -> bool:
        self._check_external_change()
        try:
            libcfg.save_library(self._library)
            self._loaded_at_mtime = libcfg.config_path().stat().st_mtime
            if self._external_change_detected:
                self._external_change_detected = False
                self._status.setText("저장됨 (다른 곳에서 그 사이 수정했을 수 있습니다)")
            else:
                self._status.setText("저장됨")
            return True
        except Exception as exc:
            logger.warning("library.json 저장 실패: %s", exc)
            self._status.setText("저장 실패: {}".format(exc))
            return False

    def _persist_silent(self) -> bool:
        """`_persist()`와 동일하지만 상태줄은 안 건드린다 — 호출부가 이미 더 구체적인
        메시지(성공·실패)를 세팅해 둔 경우, 그걸 제네릭 "저장됨"으로 덮어쓰지 않기 위해."""
        self._check_external_change()
        try:
            libcfg.save_library(self._library)
            try:
                self._loaded_at_mtime = libcfg.config_path().stat().st_mtime
            except OSError:
                pass
            return True
        except Exception as exc:
            logger.warning("library.json 저장 실패: %s", exc)
            return False

    def _persist_and_status(
        self, success_text: str, *, reload: Optional[Callable[[], None]] = None
    ) -> bool:
        """저장 → (있으면) 리로드 → 저장이 실제로 성공했을 때만 성공 메시지 표시.

        기존 UX(저장 실패해도 화면은 항상 최신 메모리 상태로 리로드)는 그대로 유지한다
        — `self._library`는 저장 여부와 무관하게 이미 메모리에서 갱신돼 있으므로.
        """
        ok = self._persist_silent()
        externally_changed = self._external_change_detected
        self._external_change_detected = False
        if reload is not None:
            reload()
        if ok:
            if externally_changed:
                self._status.setText(
                    "{} (다른 곳에서 그 사이 수정했을 수 있습니다)".format(success_text)
                )
            else:
                self._status.setText(success_text)
        else:
            self._status.setText("저장 실패 — {} 반영 안 됨".format(success_text))
        return ok

    def _index_count_for_roots(self, roots: List[str]) -> int:
        if not roots:
            return 0
        conn = None
        try:
            conn = db.connect()
            return sum(db.count_for_root(conn, r) for r in roots)
        except Exception as exc:
            logger.debug("배정 루트 인덱스 건수 실패: %s", exc)
            return 0
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _reload_roots_list(self) -> None:
        prev = self._tree_expand_keys(self._roots_tree)
        roots = list((self._library.get("common") or {}).get("roots") or [])
        self._roots_tree.clear()
        for r in roots:
            root_n = libcfg.normalize_path(r)
            item = QTreeWidgetItem([normalize_path_str(root_n)])
            item.setData(0, _ROLE_KIND, _KIND_ROOT)
            item.setData(0, _ROLE_PATH, root_n)
            item.setToolTip(0, normalize_path_str(root_n))
            self._roots_tree.addTopLevelItem(item)
            self._add_category_children(item, root_n)
        self._restore_tree_expand(self._roots_tree, prev)

    def _item_depth(self, item: QTreeWidgetItem) -> int:
        depth = 0
        p = item.parent()
        while p is not None:
            depth += 1
            p = p.parent()
        return depth

    def _add_category_children(self, parent_item: QTreeWidgetItem, abs_path: str) -> None:
        """디스크 하위 폴더를 한 단계 채우고, 더 깊은 하위가 있으면 더미로 펼침 화살표만 표시한다.

        서버 다단계 구조를 지연 로드(lazy-expand)로 보여준다 — 처음부터 전 깊이를
        eager 재귀하면 네트워크 드라이브 폴더 수만큼 왕복이 생겨 창이 느려진다.
        """
        for sub in libcfg.list_disk_subdirs(abs_path):
            abs_sub = "{}/{}".format(abs_path, sub)
            cat_item = QTreeWidgetItem([sub])
            cat_item.setData(0, _ROLE_KIND, _KIND_CATEGORY)
            cat_item.setData(0, _ROLE_PATH, abs_sub)
            cat_item.setData(0, _ROLE_PARENT, abs_path)
            cat_item.setToolTip(0, normalize_path_str(abs_sub))
            parent_item.addChild(cat_item)
            self._maybe_add_dummy_child(cat_item, abs_sub)

    def _maybe_add_dummy_child(self, item: QTreeWidgetItem, abs_path: str) -> None:
        if self._item_depth(item) >= libcfg.MAX_VIRTUAL_DEPTH:
            return
        if not libcfg.has_disk_subdir(abs_path):
            return
        dummy = QTreeWidgetItem(["…"])
        dummy.setData(0, _ROLE_KIND, _KIND_DUMMY)
        item.addChild(dummy)

    def _on_roots_tree_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() != 1:
            return
        child = item.child(0)
        if child is None or str(child.data(0, _ROLE_KIND) or "") != _KIND_DUMMY:
            return
        item.takeChild(0)
        abs_path = str(item.data(0, _ROLE_PATH) or "")
        if abs_path:
            self._add_category_children(item, abs_path)

    def _paint_virtual_folder(
        self, parent_item: QTreeWidgetItem, child: Dict[str, Any], parent_path: str
    ) -> None:
        """virtual 폴더를 재귀로 그린다. PATH = 전체 org 경로."""
        cname = str(child.get("name") or "")
        if not cname:
            return
        full_path = libcfg.join_org_path([parent_path, cname]) if parent_path else cname
        v_item = QTreeWidgetItem(["[폴더] {}".format(cname)])
        v_item.setData(0, _ROLE_KIND, _KIND_VIRTUAL)
        v_item.setData(0, _ROLE_PATH, full_path)
        v_item.setData(0, _ROLE_PARENT, parent_path)
        v_item.setToolTip(0, "폴더 — 왼쪽 소분류를 드래그해 넣으세요")
        parent_item.addChild(v_item)
        for abs_p in child.get("folders") or []:
            abs_n = libcfg.normalize_path(str(abs_p))
            if not abs_n:
                continue
            leaf_name = abs_n.rsplit("/", 1)[-1] or abs_n
            a_item = QTreeWidgetItem([leaf_name])
            a_item.setData(0, _ROLE_KIND, _KIND_VASSIGN)
            a_item.setData(0, _ROLE_PATH, abs_n)
            a_item.setData(0, _ROLE_PARENT, full_path)
            a_item.setData(0, _ROLE_VIRTUAL, full_path)
            a_item.setToolTip(0, normalize_path_str(abs_n))
            v_item.addChild(a_item)
        for sub in child.get("children") or []:
            if not isinstance(sub, dict):
                continue
            if str(sub.get("kind") or "") == libcfg.CHILD_KIND_VIRTUAL:
                self._paint_virtual_folder(v_item, sub, full_path)

    def _reload_group_tree(
        self,
        *,
        select_kind: str = "",
        select_path: str = "",
        select_parent: str = "",
    ) -> None:
        """오른쪽: 보관함·폴더·짧은 소분류명만 (W: 루트 브랜치 없음)."""
        prev = self._tree_expand_keys(self._group_tree)
        self._group_tree.clear()
        groups = libcfg.view_groups(self._library)
        organized_all = libcfg.library_organized_paths(self._library)
        for g in groups:
            gname = str(g.get("name") or "")
            if libcfg.is_builtin_group(gname):
                # 삭제·이름변경 불가(순서 이동만 가능)한 기본 그룹임을 구분 표기
                label = "[기본 폴더] {}".format(gname)
            else:
                label = "[폴더] {}".format(gname)
            g_item = QTreeWidgetItem([label])
            g_item.setData(0, _ROLE_KIND, _KIND_GROUP)
            g_item.setData(0, _ROLE_PATH, gname)
            self._group_tree.addTopLevelItem(g_item)
            # 최상위 직속 bag (레거시·직접 수납)
            for abs_p in g.get("bag") or []:
                abs_n = libcfg.normalize_path(str(abs_p))
                if not abs_n:
                    continue
                leaf_name = abs_n.rsplit("/", 1)[-1] or abs_n
                a_item = QTreeWidgetItem([leaf_name])
                a_item.setData(0, _ROLE_KIND, _KIND_VASSIGN)
                a_item.setData(0, _ROLE_PATH, abs_n)
                a_item.setData(0, _ROLE_PARENT, gname)
                a_item.setData(0, _ROLE_VIRTUAL, gname)
                a_item.setToolTip(0, normalize_path_str(abs_n))
                g_item.addChild(a_item)
            for child in libcfg.group_children(g):
                if not isinstance(child, dict):
                    continue
                kind = str(child.get("kind") or "")
                cname = str(child.get("name") or "")
                if not cname:
                    continue
                if kind == libcfg.CHILD_KIND_VIRTUAL:
                    self._paint_virtual_folder(g_item, child, gname)
                elif kind == libcfg.CHILD_KIND_NESTED or child.get("anchor"):
                    # 호환: nested 1단만 표시 (신규 생성·DnD 없음)
                    nested_org = libcfg.join_org_path([gname, cname])
                    n_item = QTreeWidgetItem(["[폴더] {}".format(cname)])
                    n_item.setData(0, _ROLE_KIND, _KIND_NESTED)
                    n_item.setData(0, _ROLE_PATH, cname)
                    n_item.setData(0, _ROLE_PARENT, gname)
                    tip = normalize_path_str(str(child.get("anchor") or ""))
                    n_item.setToolTip(0, tip or "폴더 (읽기 전용)")
                    g_item.addChild(n_item)
                    for abs_p in child.get("folders") or []:
                        abs_n = libcfg.normalize_path(str(abs_p))
                        if not abs_n:
                            continue
                        leaf_name = abs_n.rsplit("/", 1)[-1] or abs_n
                        a_item = QTreeWidgetItem([leaf_name])
                        a_item.setData(0, _ROLE_KIND, _KIND_VASSIGN)
                        a_item.setData(0, _ROLE_PATH, abs_n)
                        a_item.setData(0, _ROLE_PARENT, nested_org)
                        a_item.setData(0, _ROLE_VIRTUAL, nested_org)
                        a_item.setToolTip(0, normalize_path_str(abs_n))
                        n_item.addChild(a_item)
            # 미정리 — 드롭 대상 + 미배정 소분류 leaf
            u_item = QTreeWidgetItem(["[미정리]"])
            u_item.setData(0, _ROLE_KIND, _KIND_UNFILED)
            u_item.setData(0, _ROLE_PATH, gname)
            u_item.setData(0, _ROLE_PARENT, gname)
            u_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            u_item.setToolTip(0, "폴더에서 뺀 소스가 여기로 옵니다 (왼쪽 등록은 유지)")
            g_item.addChild(u_item)
            # 미배정: 이 그룹이 소유한 루트의 직속 소분류 (organized 제외)
            for root in libcfg.group_roots(g):
                root_n = libcfg.normalize_path(root)
                for name in libcfg.list_disk_subdirs(root_n):
                    abs_cat = libcfg.folder_abs(root_n, name)
                    if abs_cat in organized_all:
                        continue
                    if libcfg.is_hidden_folder(self._library, abs_cat):
                        continue
                    a_item = QTreeWidgetItem([name])
                    a_item.setData(0, _ROLE_KIND, _KIND_VASSIGN)
                    a_item.setData(0, _ROLE_PATH, abs_cat)
                    a_item.setData(0, _ROLE_PARENT, gname)
                    a_item.setData(0, _ROLE_VIRTUAL, gname)
                    a_item.setToolTip(0, normalize_path_str(abs_cat))
                    u_item.addChild(a_item)
            if not prev:
                g_item.setExpanded(True)
        self._restore_tree_expand(self._group_tree, prev)
        if select_kind and select_path:
            self._select_group_tree_item(select_kind, select_path, select_parent)

    def _select_group_tree_item(self, kind: str, path: str, parent: str = "") -> None:
        def walk(item: QTreeWidgetItem) -> bool:
            if (
                str(item.data(0, _ROLE_KIND) or "") == kind
                and str(item.data(0, _ROLE_PATH) or "") == path
                and str(item.data(0, _ROLE_PARENT) or "") == parent
            ):
                self._group_tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None and walk(child):
                    return True
            return False

        for i in range(self._group_tree.topLevelItemCount()):
            top = self._group_tree.topLevelItem(i)
            if top is not None and walk(top):
                return

    def move_virtual_drop(self, from_path: str, target: Optional[QTreeWidgetItem]) -> None:
        self.drop_virtual_group(from_path, target)

    def _drop_target_info(self, target: Optional[QTreeWidgetItem]) -> Dict[str, str]:
        """드롭 대상: kind, parent_group, path, folder_path(org)."""
        item = target
        while item is not None:
            kind = str(item.data(0, _ROLE_KIND) or "")
            path = str(item.data(0, _ROLE_PATH) or "")
            parent = str(item.data(0, _ROLE_PARENT) or "")
            if kind in (_KIND_ROOT, _KIND_CATEGORY):
                return {
                    "kind": kind,
                    "parent_group": parent,
                    "path": path,
                    "folder_path": "",
                }
            if kind == _KIND_GROUP:
                # CS / MMK / org=folder — 모두 드롭 가능한 폴더
                return {
                    "kind": kind,
                    "parent_group": path,
                    "path": path,
                    "folder_path": path,
                }
            if kind == _KIND_UNFILED:
                return {
                    "kind": kind,
                    "parent_group": path,
                    "path": path,
                    "folder_path": "",
                }
            if kind == _KIND_VIRTUAL:
                segs = libcfg.parse_org_path(path)
                top = segs[0] if segs else parent
                return {
                    "kind": kind,
                    "parent_group": top,
                    "path": path,
                    "folder_path": path,
                }
            if kind == _KIND_NESTED:
                return {
                    "kind": kind,
                    "parent_group": parent,
                    "path": path,
                    "folder_path": "",
                }
            if kind == _KIND_VASSIGN:
                virt = str(item.data(0, _ROLE_VIRTUAL) or "")
                segs = libcfg.parse_org_path(virt)
                top = segs[0] if segs else parent
                return {
                    "kind": kind,
                    "parent_group": top,
                    "path": path,
                    "folder_path": virt,
                }
            item = item.parent()
        return {}

    def drop_top_level_group(self, group_name: str, target: Optional[QTreeWidgetItem]) -> None:
        if libcfg.is_builtin_group(group_name):
            # CS는 순서 이동만 허용 — 다른 그룹/폴더 "안으로" 넣는 건 항상 거부된다.
            # 예전엔 여기서 promote_top_level_to_virtual()이 실패하며 "루트를 먼저
            # 빼세요"라는 오해 유발 메시지가 떴는데, 그 안내를 따라가면 실제로 CS의
            # 등록 루트가 삭제되는 사고로 이어질 수 있었다.
            # 상황별 안내: 빈 영역/자기 자신 드롭까지 "안으로 넣기 거부"로 말하면
            # 엉뚱한 안내가 된다 — 실제 시도였을 때만 거부 사유를 보여준다.
            info = self._drop_target_info(target)
            tgt_group = str(info.get("parent_group") or "") if info else ""
            if target is None:
                self._status.setText("보관함 또는 폴더 위에 놓으세요.")
            elif not tgt_group or tgt_group == group_name:
                pass  # 자기 자신/자기 하위로의 드롭 — 의미 없는 조작이라 무음
            else:
                self._status.setText(
                    "「{}」는 다른 그룹 안으로 넣을 수 없습니다 (순서 이동만 가능합니다).".format(
                        libcfg.COMMON_LABEL
                    )
                )
            return
        info = self._drop_target_info(target)
        kind = info.get("kind") or ""
        parent = info.get("parent_group") or ""
        folder_path = info.get("folder_path") or ""
        if kind in (_KIND_ROOT, _KIND_CATEGORY):
            self._status.setText("디스크 경로 안으로는 넣지 않습니다. 폴더·보관함 위에 놓으세요.")
            return
        if kind in (_KIND_VIRTUAL, _KIND_VASSIGN) and folder_path:
            top = libcfg.parse_org_path(folder_path)
            top_name = top[0] if top else parent
            if not top_name or top_name == group_name:
                return
            if not libcfg.promote_top_level_to_virtual(self._library, group_name, top_name):
                self._status.setText(
                    "「{}」을(를) 「{}」 아래로 옮기지 못했습니다 "
                    "(루트가 들어 있으면 루트를 먼저 빼세요).".format(group_name, top_name)
                )
                return
            new_path = libcfg.join_org_path([top_name, group_name])
            if folder_path != top_name and new_path != folder_path:
                if not libcfg.move_folder(self._library, new_path, folder_path):
                    self._status.setText("폴더 안으로 옮기지 못했습니다.")
                    self._persist()
                    self._reload_group_tree(
                        select_kind=_KIND_VIRTUAL,
                        select_path=new_path,
                        select_parent=top_name,
                    )
                    return
                new_path = libcfg.join_org_path([folder_path, group_name])
            parent_of_new = libcfg.join_org_path(libcfg.parse_org_path(new_path)[:-1])
            self._persist_and_status(
                "「{}」 → 「{}」 안".format(group_name, folder_path),
                reload=lambda: self._reload_group_tree(
                    select_kind=_KIND_VIRTUAL,
                    select_path=new_path,
                    select_parent=parent_of_new,
                ),
            )
            return
        if kind in (_KIND_GROUP, _KIND_UNFILED) and parent:
            if parent == group_name:
                return
            if not libcfg.promote_top_level_to_virtual(self._library, group_name, parent):
                self._status.setText(
                    "「{}」을(를) 「{}」 아래로 옮기지 못했습니다 "
                    "(루트가 들어 있으면 루트를 먼저 빼세요).".format(group_name, parent)
                )
                return
            new_path = libcfg.join_org_path([parent, group_name])
            self._persist_and_status(
                "「{}」 → 「{}」 하위 폴더".format(group_name, parent),
                reload=lambda: self._reload_group_tree(
                    select_kind=_KIND_VIRTUAL,
                    select_path=new_path,
                    select_parent=parent,
                ),
            )
            return
        self._status.setText("보관함 또는 폴더 위에 놓으세요.")

    def drop_nested_group(
        self, from_parent: str, child_name: str, target: Optional[QTreeWidgetItem]
    ) -> None:
        _ = from_parent
        _ = child_name
        _ = target
        self._status.setText("예전 중첩 폴더는 옮길 수 없습니다 (삭제만 가능).")

    def reorder_virtual_groups_drop(
        self, from_paths: List[str], target: QTreeWidgetItem, *, after: bool
    ) -> None:
        """위·아래 인디케이터(다중) — 같은 부모 형제 순서만 변경. target 은 한 번만 읽는다."""
        paths = [p.strip() for p in from_paths if (p or "").strip()]
        if not paths:
            return
        tkind = str(target.data(0, _ROLE_KIND) or "")
        tpath = str(target.data(0, _ROLE_PATH) or "")
        if tkind == _KIND_VASSIGN:
            parent = target.parent()
            if parent is None:
                return
            tkind = str(parent.data(0, _ROLE_KIND) or "")
            tpath = str(parent.data(0, _ROLE_PATH) or "")
        if tkind != _KIND_VIRTUAL or not tpath:
            # 그룹 줄 가장자리 → 안으로 넣기와 동일
            self.drop_virtual_groups(paths, target)
            return
        n = 0
        for from_path in paths:
            if from_path == tpath:
                continue
            if libcfg.reorder_folder_sibling(self._library, from_path, tpath, after=after):
                n += 1
        if n <= 0:
            self._status.setText("같은 안의 폴더끼리만 순서를 바꿀 수 있습니다.")
            return
        parent_of = libcfg.join_org_path(libcfg.parse_org_path(tpath)[:-1])
        self._persist_and_status(
            "{}개 폴더 순서 변경".format(n),
            reload=lambda: self._reload_group_tree(
                select_kind=_KIND_VIRTUAL,
                select_path=paths[-1],
                select_parent=parent_of,
            ),
        )

    def reorder_top_level_drop(
        self, group_name: str, target: QTreeWidgetItem, *, after: bool
    ) -> None:
        tkind = str(target.data(0, _ROLE_KIND) or "")
        tpath = str(target.data(0, _ROLE_PATH) or "")
        if tkind != _KIND_GROUP or not tpath:
            self.drop_top_level_group(group_name, target)
            return
        if tpath == group_name:
            return  # 자기 자신 위/아래로의 드롭 — 무동작인데 "실패"로 보이지 않게 무음
        if not libcfg.reorder_top_level_group(self._library, group_name, tpath, after=after):
            self._status.setText("최상위 폴더 순서를 바꾸지 못했습니다 (대상을 찾을 수 없음).")
            return
        self._persist_and_status(
            "폴더 순서 변경: 「{}」".format(group_name),
            reload=lambda: self._reload_group_tree(select_kind=_KIND_GROUP, select_path=group_name),
        )

    def drop_virtual_group(self, from_path: str, target: Optional[QTreeWidgetItem]) -> None:
        from_path = (from_path or "").strip()
        if not from_path or len(libcfg.parse_org_path(from_path)) < 2:
            return
        if not target:
            self._status.setText("빈 곳으로는 옮기지 않습니다")
            return
        info = self._drop_target_info(target)
        kind = info.get("kind") or ""
        folder_path = info.get("folder_path") or ""
        parent = info.get("parent_group") or ""
        leaf = libcfg.parse_org_path(from_path)[-1]
        if kind in (_KIND_VIRTUAL, _KIND_VASSIGN) and folder_path:
            to_parent = folder_path
            # self / 자기 자손만 차단 (조상 virtual로 빼기는 허용 — core move_folder와 동일)
            if to_parent == from_path or to_parent.startswith(from_path + "/"):
                return
            if not libcfg.move_folder(self._library, from_path, to_parent):
                self._status.setText("폴더를 옮기지 못했습니다.")
                return
            new_path = libcfg.join_org_path([to_parent, leaf])
            self._persist_and_status(
                "「{}」 → 「{}」".format(leaf, to_parent),
                reload=lambda: self._reload_group_tree(
                    select_kind=_KIND_VIRTUAL,
                    select_path=new_path,
                    select_parent=to_parent,
                ),
            )
            return
        if kind in (_KIND_GROUP, _KIND_UNFILED) and parent:
            if not libcfg.move_folder(self._library, from_path, parent):
                self._status.setText("폴더를 옮기지 못했습니다.")
                return
            new_path = libcfg.join_org_path([parent, leaf])
            self._persist_and_status(
                "「{}」 → 「{}」".format(leaf, parent),
                reload=lambda: self._reload_group_tree(
                    select_kind=_KIND_VIRTUAL,
                    select_path=new_path,
                    select_parent=parent,
                ),
            )
            return
        self._status.setText("폴더는 다른 폴더·보관함 위에 놓으세요.")

    def drop_virtual_groups(self, from_paths: List[str], target: Optional[QTreeWidgetItem]) -> None:
        """오른쪽 폴더(다중)를 다른 폴더로 옮긴다 — drop_vassigns 와 동일 패턴.

        target 은 트리 리로드 전에 한 번만 읽는다(리로드 후 QTreeWidgetItem 은
        무효화되므로 루프 중 재조회하면 안 됨).
        """
        paths = [p.strip() for p in from_paths if (p or "").strip()]
        if not paths:
            return
        if not target:
            self._status.setText("빈 곳으로는 옮기지 않습니다")
            return
        info = self._drop_target_info(target)
        kind = info.get("kind") or ""
        folder_path = info.get("folder_path") or ""
        parent = info.get("parent_group") or ""
        to_parent = folder_path if (kind in (_KIND_VIRTUAL, _KIND_VASSIGN) and folder_path) else ""
        if not to_parent and kind in (_KIND_GROUP, _KIND_UNFILED) and parent:
            to_parent = parent
        if not to_parent:
            self._status.setText("폴더는 다른 폴더·보관함 위에 놓으세요.")
            return
        n = 0
        last_leaf = ""
        for from_path in paths:
            if len(libcfg.parse_org_path(from_path)) < 2:
                continue
            # self / 자기 자손만 차단 (조상 virtual로 빼기는 허용 — core move_folder와 동일)
            if to_parent == from_path or to_parent.startswith(from_path + "/"):
                continue
            if libcfg.move_folder(self._library, from_path, to_parent):
                n += 1
                last_leaf = libcfg.parse_org_path(from_path)[-1]
        if n <= 0:
            self._status.setText("폴더를 옮기지 못했습니다.")
            return
        self._persist_and_status(
            "{}개 폴더 → 「{}」".format(n, to_parent),
            reload=lambda: self._reload_group_tree(
                select_kind=_KIND_VIRTUAL,
                select_path=libcfg.join_org_path([to_parent, last_leaf]) if last_leaf else "",
                select_parent=to_parent,
            ),
        )

    def drop_vassigns(
        self, pairs: List[Tuple[str, str]], target: Optional[QTreeWidgetItem]
    ) -> None:
        """오른쪽 소분류(다중)를 다른 폴더로 옮기거나 [미정리]로 뺀다."""
        if not pairs:
            return
        info = self._drop_target_info(target)
        kind = info.get("kind") or ""
        folder_path = info.get("folder_path") or ""
        n = 0
        last_cat = ""
        if kind == _KIND_UNFILED:
            for from_folder, cat in pairs:
                from_folder = (from_folder or "").strip()
                cat = libcfg.normalize_path(cat)
                if not from_folder or not cat:
                    continue
                if libcfg.remove_source_from_folder(self._library, from_folder, cat):
                    n += 1
                    last_cat = cat
            if n <= 0:
                self._status.setText("미정리로 빼지 못했습니다.")
                return
            self._persist_and_status(
                "{}개 → 미정리 (원본은 그대로)".format(n),
                reload=lambda: self._reload_group_tree(),
            )
            return
        if kind in (_KIND_VIRTUAL, _KIND_VASSIGN, _KIND_GROUP) and folder_path:
            for from_folder, cat in pairs:
                from_folder = (from_folder or "").strip()
                cat = libcfg.normalize_path(cat)
                if not from_folder or not cat or folder_path == from_folder:
                    continue
                # 대상이 폴더면 동명 하위 폴더로 정리 (탐색기형)
                if libcfg.organize_into_folder(self._library, folder_path, cat):
                    n += 1
                    last_cat = cat
            if n <= 0:
                self._status.setText("소스를 옮기지 못했습니다.")
                return
            short = last_cat.rsplit("/", 1)[-1] if last_cat else ""
            self._persist_and_status(
                "{}개 → 「{}」".format(n, folder_path)
                + (" (예: {})".format(short) if short else ""),
                reload=lambda: self._reload_group_tree(),
            )
            return
        self._status.setText("폴더(Compositing Source·MMK·직접 만든 폴더) 위에 놓으세요.")

    def drop_vassign(
        self, from_folder: str, category_abs: str, target: Optional[QTreeWidgetItem]
    ) -> None:
        self.drop_vassigns([(from_folder, category_abs)], target)

    def assign_categories_to_virtual_drop(
        self, paths: List[str], target: Optional[QTreeWidgetItem]
    ) -> None:
        """왼쪽 소분류를 오른쪽 폴더로 드롭 — 동명 하위 폴더로 구조 보존."""
        info = self._drop_target_info(target)
        kind = info.get("kind") or ""
        folder_path = info.get("folder_path") or ""
        if kind == _KIND_NESTED:
            self._status.setText("폴더(Compositing Source·MMK·직접 만든 폴더) 위에 놓으세요.")
            return
        if kind == _KIND_GROUP and folder_path:
            pass
        elif kind not in (_KIND_VIRTUAL, _KIND_VASSIGN) or not folder_path:
            self._status.setText("폴더(Compositing Source·MMK·직접 만든 폴더) 위에 놓으세요.")
            return
        n = 0
        for p in paths:
            if libcfg.organize_into_folder(self._library, folder_path, p):
                n += 1
        if n <= 0:
            self._status.setText("이미 들어 있거나 넣을 수 없습니다.")
            return
        leaf = libcfg.parse_org_path(folder_path)[-1]
        self._persist_and_status(
            "{}개 → 폴더 「{}」 (서버 구조 유지, 원본 그대로)".format(n, leaf),
            reload=lambda: self._reload_group_tree(),
        )

    def add_root_path(self, path: str) -> None:
        root = libcfg.normalize_path(normalize_path_str(path))
        if not root:
            return
        common = self._library.get("common") or {}
        roots = list(common.get("roots") or [])
        if root in roots:
            self._status.setText("이미 등록된 폴더입니다.")
            return
        roots.append(root)
        groups = list(common.get("groups") or [])
        if not any(libcfg.group_roots(g) for g in groups if isinstance(g, dict)):
            libcfg.set_scope(self._library, libcfg.COMMON_SCOPE, roots, groups)
            libcfg.assign_roots_to_group(self._library, [root], libcfg.COMMON_LABEL)
        else:
            libcfg.set_scope(self._library, libcfg.COMMON_SCOPE, roots, groups)

        def _reload_roots_and_groups() -> None:
            self._reload_roots_list()
            self._reload_group_tree()

        self._persist_and_status(
            "등록: {} (원본은 그대로입니다)".format(root), reload=_reload_roots_and_groups
        )
        self._queue_auto_scan([root])

    def _on_add_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "라이브러리 폴더 선택")
        if chosen:
            self.add_root_path(chosen)

    def _on_remove_root(self) -> None:
        item = self._roots_tree.currentItem()
        if item is None:
            return
        target = str(item.data(0, _ROLE_PATH) or "")
        if not target:
            return
        confirm = QMessageBox.question(
            self,
            "등록 해제",
            "{}\n\n라이브러리 등록만 해제합니다.\n원본 파일은 절대 삭제·이동되지 않습니다.".format(
                normalize_path_str(target)
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        common = self._library.get("common") or {}
        roots = [r for r in (common.get("roots") or []) if r != target]
        groups: List[Dict[str, Any]] = []
        for g in common.get("groups") or []:
            if not isinstance(g, dict):
                continue
            folders = [
                libcfg.normalize_path(str(f))
                for f in (g.get("folders") or [])
                if libcfg.normalize_path(str(f)) != target
            ]
            # 해당 루트 아래 anchor 중첩 그룹도 제거
            children = []
            for c in g.get("children") or []:
                if not isinstance(c, dict):
                    continue
                anchor = libcfg.normalize_path(str(c.get("anchor") or ""))
                if anchor == target or anchor.startswith(target + "/"):
                    continue
                children.append(c)
            groups.append({"name": g.get("name"), "folders": folders, "children": children})
        libcfg.set_scope(self._library, libcfg.COMMON_SCOPE, roots, groups)

        def _drop_index_and_reload() -> None:
            try:
                conn = db.connect()
                try:
                    db.drop_root(conn, target)
                finally:
                    conn.close()
            except Exception as exc:
                logger.debug("인덱스 루트 제거 실패(무시): %s", exc)
            self._reload_roots_list()
            self._reload_group_tree()

        self._persist_and_status("등록 해제: {}".format(target), reload=_drop_index_and_reload)

    def assign_roots_to_group(self, paths: List[str], group_name: str) -> None:
        assigned = libcfg.assign_roots_to_group(self._library, paths, group_name)
        if assigned <= 0 and paths:
            logger.warning(
                "설정 배정 실패(no-op): paths=%s group=%r",
                paths,
                group_name,
            )
            self._status.setText(
                "배정 실패: 등록된 루트가 아니거나 대상이 없습니다. "
                "왼쪽 목록의 경로만 그룹으로 끌어다 놓으세요."
            )
            self._reload_group_tree()
            return
        saved = self._persist()
        self._reload_group_tree()
        if not saved:
            return
        path_set = {libcfg.normalize_path(p) for p in paths if p}
        assigned_paths: List[str] = []
        if group_name:
            for g in (self._library.get("common") or {}).get("groups") or []:
                if isinstance(g, dict) and str(g.get("name") or "") == group_name:
                    assigned_paths = [
                        libcfg.normalize_path(str(f))
                        for f in (g.get("folders") or [])
                        if libcfg.normalize_path(str(f)) in path_set
                    ]
                    break
        else:
            assigned_paths = list(path_set)
        idx_n = self._index_count_for_roots(assigned_paths)
        if group_name:
            if idx_n <= 0:
                self._status.setText(
                    "{}개 → 그룹 「{}」 — 팀에 공개. 인덱스 없어 스캔·게시를 시작합니다.".format(
                        assigned, group_name
                    )
                )
                if assigned_paths:
                    self._queue_auto_scan(assigned_paths)
            else:
                self._status.setText(
                    "{}개 → 그룹 「{}」(인덱스 {:,}개) — 팀에 보입니다.".format(
                        assigned, group_name, idx_n
                    )
                )
        else:
            self._status.setText("{}개 그룹 배정 해제".format(assigned))

    def _on_group_context_menu(self, pos: Any) -> None:
        item = self._group_tree.itemAt(pos)
        if item is None:
            return
        kind = str(item.data(0, _ROLE_KIND) or "")
        path = str(item.data(0, _ROLE_PATH) or "")
        if kind == _KIND_VASSIGN:
            folder_org = str(item.data(0, _ROLE_VIRTUAL) or "")
            if not folder_org or not path:
                return
            menu = QMenu(self)
            act = QAction("폴더에서 빼기", self)
            act.triggered.connect(lambda: self._remove_vassign(folder_org, path))
            menu.addAction(act)
            menu.exec(self._group_tree.viewport().mapToGlobal(pos))
            return
        if kind in (_KIND_GROUP, _KIND_VIRTUAL):
            if not path:
                return
            prev_path = self._reorder_neighbor_path(item, kind, up=True)
            next_path = self._reorder_neighbor_path(item, kind, up=False)
            menu = QMenu(self)
            up_act = QAction("위로 이동", menu)
            down_act = QAction("아래로 이동", menu)
            up_act.setEnabled(bool(prev_path))
            down_act.setEnabled(bool(next_path))
            up_act.triggered.connect(
                lambda checked=False, b=prev_path: self._reorder_sibling_by_menu(
                    kind, path, b, after=False
                )
            )
            down_act.triggered.connect(
                lambda checked=False, b=next_path: self._reorder_sibling_by_menu(
                    kind, path, b, after=True
                )
            )
            menu.addAction(up_act)
            menu.addAction(down_act)
            menu.exec(self._group_tree.viewport().mapToGlobal(pos))
            return
        if kind != _KIND_CATEGORY:
            return
        if not path:
            return
        hidden = libcfg.is_hidden_folder(self._library, path)
        menu = QMenu(self)
        act = QAction("숨기기 해제" if hidden else "목록에서 숨기기", self)
        act.triggered.connect(lambda: self._toggle_hidden_folder(path, not hidden))
        menu.addAction(act)
        menu.exec(self._group_tree.viewport().mapToGlobal(pos))

    def _reorder_neighbor_path(self, item: QTreeWidgetItem, kind: str, *, up: bool) -> str:
        """같은 종류(kind) 형제 중 바로 위/아래 항목의 경로. 없으면 빈 문자열.

        트리에는 VASSIGN(절대경로)·NESTED(짧은 이름)·UNFILED(그룹명)가 섞여 있어
        인덱스 ±1을 그대로 쓰면 안 되고, 같은 kind 만 스킵-스캔으로 찾는다.
        """
        step = -1 if up else 1
        parent = item.parent()
        if parent is None:
            idx = self._group_tree.indexOfTopLevelItem(item)
            j = idx + step
            while 0 <= j < self._group_tree.topLevelItemCount():
                cand = self._group_tree.topLevelItem(j)
                ckind = str(cand.data(0, _ROLE_KIND) or "")
                cpath = str(cand.data(0, _ROLE_PATH) or "")
                if ckind == kind and cpath:
                    return cpath
                j += step
            return ""
        idx = parent.indexOfChild(item)
        j = idx + step
        while 0 <= j < parent.childCount():
            cand = parent.child(j)
            ckind = str(cand.data(0, _ROLE_KIND) or "")
            cpath = str(cand.data(0, _ROLE_PATH) or "")
            if ckind == kind and cpath:
                return cpath
            j += step
        return ""

    def _reorder_sibling_by_menu(
        self, kind: str, path: str, neighbor_path: str, *, after: bool
    ) -> None:
        """컨텍스트 메뉴 「위로/아래로 이동」 — 드래그 재정렬과 같은 core 함수 사용."""
        if not neighbor_path or neighbor_path == path:
            return
        if kind == _KIND_GROUP:
            if not libcfg.reorder_top_level_group(self._library, path, neighbor_path, after=after):
                self._status.setText("최상위 폴더 순서를 바꾸지 못했습니다 (대상을 찾을 수 없음).")
                return
            self._persist_and_status(
                "폴더 순서 변경: 「{}」".format(path),
                reload=lambda: self._reload_group_tree(select_kind=_KIND_GROUP, select_path=path),
            )
            return
        if not libcfg.reorder_folder_sibling(self._library, path, neighbor_path, after=after):
            self._status.setText("같은 안의 폴더끼리만 순서를 바꿀 수 있습니다.")
            return
        parent_of = libcfg.join_org_path(libcfg.parse_org_path(path)[:-1])
        self._persist_and_status(
            "폴더 순서 변경",
            reload=lambda: self._reload_group_tree(
                select_kind=_KIND_VIRTUAL,
                select_path=path,
                select_parent=parent_of,
            ),
        )

    def _remove_vassign(self, folder_org_path: str, category_abs: str) -> None:
        if libcfg.remove_source_from_folder(self._library, folder_org_path, category_abs):
            short = libcfg.parse_org_path(folder_org_path)
            label = short[-1] if short else folder_org_path
            self._persist_and_status(
                "「{}」에서 뺌".format(label), reload=lambda: self._reload_group_tree()
            )

    def _toggle_hidden_folder(self, path: str, hide: bool) -> None:
        if not libcfg.set_folder_hidden(self._library, path, hide):
            return
        if not self._persist():
            return
        self._reload_group_tree()
        shown = normalize_path_str(path)
        parent_roots = [
            libcfg.normalize_path(r)
            for r in ((self._library.get("common") or {}).get("roots") or [])
            if path.startswith(libcfg.normalize_path(str(r)) + "/")
            or path == libcfg.normalize_path(str(r))
        ]
        if hide:
            self._status.setText(
                "숨김: {} — 메인 목록에서 제외. 공유 인덱스 정리 중…".format(shown)
            )
            if parent_roots:
                self._start_auto_scan(parent_roots)
        else:
            self._status.setText("숨김 해제: {} — 다시 스캔·게시합니다…".format(shown))
            if parent_roots:
                self._start_auto_scan(parent_roots)

    def _owner_scan(self) -> Optional[Any]:
        p = self.parent()
        if p is not None and hasattr(p, "enqueue_library_scan"):
            return p
        return None

    def _queue_auto_scan(self, roots: List[str]) -> None:
        """인덱스 없는 루트만 백그라운드 스캔 후 게시 (소유자는 메인 라이브러리)."""
        owner = self._owner_scan()
        if owner is None:
            self._status.setText("스캔 소유자를 찾을 수 없습니다.")
            return
        owner.enqueue_library_scan(roots, force=False, publish=True, missing_only=True)
        self._status.setText("백그라운드 스캔·게시 요청됨 (창을 닫아도 계속됩니다)")

    def _start_auto_scan(self, roots: List[str]) -> None:
        owner = self._owner_scan()
        if owner is None:
            return
        owner.enqueue_library_scan(roots, force=False, publish=True, missing_only=False)
        self._status.setText("백그라운드 스캔·게시 요청됨 (창을 닫아도 계속됩니다)")

    def _on_scan_publish(self) -> None:
        owner = self._owner_scan()
        if owner is None:
            self._status.setText("스캔 소유자를 찾을 수 없습니다.")
            return
        roots = list((self._library.get("common") or {}).get("roots") or [])
        if not roots:
            self._status.setText("등록된 폴더가 없습니다.")
            return
        owner.enqueue_library_scan(roots, force=True, publish=True, missing_only=False)
        self._status.setText("전체 스캔 요청됨 (창을 닫아도 계속됩니다)")

    def apply_auto_organize(self, pairs: List[Tuple[str, str]]) -> Tuple[List[str], List[str]]:
        """새로고침이 추가한 최상위 폴더를 옆 폴더와 같은 분류에 넣고 저장한다.

        메인 라이브러리가 이 창이 열려 있는 동안 부른다 — 이 창의 사본에 적용해야
        닫을 때 옛 사본으로 덮어쓰지 않는다. 반환 ``(넣은 abs, 못 넣은 abs)``.
        """
        from bpe.core import source_library_refresh as refresh

        targets = refresh.auto_organize_targets(self._library, pairs)
        done, failed = refresh.apply_auto_organize(self._library, targets)
        if done:
            self._persist_and_status(
                "새로고침: 분류에 넣음 {}개".format(len(done)),
                reload=lambda: self._reload_group_tree(),
            )
        return done, failed

    def _on_refresh_request(self) -> None:
        """고른 폴더만 바뀐 부분 새로고침 — 실제 진행은 메인 라이브러리(스캔 소유자)."""
        owner = self._owner_scan()
        if owner is None or not hasattr(owner, "request_library_refresh"):
            self._status.setText("스캔 소유자를 찾을 수 없습니다.")
            return
        choices = libcfg.refresh_root_choices(self._library)
        if not any(selectable for _root, selectable in choices):
            self._status.setText(
                "새로고침할 폴더가 없습니다 (Compositing Source는 「전체 스캔」으로 갱신)."
            )
            return
        from bpe.gui.widgets.library_refresh_roots_dialog import LibraryRefreshRootsDialog

        picker = LibraryRefreshRootsDialog(self, choices)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        roots = picker.selected_roots()
        if not roots:
            return
        self._status.setText(str(owner.request_library_refresh(roots)))

    def _shutdown(self) -> None:
        """설정만 닫음 — 스캔 워커는 메인 라이브러리가 소유하므로 stop 하지 않음."""
        if self._shutdown_done:
            return
        self._shutdown_done = True

    def done(self, result: int) -> None:
        self._shutdown()
        super().done(result)

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._shutdown()
        super().closeEvent(event)

    def _selection_context(self) -> Dict[str, str]:
        """선택 컨텍스트: kind, path(전체 org/abs), parent, folder_path."""
        item = self._group_tree.currentItem()
        if item is None:
            return {}
        kind = str(item.data(0, _ROLE_KIND) or "")
        path = str(item.data(0, _ROLE_PATH) or "")
        parent = str(item.data(0, _ROLE_PARENT) or "")
        virt = str(item.data(0, _ROLE_VIRTUAL) or "")
        if kind == _KIND_GROUP:
            return {"kind": kind, "path": path, "parent": "", "folder_path": ""}
        if kind == _KIND_VIRTUAL:
            return {"kind": kind, "path": path, "parent": parent, "folder_path": path}
        if kind == _KIND_VASSIGN:
            return {
                "kind": kind,
                "path": path,
                "parent": parent,
                "folder_path": virt or parent,
            }
        if kind == _KIND_UNFILED:
            return {"kind": kind, "path": path, "parent": parent, "folder_path": ""}
        if kind == _KIND_NESTED:
            return {"kind": kind, "path": path, "parent": parent, "folder_path": ""}
        return {"kind": kind, "path": path, "parent": parent, "folder_path": virt}

    def _on_new_group(self) -> None:
        """새 폴더 — 선택 없음=최상위, 폴더/보관함 선택=그 안(또는 형제)."""
        ctx = self._selection_context()
        kind = ctx.get("kind") or ""
        path = ctx.get("path") or ""
        parent = ctx.get("parent") or ""
        folder_path = ctx.get("folder_path") or ""

        parent_path = ""
        if not kind:
            parent_path = ""
        elif kind == _KIND_GROUP:
            parent_path = path
        elif kind == _KIND_UNFILED:
            parent_path = path
        elif kind == _KIND_VIRTUAL:
            parent_path = path
        elif kind == _KIND_VASSIGN:
            parent_path = folder_path or parent
        elif kind == _KIND_NESTED:
            parent_path = parent
        else:
            parent_path = ""

        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름 (예: 주필산)")
        if not ok:
            return
        name = (name or "").strip()
        if not name or libcfg.is_builtin_group(name) or name == libcfg.OTHER_GROUP:
            QMessageBox.information(self, "새 폴더", "사용할 수 없는 이름입니다.")
            return

        if not parent_path:
            if not libcfg.add_top_level_folder(self._library, name):
                logger.warning("최상위 폴더 생성 실패: name=%s", name)
                self._status.setText("폴더를 만들지 못했습니다 (이미 같은 이름이 있습니다).")
                return
            self._persist_and_status(
                "폴더 「{}」 — 왼쪽 소분류를 드래그해 넣으세요".format(name),
                reload=lambda: self._reload_group_tree(select_kind=_KIND_GROUP, select_path=name),
            )
            return

        if not libcfg.add_folder_under(self._library, parent_path, name):
            logger.warning("폴더 생성 실패: parent=%s name=%s", parent_path, name)
            self._status.setText(
                "폴더를 만들지 못했습니다 (이미 같은 이름이 있거나, 최대 깊이(8단계)를 넘었습니다)."
            )
            return
        new_path = libcfg.join_org_path([parent_path, name])
        self._persist_and_status(
            "폴더 「{}」 → 「{}」 — 왼쪽 소분류를 드래그해 넣으세요".format(name, parent_path),
            reload=lambda: self._reload_group_tree(
                select_kind=_KIND_VIRTUAL,
                select_path=new_path,
                select_parent=parent_path,
            ),
        )

    def _on_rename_group(self) -> None:
        ctx = self._selection_context()
        kind = ctx.get("kind") or ""
        if kind == _KIND_NESTED:
            self._status.setText("예전 중첩 폴더는 이름을 바꿀 수 없습니다.")
            return
        if kind == _KIND_VIRTUAL:
            full_path = ctx.get("path") or ""
            segs = libcfg.parse_org_path(full_path)
            if len(segs) < 2:
                return
            old = segs[-1]
            name, ok = QInputDialog.getText(self, "폴더 이름 변경", "새 이름", text=old)
            if not ok:
                return
            name = (name or "").strip()
            if not name or libcfg.is_builtin_group(name) or name == libcfg.OTHER_GROUP:
                return
            if not libcfg.rename_folder_at(self._library, full_path, name):
                self._status.setText("이름 변경 실패 (이미 같은 이름이 있을 수 있습니다).")
                return
            new_path = libcfg.join_org_path(segs[:-1] + [name])
            parent_path = libcfg.join_org_path(segs[:-1])
            self._persist_and_status(
                "이름 변경: {} → {}".format(old, name),
                reload=lambda: self._reload_group_tree(
                    select_kind=_KIND_VIRTUAL,
                    select_path=new_path,
                    select_parent=parent_path,
                ),
            )
            return

        old = ""
        if kind == _KIND_GROUP:
            old = ctx.get("path") or ""
        if not old:
            self._status.setText("폴더 또는 보관함을 선택하세요.")
            return
        if libcfg.is_builtin_group(old):
            self._status.setText("「{}」는 이름을 바꿀 수 없습니다.".format(libcfg.COMMON_LABEL))
            return
        name, ok = QInputDialog.getText(self, "이름 변경", "새 이름", text=old)
        if not ok:
            return
        name = (name or "").strip()
        if not name or name == libcfg.OTHER_GROUP or libcfg.is_builtin_group(name):
            return
        common = self._library.get("common") or {}
        groups: List[Dict[str, Any]] = []
        for g in common.get("groups") or []:
            if not isinstance(g, dict):
                continue
            if str(g.get("name") or "") == old:
                ng = dict(g)
                ng["name"] = name
                groups.append(ng)
            else:
                groups.append(dict(g))
        libcfg.set_scope(
            self._library, libcfg.COMMON_SCOPE, list(common.get("roots") or []), groups
        )
        self._persist_and_status(
            "이름 변경: {} → {}".format(old, name),
            reload=lambda: self._reload_group_tree(select_kind=_KIND_GROUP, select_path=name),
        )

    def _on_delete_group(self) -> None:
        ctx = self._selection_context()
        kind = ctx.get("kind") or ""
        if kind == _KIND_VIRTUAL:
            full_path = ctx.get("path") or ""
            segs = libcfg.parse_org_path(full_path)
            if len(segs) < 2:
                return
            confirm = QMessageBox.question(
                self,
                "폴더 삭제",
                "「{}」 폴더를 삭제할까요?\n\n"
                "하위 폴더와 배정된 소스가 모두 함께 삭제됩니다 (되돌릴 수 없음).\n"
                "원본 파일은 삭제·이동되지 않습니다.".format(segs[-1]),
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            if not libcfg.delete_folder_at(self._library, full_path):
                self._status.setText("폴더를 삭제하지 못했습니다.")
                return
            self._persist_and_status(
                "폴더 삭제: {}".format(segs[-1]), reload=lambda: self._reload_group_tree()
            )
            return
        if kind == _KIND_NESTED:
            parent = ctx.get("parent") or ""
            name = ctx.get("path") or ""
            if not parent or not name:
                return
            confirm = QMessageBox.question(
                self,
                "폴더 삭제",
                "「{}」 폴더를 삭제할까요? (되돌릴 수 없음)\n"
                "원본 파일은 삭제·이동되지 않습니다.".format(name),
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            common = self._library.get("common") or {}
            groups_out: List[Dict[str, Any]] = []
            for g in common.get("groups") or []:
                if not isinstance(g, dict):
                    continue
                children = list(g.get("children") or [])
                if str(g.get("name") or "") == parent:
                    children = [
                        c
                        for c in children
                        if isinstance(c, dict) and str(c.get("name") or "") != name
                    ]
                ng = dict(g)
                ng["children"] = children
                groups_out.append(ng)
            libcfg.set_scope(
                self._library, libcfg.COMMON_SCOPE, list(common.get("roots") or []), groups_out
            )
            self._persist_and_status(
                "폴더 삭제: {}".format(name), reload=lambda: self._reload_group_tree()
            )
            return

        name = ctx.get("path") if kind == _KIND_GROUP else ""
        if not name:
            self._status.setText("폴더 또는 보관함을 선택하세요.")
            return
        if libcfg.is_builtin_group(name):
            self._status.setText("「{}」는 삭제할 수 없습니다.".format(libcfg.COMMON_LABEL))
            return
        confirm = QMessageBox.question(
            self,
            "보관함 삭제",
            "「{}」 보관함을 삭제할까요?\n\n"
            "안의 폴더·배정된 소스가 모두 함께 삭제됩니다 (되돌릴 수 없음).\n"
            "등록 경로 자체는 왼쪽에 그대로 남습니다.".format(name),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        common = self._library.get("common") or {}
        groups = [
            dict(g)
            for g in (common.get("groups") or [])
            if isinstance(g, dict) and str(g.get("name") or "") != name
        ]
        libcfg.set_scope(
            self._library, libcfg.COMMON_SCOPE, list(common.get("roots") or []), groups
        )
        self._persist_and_status(
            "삭제 (등록 경로는 왼쪽에 남음): {}".format(name),
            reload=lambda: self._reload_group_tree(),
        )
