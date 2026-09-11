"""소스 라이브러리 설정 「새로고침」 흐름 — 창을 띄우지 않고 메서드 단위로 검증.

실제 공유 서버(W:)는 절대 건드리지 않는다: 공유 메타·게시·설정 읽기는 전부 가짜로
바꾸고, 로컬 인덱스는 ``tmp_app_dir`` 임시 폴더만 쓴다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 라이브러리 창은 영상 미리보기(QtMultimedia)를 쓴다 — 오디오 라이브러리(libpulse)가
# 없는 CI(Ubuntu)에서는 import 자체가 실패하므로 이 파일을 건너뛴다 (Windows·macOS 는 실행).
pytest.importorskip("PySide6.QtMultimedia", reason="QtMultimedia 를 불러올 수 없는 환경")

import bpe.gui.widgets.source_library_dialog as sdlg  # noqa: E402
from bpe.core import source_library_config as libcfg
from bpe.core import source_library_db as db
from bpe.core import source_library_publish as publish
from bpe.core.source_library_scan import FileEntry, group_entries

SourceLibraryDialog = sdlg.SourceLibraryDialog

_CLIPS = "W:/proj/clips"
_ELEMENT = "W:/library/element"


class _Label:
    def __init__(self) -> None:
        self.texts: List[str] = []

    def setText(self, text: str) -> None:  # noqa: N802
        self.texts.append(str(text))

    def text(self) -> str:
        return self.texts[-1] if self.texts else ""

    def repaint(self) -> None:
        pass


class _Signal:
    def connect(self, _slot: Any) -> None:
        pass


class _FakeWorker:
    """LibraryScanWorker 대역 — 생성 인자만 기록한다."""

    created: List["_FakeWorker"] = []

    def __init__(self, roots, **kwargs) -> None:
        self.roots = list(roots)
        self.kwargs = kwargs
        self.read_failures = 0
        self.preview_result: Any = None
        self.progress = _Signal()
        self.scan_done = _Signal()
        self.scan_aborted = _Signal()
        self.scan_error = _Signal()
        self._running = False
        _FakeWorker.created.append(self)

    def start(self) -> None:
        self._running = True

    def isRunning(self) -> bool:  # noqa: N802
        return self._running


class _Stub:
    """SourceLibraryDialog 의 새로고침 관련 메서드만 빌려 쓰는 가짜 창."""

    request_library_refresh = SourceLibraryDialog.request_library_refresh
    _continue_refresh_after_sync = SourceLibraryDialog._continue_refresh_after_sync
    _refresh_snapshot_safe = SourceLibraryDialog._refresh_snapshot_safe
    _prepare_refresh_baseline = SourceLibraryDialog._prepare_refresh_baseline
    _finish_refresh = SourceLibraryDialog._finish_refresh
    _publish_after_scan = SourceLibraryDialog._publish_after_scan
    _start_scan_job = SourceLibraryDialog._start_scan_job
    _on_index_sync_done = SourceLibraryDialog._on_index_sync_done
    _on_index_sync_error = SourceLibraryDialog._on_index_sync_error
    is_library_scanning = SourceLibraryDialog.is_library_scanning
    is_closed = SourceLibraryDialog.is_closed
    _organize_suffix = staticmethod(SourceLibraryDialog._organize_suffix)
    _refresh_hold_text = staticmethod(SourceLibraryDialog._refresh_hold_text)
    _apply_refresh = staticmethod(SourceLibraryDialog._apply_refresh)
    _auto_organize = SourceLibraryDialog._auto_organize
    enqueue_library_scan = SourceLibraryDialog.enqueue_library_scan
    _merge_scan_job = SourceLibraryDialog._merge_scan_job

    def __init__(self, conn=None) -> None:
        self._shutdown_done = False
        self._refresh_reviewing = False
        self._settings_dlg: Optional[Any] = None
        self.review_calls: List[Any] = []
        self.review_answer: Any = "all"  # "all" | None(취소) | set(keys)
        self._roots: List[str] = [_CLIPS]
        self._scan_worker: Optional[Any] = None
        self._scan_queue: List[Dict[str, Any]] = []
        self._scan_publish = True
        self._index_sync_worker: Optional[Any] = None
        self._refresh_pending = False
        self._scan_is_refresh = False
        self._scan_refresh_roots: List[str] = []
        self._refresh_baseline: Optional[Dict[str, Any]] = None
        self._refresh_shared_at = ""
        self._conn = conn
        self._library = _library()
        self._settings = {"thumb_cache_max_mb": 1}
        self._status_label = _Label()
        self._scan_cancel_btn = type("B", (), {"setVisible": lambda self, v: None})()
        self.sync_started = 0
        self.reload_refresh = 0
        self.reload_scan = 0
        self._sender: Optional[Any] = None

    # 창 쪽 동작은 기록만
    def sender(self) -> Optional[Any]:
        return self._sender

    def _start_index_sync(self) -> None:
        self.sync_started += 1

    def _reload_after_refresh(self) -> None:
        self.reload_refresh += 1

    def _reload_after_scan(self) -> None:
        self.reload_scan += 1

    def _warn_empty_group_index(self) -> None:
        pass

    def _review_refresh(self, groups, failures):
        self.review_calls.append((list(groups), int(failures)))
        if self.review_answer == "all":
            return {g.key for g in groups}
        return self.review_answer

    def _on_scan_progress(self, *_a: Any) -> None:
        pass

    def _on_owner_scan_done(self, *_a: Any) -> None:
        pass

    def _on_owner_scan_aborted(self, *_a: Any) -> None:
        pass

    def _on_scan_error(self, *_a: Any) -> None:
        pass


def _library() -> Dict[str, Any]:
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        [_ELEMENT, _CLIPS],
        [{"name": libcfg.COMMON_LABEL, "folders": [_ELEMENT]}],
    )
    return lib


@pytest.fixture()
def env(tmp_app_dir: Path, tmp_path: Path, monkeypatch):
    """공유 서버 호출을 전부 가짜로 — 기록용 dict 를 돌려준다."""
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    state: Dict[str, Any] = {
        "shared": {"published_at": "T1", "grouping_version": 2, "items": 0},
        "published": [],
        "library": _library(),
        "probe": None,
    }

    def fake_publish(conn):
        state["published"].append(db.total_indexed(conn))
        meta = {"published_at": "T2", "items": db.total_indexed(conn), "grouping_version": 2}
        state["shared"] = dict(meta)
        return meta

    def fake_save(lib, path=None):
        state["saved"] = state.get("saved", 0) + 1
        state["library"] = lib

    monkeypatch.setattr(publish, "read_shared_meta", lambda: dict(state["shared"]))
    monkeypatch.setattr(publish, "publish_index", fake_publish)
    monkeypatch.setattr(libcfg, "load_library", lambda *a, **k: state["library"])
    monkeypatch.setattr(libcfg, "save_library", fake_save)
    monkeypatch.setattr(libcfg, "probe_library_read", lambda *a, **k: state["probe"])
    monkeypatch.setattr(sdlg, "LibraryScanWorker", _FakeWorker)
    monkeypatch.setattr(sdlg, "_track_thread", lambda t: None)
    _FakeWorker.created.clear()
    conn = db.connect()
    state["conn"] = conn
    yield state
    conn.close()


def _items(names: List[str]):
    return group_entries([FileEntry(n, 1, 1.0) for n in names])


def _put(conn, dir_rel: str, names: List[str]) -> None:
    db.replace_dir_items(conn, _CLIPS, dir_rel, _items(names))
    conn.commit()


def _names(conn, root: str = _CLIPS) -> List[str]:
    return sorted(r["name"] for r in db.fetch_items(conn, roots=[root]))


def _library_with_plate() -> Dict[str, Any]:
    """MMK_Plate 정리 폴더 안에 Day1 이 가상 폴더로 들어 있는 실데이터 모양."""
    lib = _library()
    libcfg.add_top_level_folder(lib, "MMK_Plate")
    assert libcfg.organize_into_folder(lib, "MMK_Plate", _CLIPS + "/Day1")
    return lib


# ── 요청 ────────────────────────────────────────────────────────────


def test_request_rejected_when_closed_scanning_or_pending(env) -> None:
    s = _Stub(env["conn"])
    s._shutdown_done = True
    assert "닫혀" in s.request_library_refresh([_CLIPS])
    s._shutdown_done = False
    s._scan_queue = [{"roots": ["x"]}]
    assert "이미 스캔 중" in s.request_library_refresh([_CLIPS])
    s._scan_queue = []
    s._refresh_pending = True
    assert "준비 중" in s.request_library_refresh([_CLIPS])
    assert s.sync_started == 0


def test_request_starts_sync_and_normalizes_roots(env) -> None:
    s = _Stub(env["conn"])
    msg = s.request_library_refresh(["W:\\proj\\clips\\", _CLIPS])
    assert "요청됨" in msg
    assert s._refresh_pending is True
    assert s._scan_refresh_roots == [_CLIPS]
    assert s.sync_started == 1


# ── 공유 목록 받은 뒤 이어서 ─────────────────────────────────────────


def test_sync_done_continues_into_strict_refresh_scan(env) -> None:
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS, _ELEMENT])  # element 는 걸러져야 한다
    s._on_index_sync_done(None)
    assert s._refresh_pending is False
    assert len(_FakeWorker.created) == 1
    w = _FakeWorker.created[0]
    assert w.roots == [_CLIPS]
    assert w.kwargs["strict"] is True
    assert w.kwargs["preview"] is True
    assert w.kwargs["pack_roots"] == [_ELEMENT]
    assert w.kwargs["force"] is False
    assert s._scan_is_refresh is True
    assert s._refresh_shared_at == "T1"
    assert s._refresh_baseline is not None
    assert publish.read_refresh_baseline()["published_at"] == "T1"


def test_sync_done_from_stale_worker_does_not_continue(env) -> None:
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._index_sync_worker = object()
    s._sender = object()  # 이전(다른) 동기 워커가 보낸 늦은 신호
    s._on_index_sync_done(None)
    assert s._refresh_pending is True
    assert _FakeWorker.created == []


def test_sync_error_cancels_pending_refresh(env) -> None:
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._on_index_sync_error("network down")
    assert s._refresh_pending is False
    assert "새로고침을 멈췄습니다" in s._status_label.text()
    assert _FakeWorker.created == []


def test_continue_stops_when_library_unreadable(env) -> None:
    env["probe"] = "JSON 파싱 실패"
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._on_index_sync_done(None)
    assert _FakeWorker.created == []
    assert "설정 파일을 못 읽어" in s._status_label.text()


def test_continue_stops_without_shared_meta(env) -> None:
    env["shared"] = {}
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._on_index_sync_done(None)
    assert _FakeWorker.created == []
    assert "공유 목록 정보를 읽지 못해" in s._status_label.text()


def test_continue_skips_when_other_scan_started(env) -> None:
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._scan_queue = [{"roots": [_CLIPS]}]  # 그사이 관리자 「전체 스캔」
    s._on_index_sync_done(None)
    assert s._refresh_pending is False
    assert "건너뜀" in s._status_label.text()


def test_continue_stops_when_root_moved_to_compositing_source(env) -> None:
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        [_ELEMENT, _CLIPS],
        [{"name": libcfg.COMMON_LABEL, "folders": [_ELEMENT, _CLIPS]}],
    )
    env["library"] = lib
    s = _Stub(env["conn"])
    s.request_library_refresh([_CLIPS])
    s._on_index_sync_done(None)
    assert _FakeWorker.created == []
    assert "새로고침할 폴더가 없습니다" in s._status_label.text()


# ── 스캔 시작: 새로고침 표시는 job 마다 새로 ──────────────────────────


def test_non_refresh_job_is_unchanged(env) -> None:
    s = _Stub(env["conn"])
    s._scan_is_refresh = True  # 이전 새로고침 흔적이 남아 있어도
    s._start_scan_job({"roots": [_CLIPS], "force": True, "publish": True, "hidden": []})
    w = _FakeWorker.created[-1]
    assert w.kwargs["strict"] is False
    assert w.kwargs["preview"] is False
    assert w.kwargs["pack_roots"] == [_ELEMENT]
    assert w.kwargs["force"] is True
    assert s._scan_is_refresh is False
    assert s._refresh_baseline is None


# ── 스캔 끝: 리뷰 → 적용 → 게시 여부 ────────────────────────────────


def _run_refresh(s: _Stub, env, found: Dict[str, Any], failures: int = 0) -> None:
    """요청 → 동기 완료 → (훑기 결과를 미리보기 상자에 담음) → 스캔 완료.

    ``found``: ``{dir_rel: [파일명...]}`` 또는 ``{dir_rel: None}``(사라진 폴더).
    인덱스에는 아무것도 직접 쓰지 않는다 — 실제 preview 모드와 같다.
    """
    from bpe.core.source_library_refresh import RefreshPreview

    s.request_library_refresh([_CLIPS])
    s._on_index_sync_done(None)
    w = _FakeWorker.created[-1]
    s._scan_worker = w
    conn = env["conn"]
    result = RefreshPreview()
    result.begin_root(conn, _CLIPS)
    gone = []
    for dir_rel, names in found.items():
        if names is None:
            gone.append(dir_rel)
        else:
            result.record_dir(conn, _CLIPS, dir_rel, _items(names), 5.0)
    result.finish_root(_CLIPS, gone)
    w.preview_result = result
    w.read_failures = failures
    w._running = False
    s._publish_after_scan(0)


def test_refresh_unchanged_no_review_no_publish(env) -> None:
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day1": ["a.mov"]})  # 시각만 바뀐 폴더 → 내용 같음
    assert s.review_calls == []
    assert env["published"] == []
    assert s.reload_refresh == 0
    assert "바뀐 파일 없음" in s._status_label.text()


def test_refresh_review_lists_new_existing_and_applies_selected(env) -> None:
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day1": ["a.mov", "b.mov"], "Day2": ["c.mov"], "Day3/Reel": ["d.mov"]})
    groups, failures = s.review_calls[0]
    assert failures == 0
    assert [(g.category, g.kind) for g in groups] == [
        ("Day2", "new"),
        ("Day3", "new"),
        ("Day1", "existing"),
    ]
    assert groups[2].added == 1 and groups[0].clips == 1
    # 전부 체크 → 전부 들어가고 게시
    assert _names(env["conn"]) == ["a", "b", "c", "d"]
    assert env["published"] == [4]
    assert s.reload_refresh == 1 and s.reload_scan == 0
    text = s._status_label.text()
    assert "팀 공유 목록 갱신" in text
    # 새 폴더 Day2·Day3 는 Day1 이 있는 MMK_Plate 에 자동 분류
    assert "분류에 넣음 2개" in text
    organized = libcfg.library_organized_paths(env["library"])
    assert _CLIPS + "/Day2" in organized and _CLIPS + "/Day3" in organized
    assert env.get("saved") == 1
    base = publish.read_refresh_baseline()
    assert base["published_at"] == "T2"
    assert base["roots"][_CLIPS]["items"] == 4


def test_refresh_partial_selection_leaves_rest_for_next_time(env) -> None:
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    s.review_answer = {(_CLIPS, "Day2")}
    _run_refresh(s, env, {"Day2": ["c.mov"], "Day3": ["d.mov"]})
    assert _names(env["conn"]) == ["a", "c"]
    assert env["published"] == [2]
    # 다음 새로고침: 안 고른 Day3 가 다시 나온다
    s2 = _Stub(env["conn"])
    _run_refresh(s2, env, {"Day3": ["d.mov"]})
    assert [g.category for g in s2.review_calls[0][0]] == ["Day3"]
    assert _names(env["conn"]) == ["a", "c", "d"]


def test_refresh_cancel_writes_and_publishes_nothing(env) -> None:
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    s.review_answer = None
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    assert _names(env["conn"]) == ["a"]
    assert env["published"] == []
    assert env.get("saved") is None
    assert s.reload_refresh == 0
    assert "새로고침 취소" in s._status_label.text()


def test_refresh_deleted_folder_is_removed_when_selected(env) -> None:
    lib = _library_with_plate()
    assert libcfg.organize_into_folder(lib, "MMK_Plate", _CLIPS + "/Day2")
    env["library"] = lib
    _put(env["conn"], "Day1", ["a.mov"])
    _put(env["conn"], "Day2", ["c.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day2": None})
    groups, _ = s.review_calls[0]
    assert [(g.category, g.kind, g.removed) for g in groups] == [("Day2", "existing", 1)]
    assert _names(env["conn"]) == ["a"]
    assert env["published"] == [1]


def test_refresh_unorganized_only_shows_review_and_organizes(env) -> None:
    """인덱스엔 이미 있는데 트리에 안 보이는 폴더 — 새 파일이 없어도 창에 나온다."""
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])
    _put(env["conn"], "Day9", ["z.mov"])  # 이미 팀 목록엔 있고 분류만 안 됨
    s = _Stub(env["conn"])
    _run_refresh(s, env, {})
    groups, _ = s.review_calls[0]
    assert [(g.category, g.kind, g.clips) for g in groups] == [("Day9", "unorganized", 1)]
    assert env["published"] == []  # 내용은 팀 장부와 같음
    assert _CLIPS + "/Day9" in libcfg.library_organized_paths(env["library"])
    assert s.reload_refresh == 1
    text = s._status_label.text()
    assert "바뀐 파일 없음" in text and "분류에 넣음 1개 (Day9)" in text


def test_refresh_auto_organize_reports_when_no_sibling(env) -> None:
    """어느 분류에도 옆 폴더가 없으면 넣지 못했다고 알린다 (Day1 은 분류 안 됨으로 같이 나옴)."""
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    groups, _ = s.review_calls[0]
    assert [(g.category, g.kind) for g in groups] == [("Day2", "new"), ("Day1", "unorganized")]
    assert env["published"] == [2]
    assert "분류 못 넣은 폴더 2개 (Day2 외)" in s._status_label.text()
    assert env.get("saved") is None


def test_refresh_owned_root_is_not_auto_organized(env) -> None:
    """그룹이 루트를 소유하면(평탄 표시) 새 폴더를 분류에 넣을 필요가 없다."""
    lib = _library()
    assert libcfg.assign_roots_to_group(lib, [_CLIPS], "MMK") == 1
    env["library"] = lib
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    groups, _ = s.review_calls[0]
    assert [(g.category, g.kind) for g in groups] == [("Day2", "new")]
    text = s._status_label.text()
    assert "분류" not in text and "팀 공유 목록 갱신" in text


def test_refresh_auto_organize_goes_through_open_settings_dialog(env) -> None:
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])

    class _Settings:
        def __init__(self):
            self.calls = []

        def apply_auto_organize(self, pairs):
            self.calls.append(list(pairs))
            return [_CLIPS + "/Day2"], []

    s = _Stub(env["conn"])
    s._settings_dlg = _Settings()
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    assert s._settings_dlg.calls == [[(_CLIPS, "Day2")]]
    assert env.get("saved") is None  # 저장은 설정 창이 맡는다
    assert "분류에 넣음 1개" in s._status_label.text()


def test_refresh_read_error_holds_and_retry_publishes(env) -> None:
    env["library"] = _library_with_plate()
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day2": ["c.mov"]}, failures=1)
    assert s.review_calls[0][1] == 1
    assert _names(env["conn"]) == ["a", "c"]  # 고른 건 이 PC 에 반영
    assert env["published"] == []
    assert s.reload_refresh == 1
    assert "읽지 못해 팀 공유 보류" in s._status_label.text()

    # 다시 누름: 새로 찾은 건 없지만 기준선(팀 장부)과 다르므로 게시된다
    s2 = _Stub(env["conn"])
    _run_refresh(s2, env, {})
    assert s2.review_calls == []
    assert env["published"] == [2]
    assert "팀 공유 목록 갱신" in s2._status_label.text()


def test_refresh_big_loss_is_held(env) -> None:
    _put(env["conn"], "Day1", ["c{:03d}.mov".format(i) for i in range(300)])
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day1": ["c000.mov"]})
    assert env["published"] == []
    assert "많이 줄어" in s._status_label.text()


def test_refresh_shared_moved_does_not_overwrite(env) -> None:
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])

    def review(groups, failures):
        env["shared"] = {"published_at": "T9", "grouping_version": 2}
        return {g.key for g in groups}

    s._review_refresh = review  # type: ignore[method-assign]
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    assert env["published"] == []
    assert "다른 사람이" in s._status_label.text()


def test_refresh_publish_failure_is_reported(env, monkeypatch) -> None:
    _put(env["conn"], "Day1", ["a.mov"])

    def boom(conn):
        raise PermissionError("locked")

    monkeypatch.setattr(publish, "publish_index", boom)
    s = _Stub(env["conn"])
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    assert "게시 실패" in s._status_label.text()
    assert s.reload_refresh == 1
    assert publish.read_refresh_baseline()["published_at"] == "T1"


def test_refresh_shutdown_during_review_writes_nothing(env) -> None:
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])

    def review(groups, failures):
        s._shutdown_done = True
        return {g.key for g in groups}

    s._review_refresh = review  # type: ignore[method-assign]
    _run_refresh(s, env, {"Day2": ["c.mov"]})
    assert _names(env["conn"]) == ["a"]
    assert env["published"] == []


def test_reviewing_blocks_new_refresh_and_queues_scans(env) -> None:
    s = _Stub(env["conn"])
    s._refresh_reviewing = True
    assert s.is_library_scanning() is True
    assert "이미 스캔 중" in s.request_library_refresh([_CLIPS])
    s.enqueue_library_scan([_CLIPS], force=True, publish=True)
    assert _FakeWorker.created == []
    assert s._scan_queue and s._scan_queue[0]["force"] is True


def test_non_refresh_scan_still_always_publishes(env) -> None:
    """회귀 방지: 「전체 스캔」 등 기존 스캔은 바뀐 게 없어도 기존처럼 게시·트리 초기화."""
    _put(env["conn"], "Day1", ["a.mov"])
    s = _Stub(env["conn"])
    s._start_scan_job({"roots": [_CLIPS], "force": True, "publish": True, "hidden": []})
    s._publish_after_scan(0)
    assert env["published"] == [1]
    assert s.reload_scan == 1
    assert s.reload_refresh == 0
    assert "스캔·게시 완료" in s._status_label.text()


# ── 설정 창 버튼 ───────────────────────────────────────────────────


class _Owner:
    def __init__(self) -> None:
        self.requested: List[List[str]] = []

    def request_library_refresh(self, roots):
        self.requested.append(list(roots))
        return "새로고침 요청됨"


class _Picker:
    result: Any = None
    choices: List[Any] = []
    picked: List[str] = []

    def __init__(self, parent, choices) -> None:
        _Picker.choices = list(choices)

    def exec(self):
        return _Picker.result

    def selected_roots(self):
        return list(_Picker.picked)


class _SettingsStub:
    from bpe.gui.widgets.source_library_settings_dialog import SourceLibrarySettingsDialog as _S

    _on_refresh_request = _S._on_refresh_request

    def __init__(self, owner, library) -> None:
        self._owner = owner
        self._library = library
        self._status = _Label()

    def _owner_scan(self):
        return self._owner


@pytest.fixture()
def picker(monkeypatch):
    from PySide6.QtWidgets import QDialog

    import bpe.gui.widgets.library_refresh_roots_dialog as picker_mod

    monkeypatch.setattr(picker_mod, "LibraryRefreshRootsDialog", _Picker)
    _Picker.result = QDialog.DialogCode.Accepted
    _Picker.picked = [_CLIPS]
    return _Picker


def test_settings_refresh_sends_picked_roots(picker) -> None:
    owner = _Owner()
    st = _SettingsStub(owner, _library())
    st._on_refresh_request()
    assert picker.choices == [(_ELEMENT, False), (_CLIPS, True)]
    assert owner.requested == [[_CLIPS]]
    assert st._status.text() == "새로고침 요청됨"


def test_settings_refresh_cancel_does_nothing(picker) -> None:
    from PySide6.QtWidgets import QDialog

    picker.result = QDialog.DialogCode.Rejected
    owner = _Owner()
    _SettingsStub(owner, _library())._on_refresh_request()
    assert owner.requested == []


def test_settings_refresh_without_owner(picker) -> None:
    st = _SettingsStub(None, _library())
    st._on_refresh_request()
    assert "스캔 소유자" in st._status.text()


def test_settings_refresh_when_only_compositing_source(picker) -> None:
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib, libcfg.COMMON_SCOPE, [_ELEMENT], [{"name": libcfg.COMMON_LABEL, "folders": [_ELEMENT]}]
    )
    owner = _Owner()
    st = _SettingsStub(owner, lib)
    st._on_refresh_request()
    assert owner.requested == []
    assert "새로고침할 폴더가 없습니다" in st._status.text()


def test_settings_apply_auto_organize_persists(monkeypatch) -> None:
    from bpe.gui.widgets.source_library_settings_dialog import SourceLibrarySettingsDialog

    class _St:
        apply_auto_organize = SourceLibrarySettingsDialog.apply_auto_organize

        def __init__(self):
            self._library = _library_with_plate()
            self.persisted: List[str] = []
            self.reloaded = 0

        def _persist_and_status(self, text, reload=None):
            self.persisted.append(text)
            if reload:
                reload()
            return True

        def _reload_group_tree(self):
            self.reloaded += 1

    st = _St()
    done, failed = st.apply_auto_organize([(_CLIPS, "Day2"), (_CLIPS, "기타")])
    assert done == [_CLIPS + "/Day2"]
    assert failed == [_CLIPS + "/기타"]
    assert st.persisted == ["새로고침: 분류에 넣음 1개"] and st.reloaded == 1
    assert _CLIPS + "/Day2" in libcfg.library_organized_paths(st._library)


# ── 리뷰 창·_review_refresh (실제 위젯) ─────────────────────────────


def test_review_dialog_defaults_and_texts(qtbot) -> None:
    from bpe.core.source_library_refresh import RefreshGroup
    from bpe.gui.widgets.library_refresh_review_dialog import (
        LibraryRefreshReviewDialog,
        count_text,
    )

    groups = [
        RefreshGroup(_CLIPS, "Day2", "new", 3, 0, 0, 3),
        RefreshGroup(_CLIPS, "Day1", "existing", 5, 2, 1, 6),
        RefreshGroup(_CLIPS, "Day9", "unorganized", 0, 0, 0, 12),
    ]
    assert count_text(groups[0]) == "클립 3개"
    assert count_text(groups[1]) == "클립 +5 · −2 · 변경 1"
    assert count_text(groups[2]) == "클립 12개"
    dlg = LibraryRefreshReviewDialog(None, groups, read_failures=2)
    qtbot.addWidget(dlg)
    assert dlg.selected_keys() == {g.key for g in groups}
    assert dlg._footer.text() == "총 3개 폴더 선택"
    assert dlg._ok_btn.isEnabled()
    for _g, box in dlg._rows:
        box.setChecked(False)
    assert dlg.selected_keys() == set()
    assert dlg._ok_btn.isEnabled() is False


def test_review_refresh_resets_flag_and_returns_none_on_cancel(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    class _Fake:
        rc = QDialog.DialogCode.Rejected

        def __init__(self, parent, groups, **kw):
            self.kw = kw

        def setWindowModality(self, m):
            pass

        def exec(self):
            return _Fake.rc

        def selected_keys(self):
            return {("r", "c")}

        def deleteLater(self):
            pass

    monkeypatch.setattr(sdlg, "LibraryRefreshReviewDialog", _Fake)

    class _Host:
        _review_refresh = SourceLibraryDialog._review_refresh

        def __init__(self):
            self._settings_dlg = None
            self._refresh_reviewing = False
            self._status_label = _Label()
            self.front = 0

        def _bring_to_front(self):
            self.front += 1

    h = _Host()
    assert h._review_refresh([], 0) is None
    assert h._refresh_reviewing is False and h.front == 1
    _Fake.rc = QDialog.DialogCode.Accepted
    assert h._review_refresh([], 0) == {("r", "c")}
    assert h._refresh_reviewing is False


# ── 폴더 고르기 창 (실제 위젯) ───────────────────────────────────────


def test_refresh_roots_dialog_defaults(qtbot) -> None:
    from bpe.gui.widgets.library_refresh_roots_dialog import LibraryRefreshRootsDialog

    dlg = LibraryRefreshRootsDialog(None, [(_ELEMENT, False), (_CLIPS, True), ("W:/b", True)])
    qtbot.addWidget(dlg)
    assert dlg.selected_roots() == [_CLIPS, "W:/b"]
    boxes = dlg._boxes
    assert boxes[0][1].isEnabled() is False and boxes[0][1].isChecked() is False
    assert dlg._ok_btn.isEnabled() is True
    for _path, box in boxes:
        box.setChecked(False)
    assert dlg.selected_roots() == []
    assert dlg._ok_btn.isEnabled() is False
