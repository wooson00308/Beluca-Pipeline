"""소스 라이브러리 「새로고침」 미리보기 — 훑은 결과를 인덱스에 쓰지 않고 모아 두고,
관리자가 고른 폴더만 나중에 적용한다.

* :class:`RefreshPreview` — 스캔 워커가 채우고(스레드 안), 창이 읽는다(GUI). 안에는
  값(tuple·LibraryItem)만 담고 sqlite 객체는 담지 않는다.
* 「분류 안 됨」 판정과 자동 분류 대상 찾기는 ``library.json`` 구조만 보는 순수 함수.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any, Dict, Iterable, List, NamedTuple, Sequence, Set, Tuple

from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core.logging import get_logger
from bpe.core.source_library_scan import LibraryItem, category_of

logger = get_logger("core.source_library_refresh")

GROUP_NEW = "new"
GROUP_EXISTING = "existing"
GROUP_UNORGANIZED = "unorganized"

GroupKey = Tuple[str, str]  # (root, category)


class DirChange(NamedTuple):
    root: str
    dir_rel: str
    mtime: float
    items: Tuple[LibraryItem, ...]
    added: int
    removed: int
    changed: int


class GoneDir(NamedTuple):
    root: str
    dir_rel: str
    removed: int


class RefreshGroup(NamedTuple):
    """리뷰 창 한 줄 — 등록 루트 바로 아래 폴더(category) 하나."""

    root: str
    category: str
    kind: str  # GROUP_NEW / GROUP_EXISTING / GROUP_UNORGANIZED
    added: int
    removed: int
    changed: int
    clips: int  # new/unorganized 일 때 클립 수

    @property
    def key(self) -> GroupKey:
        return (self.root, self.category)


def item_content(item: LibraryItem) -> Tuple[Any, ...]:
    """DB ``ITEM_CONTENT_COLUMNS`` 와 같은 순서·타입의 내용 tuple."""
    return (
        str(item.name),
        str(item.ext),
        str(item.kind),
        str(item.seq_pattern),
        int(item.size_bytes),
        float(item.mtime),
        int(item.frame_first),
        int(item.frame_last),
        int(item.frame_count),
    )


def _identity(content: Tuple[Any, ...]) -> Tuple[str, str]:
    # (kind, seq_pattern): 단일 파일은 파일명, 시퀀스는 패턴 — 프레임이 늘어도 같은 항목
    return (str(content[2]), str(content[3]))


class RefreshPreview:
    """훑은 결과를 모아 두는 상자. 워커가 채우고 GUI 가 읽는다."""

    def __init__(self) -> None:
        self._before_dirs: Dict[str, Dict[str, int]] = {}
        self._before_cats: Dict[str, Dict[str, int]] = {}
        self.changes: List[DirChange] = []
        self.gone: List[GoneDir] = []
        self.unorganized: List[RefreshGroup] = []

    # ── 워커 쪽 ─────────────────────────────────────────────────────

    def begin_root(self, conn: sqlite3.Connection, root: str) -> None:
        root_n = db.normalize_root(root)
        counts = db.item_counts_by_dir(conn, root_n)
        self._before_dirs[root_n] = counts
        cats: Dict[str, int] = {}
        for dir_rel, n in counts.items():
            cat = category_of(dir_rel)
            cats[cat] = cats.get(cat, 0) + int(n)
        self._before_cats[root_n] = cats

    def record_dir(
        self,
        conn: sqlite3.Connection,
        root: str,
        dir_rel: str,
        items: Sequence[LibraryItem],
        mtime: float,
    ) -> int:
        """폴더 하나의 새 목록을 옛 목록과 비교해 달라졌으면 기록한다. 반환: 새 항목 수.

        내용이 완전히 같으면(폴더 시각만 바뀐 경우) 아무것도 기록하지 않는다.
        """
        root_n = db.normalize_root(root)
        old = sorted(db.dir_item_contents(conn, root_n, dir_rel))
        new = sorted(item_content(it) for it in items)
        if old == new:
            return 0
        old_by = {_identity(c): c for c in old}
        new_by = {_identity(c): c for c in new}
        added = sum(1 for k in new_by if k not in old_by)
        removed = sum(1 for k in old_by if k not in new_by)
        changed = sum(1 for k in new_by if k in old_by and old_by[k] != new_by[k])
        if added == removed == changed == 0:
            changed = 1  # 같은 이름이 겹치는 특수 케이스 — 어쨌든 달라졌다
        self.changes.append(
            DirChange(root_n, dir_rel, float(mtime), tuple(items), added, removed, changed)
        )
        return len(items)

    def finish_root(self, root: str, gone_dir_rels: Iterable[str]) -> None:
        root_n = db.normalize_root(root)
        before = self._before_dirs.get(root_n, {})
        for dir_rel in gone_dir_rels:
            n = int(before.get(dir_rel, 0))
            if n > 0:
                self.gone.append(GoneDir(root_n, dir_rel, n))

    # ── GUI 쪽 ──────────────────────────────────────────────────────

    def add_unorganized(self, root: str, category: str, count: int) -> None:
        self.unorganized.append(
            RefreshGroup(db.normalize_root(root), category, GROUP_UNORGANIZED, 0, 0, 0, int(count))
        )

    def is_empty(self) -> bool:
        return not self.changes and not self.gone and not self.unorganized

    def groups(self) -> List[RefreshGroup]:
        """리뷰 창 줄 목록 — 새 폴더, 기존 폴더 변경, 분류 안 됨 순서, 이름순."""
        agg: Dict[GroupKey, Dict[str, int]] = {}

        def bucket(root: str, cat: str) -> Dict[str, int]:
            return agg.setdefault((root, cat), {"added": 0, "removed": 0, "changed": 0, "count": 0})

        for ch in self.changes:
            b = bucket(ch.root, category_of(ch.dir_rel))
            b["added"] += ch.added
            b["removed"] += ch.removed
            b["changed"] += ch.changed
            b["count"] += len(ch.items)
        for g in self.gone:
            b = bucket(g.root, category_of(g.dir_rel))
            b["removed"] += g.removed
        out: List[RefreshGroup] = []
        for (root, cat), b in agg.items():
            before = int(self._before_cats.get(root, {}).get(cat, 0))
            kind = GROUP_NEW if before == 0 else GROUP_EXISTING
            out.append(
                RefreshGroup(root, cat, kind, b["added"], b["removed"], b["changed"], b["count"])
            )
        order = {GROUP_NEW: 0, GROUP_EXISTING: 1, GROUP_UNORGANIZED: 2}
        listed = {g.key for g in out}
        out.extend(u for u in self.unorganized if u.key not in listed)
        out.sort(key=lambda g: (order.get(g.kind, 9), g.category.casefold(), g.root))
        return out

    def apply(self, conn: sqlite3.Connection, selected: Set[GroupKey]) -> int:
        """고른 (root, category) 의 변경만 인덱스에 쓴다. 한 트랜잭션. 반환: 쓴 항목 수."""
        written = 0
        try:
            for ch in self.changes:
                if (ch.root, category_of(ch.dir_rel)) in selected:
                    written += db.replace_dir_items(
                        conn, ch.root, ch.dir_rel, list(ch.items), ch.mtime
                    )
            for g in self.gone:
                if (g.root, category_of(g.dir_rel)) in selected:
                    db.delete_dir(conn, g.root, g.dir_rel)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return written


# ── 분류 (library.json) ──────────────────────────────────────────────


def unorganized_categories(
    library: Dict[str, Any], folder_counts: Sequence[Tuple[str, str, int]]
) -> List[Tuple[str, str, int]]:
    """인덱스엔 있는데 트리에 안 보이는 최상위 폴더 ``(root, category, count)``.

    조건: 루트를 소유한 그룹이 없고(그래야 평탄 표시가 안 됨), 어느 폴더에도 정리돼
    있지 않고, 숨김이 아니고, 항목이 1개 이상.
    """
    common = libcfg.get_scope(library, libcfg.COMMON_SCOPE)
    owned = {libcfg.normalize_path(p) for p in libcfg.assigned_folders(common)}
    organized = libcfg.library_organized_paths(library)
    out: List[Tuple[str, str, int]] = []
    for root, category, n in folder_counts:
        root_n = libcfg.normalize_path(str(root))
        cat = str(category or "")
        if not cat or int(n) <= 0 or root_n in owned:
            continue
        abs_p = libcfg.folder_abs(root_n, cat)
        if abs_p in organized or libcfg.is_hidden_folder(library, abs_p):
            continue
        out.append((root_n, cat, int(n)))
    return out


def root_needs_organize(library: Dict[str, Any], root: str) -> bool:
    """루트를 소유한 그룹이 없으면 True — 그 루트의 최상위 폴더는 분류에 넣어야 트리에 보인다."""
    common = libcfg.get_scope(library, libcfg.COMMON_SCOPE)
    owned = {libcfg.normalize_path(p) for p in libcfg.assigned_folders(common)}
    return libcfg.normalize_path(root) not in owned


def auto_organize_targets(
    library: Dict[str, Any], pairs: Sequence[GroupKey]
) -> List[Tuple[str, str]]:
    """새 최상위 폴더를 넣을 분류 경로를 옆 폴더들에서 찾는다 ``(category_abs, org_path)``.

    같은 루트의 다른 최상위 폴더가 들어 있는 가상 폴더의 **부모** 경로(옆 폴더가 놓인
    자리)에 표를 주고 가장 많은 쪽을 고른다. 못 찾으면 ``""``. 이미 어딘가에 정리된
    폴더는 결과에서 뺀다(옮기면 빈 폴더가 남는다).
    """
    organized = libcfg.library_organized_paths(library)
    groups = libcfg.view_groups(library)
    out: List[Tuple[str, str]] = []
    for root, category in pairs:
        root_n = libcfg.normalize_path(root)
        cat = str(category or "")
        if not root_n or not cat:
            continue
        abs_p = libcfg.folder_abs(root_n, cat)
        if abs_p in organized:
            continue
        votes: Counter = Counter()

        def visit(node: Dict[str, Any], path: List[str]) -> None:
            folders = [
                libcfg.normalize_path(str(f))
                for f in (node.get("folders") or [])
                if isinstance(f, str)
            ]
            hits = 0
            for f in folders:
                split = libcfg.split_folder_to_root_dir_rel(f, [root_n])
                if split is None or not split[1]:
                    continue
                if split[1].split("/", 1)[0] != cat:
                    hits += 1
            if hits and len(path) > 1:
                # 옆 폴더가 자기 이름의 가상 폴더에 하나씩 들어 있으면 그 부모가 자리,
                # 한 가상 폴더에 여러 개가 평탄하게 들어 있으면 그 폴더 자체가 자리.
                target = path if len(folders) > 1 else path[:-1]
                votes[libcfg.join_org_path(target)] += hits
            for c in libcfg.virtual_children(node):
                visit(c, path + [str(c.get("name") or "")])

        for g in groups:
            visit(g, [str(g.get("name") or "")])
        best = votes.most_common(1)[0][0] if votes else ""
        out.append((abs_p, best))
    return out


def apply_auto_organize(
    library: Dict[str, Any], targets: Sequence[Tuple[str, str]]
) -> Tuple[List[str], List[str]]:
    """``auto_organize_targets`` 결과를 library 에 적용. 반환 ``(넣은 abs, 못 넣은 abs)``."""
    done: List[str] = []
    failed: List[str] = []
    for abs_p, org_path in targets:
        ok = False
        if org_path:
            try:
                ok = libcfg.organize_into_folder(library, org_path, abs_p)
            except Exception as exc:
                logger.warning("자동 분류 실패 (%s → %s): %s", abs_p, org_path, exc)
        (done if ok else failed).append(abs_p)
    return done, failed


def leaf_name(abs_path: str) -> str:
    return libcfg.normalize_path(abs_path).rsplit("/", 1)[-1]
