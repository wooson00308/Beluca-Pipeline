# @cursor-change: 2026-08-09, 0.13.x, handoff pending offer·더블팝업 방지·deferred timer
"""BPE Source Library 핸드오프를 Nuke Read 노드로 만든다.

PySide6 / shotgrid import 금지. core + nuke (+ Nuke PySide2 QTimer) 만 사용.
클립보드 Tcl 이 아닌 Python 노브 설정이라 한글 경로가 통과하기 쉽다.
원본 미디어 파일은 읽기만 한다(노브에 경로 문자열만 넣음).
"""

from __future__ import annotations

import nuke

from bpe.core.library_handoff import (
    handoff_is_consumed,
    handoff_send_id,
    mark_handoff_consumed,
    read_handoff,
    read_handoff_payload,
)
from bpe.core.nuke_render_paths import normalize_path_str

_POLL_MS = 1000
_timer = None
_last_seen_send_id = ""
_dialog_open = False
_baselined = False
_offer_scheduled = False
_start_scheduled = False


def _create_reads_from_items(items: list) -> int:
    # 서버 원본을 복사·이동하지 않는다. Read file knob 에 경로 포인터만 넣는다.
    created = 0
    errors = 0
    for it in items:
        path = normalize_path_str(str(it.get("path") or ""))
        if not path:
            continue
        try:
            node = nuke.createNode("Read", inpanel=False)
            node["file"].fromUserText(path)
            kind = str(it.get("kind") or "")
            if kind == "sequence" and "first" in it and "last" in it:
                first = int(it["first"])
                last = int(it["last"])
                if last < first:
                    first, last = last, first
                try:
                    node["first"].setValue(first)
                    node["last"].setValue(last)
                    node["origfirst"].setValue(first)
                    node["origlast"].setValue(last)
                except Exception:
                    pass
            created += 1
        except Exception as exc:
            errors += 1
            nuke.tprint("[BPE] Read 생성 실패: %s (%s)" % (path, exc))
    if created <= 0 and errors > 0:
        nuke.message("[BPE] Read 노드를 만들지 못했습니다.")
    elif created > 0:
        nuke.tprint("[BPE] 라이브러리에서 Read %d개 생성" % created)
        if errors:
            nuke.message("[BPE] Read %d개 생성, %d개 실패 (Script Editor 참고)" % (created, errors))
    return created


def import_library_handoff() -> None:
    """메뉴 폴백 — handoff 항목으로 Read 노드를 만든다 (확인 없음)."""
    items = read_handoff()
    if not items:
        nuke.message(
            "[BPE] 가져올 라이브러리 항목이 없습니다.\n\n"
            "BPE Source Library 에서 항목을 선택한 뒤\n"
            "「Nuke로 보내기」를 누르세요.\n"
            "(Nuke가 켜져 있으면 예/아니오 팝업이 뜹니다.)"
        )
        return
    _create_reads_from_items(items)
    try:
        mark_handoff_consumed()
    except Exception as exc:
        nuke.tprint("[BPE] handoff consumed 표시 실패: %s" % exc)


def _schedule_offer() -> bool:
    """팝업을 한 번만 예약. 이미 예약/표시 중이면 False."""
    global _offer_scheduled
    if _dialog_open or _offer_scheduled:
        return False
    _offer_scheduled = True
    nuke.executeDeferred(_offer_import_popup)
    return True


def _offer_import_popup() -> None:
    global _dialog_open, _last_seen_send_id, _offer_scheduled
    _offer_scheduled = False
    if _dialog_open:
        return
    try:
        data = read_handoff_payload()
        send_id = handoff_send_id(data)
        if not send_id:
            return
        if send_id == _last_seen_send_id:
            return
        if handoff_is_consumed(data):
            _last_seen_send_id = send_id
            return
        items = read_handoff()
        if not items:
            _last_seen_send_id = send_id
            return

        names = []
        for it in items[:5]:
            n = str(it.get("name") or "").strip()
            if n:
                names.append(n)
        preview = "\n".join("  · " + n for n in names)
        if len(items) > 5:
            preview += "\n  · … 외 %d개" % (len(items) - 5)

        msg = "[BPE] Source Library\n\n%d개 소스를 Read 노드로 가져올까요?\n" % len(items)
        if preview:
            msg += "\n" + preview + "\n"
        msg += "\n예 = 가져오기 / 아니오 = 취소"

        _dialog_open = True
        try:
            accepted = bool(nuke.ask(msg))
        finally:
            _dialog_open = False

        _last_seen_send_id = send_id
        if accepted:
            _create_reads_from_items(items)
        try:
            mark_handoff_consumed()
        except Exception as exc:
            nuke.tprint("[BPE] handoff consumed 표시 실패: %s" % exc)
    except Exception as exc:
        _dialog_open = False
        _offer_scheduled = False
        nuke.tprint("[BPE] 라이브러리 가져오기 팝업 실패: %s" % exc)


def _poll_handoff() -> None:
    global _last_seen_send_id, _baselined
    if _dialog_open or _offer_scheduled:
        return
    try:
        data = read_handoff_payload()
        send_id = handoff_send_id(data)
        if not _baselined:
            # 시작 직후 폴: pending 은 start 쪽에서 처리. 여기선 소비된/빈 것만 기준선.
            if send_id and (not handoff_is_consumed(data)) and read_handoff():
                _baselined = True
                _schedule_offer()
                return
            _last_seen_send_id = send_id
            _baselined = True
            return
        if not send_id or send_id == _last_seen_send_id:
            return
        if handoff_is_consumed(data):
            _last_seen_send_id = send_id
            return
        if not read_handoff():
            _last_seen_send_id = send_id
            return
        _schedule_offer()
    except Exception as exc:
        nuke.tprint("[BPE] handoff 감시 오류: %s" % exc)


def _pending_unconsumed() -> bool:
    data = read_handoff_payload()
    send_id = handoff_send_id(data)
    if not send_id:
        return False
    if handoff_is_consumed(data):
        return False
    return bool(read_handoff())


def _start_handoff_watcher_impl() -> None:
    """UI/이벤트 루프 준비 후 타이머를 켠다."""
    global _timer, _baselined, _last_seen_send_id
    if _timer is not None:
        return

    try:
        import bpe as _bpe_pkg

        nuke.tprint("[BPE] handoff bpe=%s" % getattr(_bpe_pkg, "__file__", "?"))
    except Exception:
        pass

    pending = False
    try:
        pending = _pending_unconsumed()
        if pending:
            # 미처리 전송은 “이미 봄”으로 삼키지 않는다.
            _last_seen_send_id = ""
            _baselined = True
        else:
            data = read_handoff_payload()
            _last_seen_send_id = handoff_send_id(data)
            _baselined = True
    except Exception:
        _last_seen_send_id = ""
        _baselined = True
        pending = False

    if pending:
        _schedule_offer()
        nuke.tprint("[BPE] Source Library 미처리 handoff 팝업 예약")

    try:
        from PySide2.QtCore import QTimer  # Nuke 번들 (PySide6 금지)
        from PySide2.QtWidgets import QApplication

        app = QApplication.instance()
        t = QTimer(app) if app is not None else QTimer()
        t.setInterval(_POLL_MS)
        t.timeout.connect(_poll_handoff)
        t.start()
        _timer = t
        nuke.tprint("[BPE] Source Library handoff 감시 시작")
        return
    except Exception as exc:
        nuke.tprint("[BPE] QTimer 감시 실패, 스레드 폴백: %s" % exc)

    import threading

    def _loop() -> None:
        global _timer
        try:
            try:
                nuke.executeInMainThread(_poll_handoff)
            except Exception:
                nuke.executeDeferred(_poll_handoff)
        except Exception as e:
            nuke.tprint("[BPE] handoff poll 실패: %s" % e)
        if _timer == "thread":
            threading.Timer(_POLL_MS / 1000.0, _loop).start()

    _timer = "thread"
    threading.Timer(_POLL_MS / 1000.0, _loop).start()
    nuke.tprint("[BPE] Source Library handoff 감시 시작 (thread)")


def start_handoff_watcher() -> None:
    """BPE 「Nuke로 보내기」를 감지해 예/아니오 팝업을 띄운다.

    menu.py 초기화 직후엔 이벤트 루프가 불안정할 수 있어 실제 시작은 deferred.
    """
    global _start_scheduled, _timer
    if _timer is not None or _start_scheduled:
        return
    _start_scheduled = True
    try:
        nuke.executeDeferred(_start_handoff_watcher_impl)
    except Exception as exc:
        _start_scheduled = False
        nuke.tprint("[BPE] handoff 감시 deferred 실패, 즉시 시작: %s" % exc)
        _start_handoff_watcher_impl()


_frame_fix_registered = False


def _fix_dropped_read_frame_range() -> None:
    """그리드→캔버스 네이티브 드래그로 만들어진 Read 의 프레임 범위를 인덱스 값으로 교정한다.

    한글 경로 드래그는 Tcl 텍스트 대신 파일 URL만 보낸다(source_library_grid.py) —
    그래서 프레임 범위가 일단 Nuke 자체 시퀀스 감지에 맡겨지는데, 여기서 BPE 인덱스의
    정확한 값으로 덮어쓴다. 등록된 라이브러리 루트 밖의 Read 는 건드리지 않는다
    (일반 샷 Read 노드에 영향 없음). 이미 정확한 값이면 같은 값을 다시 쓰는 것뿐이라
    스크립트 로드 시 저장된 Read 에 다시 걸려도 무해하다.
    """
    try:
        node = nuke.thisNode()
    except Exception:
        return
    try:
        file_knob = node.knob("file")
        if file_knob is None:
            return
        path = normalize_path_str(str(file_knob.value() or ""))
        if not path or "/" not in path:
            return
        dir_path, filename = path.rsplit("/", 1)

        from bpe.core import source_library_config as libcfg
        from bpe.core import source_library_db as db

        roots = libcfg.common_roots_list(libcfg.load_library())
        if not roots:
            return
        split = libcfg.split_folder_to_root_dir_rel(dir_path, roots)
        if split is None:
            return
        root, dir_rel = split

        conn = db.connect()
        try:
            frange = db.find_sequence_frame_range(conn, root, dir_rel, filename)
        finally:
            conn.close()
        if frange is None:
            return
        first, last = frange
        node["first"].setValue(first)
        node["last"].setValue(last)
        node["origfirst"].setValue(first)
        node["origlast"].setValue(last)
    except Exception as exc:
        nuke.tprint("[BPE] 드롭 Read 프레임 범위 교정 실패: %s" % exc)


def register_frame_range_fix() -> None:
    """등록 라이브러리 루트 밑에서 Read 가 새로 생기면 프레임 범위를 인덱스로 교정한다."""
    global _frame_fix_registered
    if _frame_fix_registered:
        return
    try:
        nuke.addOnCreate(_fix_dropped_read_frame_range, nodeClass="Read")
        _frame_fix_registered = True
    except Exception as exc:
        nuke.tprint("[BPE] 프레임 범위 교정 콜백 등록 실패: %s" % exc)
