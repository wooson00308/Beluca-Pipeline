# @cursor-change: 2026-08-11, 0.13.x, 팩 소비 image/ 고아 인덱스 prune
"""소스 라이브러리 인덱싱 워커 — 폴더를 조금씩 걸어가며 SQLite 인덱스를 갱신한다.

* 기본: 파일/시퀀스 단위 인덱싱.
* ``pack_roots`` 에 포함된 루트만 JPG+thumb.mov+image/ 팩을 한 카드로 묶는다 (CS 전용).
* 팩이 ``image/`` 를 소비하면 그 하위는 BFS·alive 에 넣지 않아 옛 per-file 행이 prune 된다.
* ``force=True`` 이면 mtime 이 같아도 디렉터리를 다시 인덱싱한다.
* ``hidden_folders`` 에 해당하는 소분류(및 하위)는 건너뛴다.
* ``stop()`` 후 종료 시 ``scan_done`` 대신 ``scan_aborted`` 를 낸다 (부분 게시 방지).
* ``strict=True`` (설정 「새로고침」 전용, 팩 루트 제외): 폴더를 못 읽으면 "빈 폴더"로
  적지 않고 예전 인덱스(자신·하위)를 그대로 두며 ``read_failures`` 를 센다.
  기본(``strict=False``) 동작은 그대로다.
* ``preview=True`` (strict 와 함께, 팩 루트는 아예 건너뜀): 인덱스에 쓰지 않고 달라진
  폴더만 ``preview_result`` 에 모은다 — 관리자가 고른 것만 나중에 적용한다.
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence, Set

from PySide6.QtCore import QObject, QThread, Signal

from bpe.core import media_thumbs
from bpe.core import source_library_db as db
from bpe.core.logging import get_logger
from bpe.core.source_library_refresh import RefreshPreview
from bpe.core.source_library_scan import (
    STILL_SEQUENCE_CATEGORIES,
    category_of,
    dir_mtime,
    group_entries,
    join_path,
    pack_freshness_mtime,
    read_dir,
    read_dir_checked,
    relative_dir,
    try_build_pack,
)

logger = get_logger("gui.workers.library_scan_worker")

_COMMIT_EVERY_DIRS = 25
_PROGRESS_EVERY_DIRS = 25
"""이미 최신이라 재인덱싱이 없는 폴더도 이 개수마다 진행 신호를 낸다 —
재스캔처럼 변경분이 적을 때 진행 표시가 오래 멈춘 것처럼 보이지 않게."""
_YIELD_MS = 4


def _known_subtree(known: Sequence[str], dir_rel: str) -> List[str]:
    """인덱스에 기록된 폴더 중 ``dir_rel`` 자신과 그 하위 (루트 ``""`` 면 전부)."""
    if not dir_rel:
        return list(known)
    prefix = dir_rel + "/"
    return [d for d in known if d == dir_rel or d.startswith(prefix)]


class LibraryScanWorker(QThread):
    """등록된 루트들을 훑어 인덱스를 갱신한다."""

    progress = Signal(str, int)
    scan_done = Signal(int)
    scan_aborted = Signal(int)
    scan_error = Signal(str)

    def __init__(
        self,
        roots: Sequence[str],
        trim_cache_bytes: int = 0,
        pack_roots: Optional[Sequence[str]] = None,
        hidden_folders: Optional[Sequence[str]] = None,
        force: bool = False,
        parent: Optional[QObject] = None,
        strict: bool = False,
        preview: bool = False,
    ) -> None:
        super().__init__(parent)
        self._strict = bool(strict)
        self._preview = bool(preview) and self._strict
        self.read_failures = 0
        """strict 모드에서 읽지 못한 폴더 수 (scan_done 이후 읽는다)."""
        self.preview_result: Optional[RefreshPreview] = RefreshPreview() if self._preview else None
        """preview 모드의 결과 상자 (scan_done 이후 GUI 가 읽는다)."""
        self._roots: List[str] = [str(r) for r in roots if str(r).strip()]
        self._trim_cache_bytes = int(trim_cache_bytes)
        self._pack_roots: Set[str] = {
            str(r).replace("\\", "/").rstrip("/") for r in (pack_roots or []) if str(r).strip()
        }
        self._force = bool(force)
        self._hidden: Set[str] = {
            str(h).replace("\\", "/").rstrip("/") for h in (hidden_folders or []) if str(h).strip()
        }
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _is_hidden_path(self, abs_path: str) -> bool:
        path = str(abs_path or "").replace("\\", "/").rstrip("/")
        if not path:
            return False
        for hidden in self._hidden:
            if path == hidden or path.startswith(hidden + "/"):
                return True
        return False

    def _root_uses_pack(self, root_n: str) -> bool:
        return root_n in self._pack_roots

    def run(self) -> None:  # noqa: D102
        if not self._roots:
            self.scan_done.emit(0)
            return
        conn = None
        try:
            if self._trim_cache_bytes > 0:
                media_thumbs.enforce_cache_limit(self._trim_cache_bytes)
            conn = db.connect()
            total_items = 0
            for root in self._roots:
                if self._stop:
                    break
                total_items += self._scan_root(conn, root)
            conn.commit()
            if self._stop:
                self.scan_aborted.emit(total_items)
            else:
                self.scan_done.emit(total_items)
        except Exception as exc:
            logger.warning("라이브러리 인덱싱 실패: %s", exc)
            self.scan_error.emit(str(exc))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _scan_root(self, conn: sqlite3.Connection, root: str) -> int:
        root_n = str(root).replace("\\", "/").rstrip("/")
        use_pack = self._root_uses_pack(root_n)
        strict = self._strict and not use_pack
        preview = self.preview_result if (self._preview and strict) else None
        if self._preview and use_pack:
            logger.warning("새로고침 미리보기는 팩 루트를 건너뜀 — %s", root_n)
            return 0
        known: List[str] = db.known_dirs(conn, root_n) if strict else []
        if preview is not None:
            preview.begin_root(conn, root_n)
        pre_mtime = 0.0
        pending_dirs: List[str] = [root_n]
        alive_dirs: List[str] = []
        indexed_items = 0
        since_commit = 0
        since_progress = 0

        while pending_dirs:
            if self._stop:
                break
            current = pending_dirs.pop(0)
            if self._is_hidden_path(current) and current != root_n:
                continue
            dir_rel = relative_dir(root_n, current)
            alive_dirs.append(dir_rel)
            since_progress += 1

            if strict:
                # mtime 을 목록보다 먼저 — 읽는 도중 들어온 파일은 다음 새로고침 때 잡힌다.
                pre_mtime = dir_mtime(current)
                subdirs, files, ok = read_dir_checked(current)
                if not ok or pre_mtime == 0.0:
                    # 못 읽은 폴더를 "비었다"로 적으면 하위까지 prune 된다 — 예전 인덱스 유지.
                    self.read_failures += 1
                    alive_dirs.extend(_known_subtree(known, dir_rel))
                    logger.warning("새로고침: 폴더를 읽지 못해 이전 목록 유지 — %s", current)
                    continue
            else:
                subdirs, files = read_dir(current)
            consumed_subs: Set[str] = set()
            pack_item = None
            if use_pack:
                built = try_build_pack(current, subdirs, files)
                if built is not None:
                    pack_item, consumed = built
                    consumed_subs = {str(s) for s in consumed}

            for s in subdirs:
                if s in consumed_subs:
                    continue
                child = join_path(current, s)
                if self._is_hidden_path(child):
                    continue
                pending_dirs.append(child)

            if pack_item is not None and consumed_subs:
                # consumed image/ 는 alive 에 넣지 않는다 — 옛 per-file 인덱스가 prune 되도록.
                # 팩 카드의 seq_pattern 은 parent dir_rel 기준이라 image/ DB 행이 필요 없다.
                mtime = pack_freshness_mtime(current, next(iter(consumed_subs)))
            else:
                mtime = pre_mtime if strict else dir_mtime(current)

            if self._force or db.dir_needs_index(conn, root_n, dir_rel, mtime):
                if pack_item is not None:
                    items = [pack_item]
                else:
                    # 3D·ball_pass 카테고리에서만 PNG/TGA 연번을 시퀀스로 묶는다 (opt-in).
                    allow_still = category_of(dir_rel).casefold() in STILL_SEQUENCE_CATEGORIES
                    items = group_entries(files, allow_still_sequences=allow_still)
                if preview is not None:
                    indexed_items += preview.record_dir(conn, root_n, dir_rel, items, mtime)
                else:
                    indexed_items += db.replace_dir_items(conn, root_n, dir_rel, items, mtime)
                    since_commit += 1
                    if since_commit >= _COMMIT_EVERY_DIRS:
                        conn.commit()
                        since_commit = 0

            if since_progress >= _PROGRESS_EVERY_DIRS:
                since_progress = 0
                # 재인덱싱이 없어도(이미 최신) 훑고 있다는 신호는 계속 보낸다.
                self.progress.emit(dir_rel or root_n, indexed_items)
                self.msleep(_YIELD_MS)

        conn.commit()
        if not self._stop:
            if preview is not None:
                # 사라진 폴더는 지우지 않고 기록만 — 숨긴 폴더는 일부러 안 훑은 것.
                alive = set(alive_dirs)
                gone = [
                    d
                    for d in known
                    if d not in alive and not self._is_hidden_path(join_path(root_n, d))
                ]
                preview.finish_root(root_n, gone)
            else:
                db.prune_dirs(conn, root_n, alive_dirs)
        return indexed_items
