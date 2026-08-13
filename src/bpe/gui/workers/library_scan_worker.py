# @cursor-change: 2026-08-11, 0.13.x, 팩 소비 image/ 고아 인덱스 prune
"""소스 라이브러리 인덱싱 워커 — 폴더를 조금씩 걸어가며 SQLite 인덱스를 갱신한다.

* 기본: 파일/시퀀스 단위 인덱싱.
* ``pack_roots`` 에 포함된 루트만 JPG+thumb.mov+image/ 팩을 한 카드로 묶는다 (CS 전용).
* 팩이 ``image/`` 를 소비하면 그 하위는 BFS·alive 에 넣지 않아 옛 per-file 행이 prune 된다.
* ``force=True`` 이면 mtime 이 같아도 디렉터리를 다시 인덱싱한다.
* ``hidden_folders`` 에 해당하는 소분류(및 하위)는 건너뛴다.
* ``stop()`` 후 종료 시 ``scan_done`` 대신 ``scan_aborted`` 를 낸다 (부분 게시 방지).
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence, Set

from PySide6.QtCore import QObject, QThread, Signal

from bpe.core import media_thumbs
from bpe.core import source_library_db as db
from bpe.core.logging import get_logger
from bpe.core.source_library_scan import (
    dir_mtime,
    group_entries,
    join_path,
    pack_freshness_mtime,
    read_dir,
    relative_dir,
    try_build_pack,
)

logger = get_logger("gui.workers.library_scan_worker")

_COMMIT_EVERY_DIRS = 25
_PROGRESS_EVERY_DIRS = 25
"""이미 최신이라 재인덱싱이 없는 폴더도 이 개수마다 진행 신호를 낸다 —
재스캔처럼 변경분이 적을 때 진행 표시가 오래 멈춘 것처럼 보이지 않게."""
_YIELD_MS = 4


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
    ) -> None:
        super().__init__(parent)
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
                mtime = dir_mtime(current)

            if self._force or db.dir_needs_index(conn, root_n, dir_rel, mtime):
                if pack_item is not None:
                    items = [pack_item]
                else:
                    items = group_entries(files)
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
            db.prune_dirs(conn, root_n, alive_dirs)
        return indexed_items
