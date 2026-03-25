"""Tool Hooks — QC Checker (BeforeRender) 및 Post-Render Viewer (AfterRender)."""

from __future__ import annotations

import os
import re

import nuke
import nukescripts

from bpe.core.presets import load_presets
from bpe.core.settings import get_tools_settings
import bpe.core.config as cfg


# ══════════════════════════════════════════════════════════════════════
# 공용 유틸리티
# ══════════════════════════════════════════════════════════════════════

def _knob_value_safe(node, *knob_candidates) -> str:
    """여러 후보 knob 이름 중 첫 번째로 값을 가진 것을 반환한다."""
    for kname in knob_candidates:
        k = node.knob(kname)
        if k is not None:
            try:
                return str(k.value()).strip()
            except Exception:
                pass
    return ""


def _find_upstream_reads(node):
    """Write 노드에서 upstream을 역추적해 모든 Read 노드를 반환한다.
    명시적 스택으로 RecursionError 방지.
    """
    results = []
    seen: set = set()
    stack = [node]
    while stack:
        current = stack.pop()
        try:
            name = current.name()
        except Exception:
            continue
        if name in seen:
            continue
        seen.add(name)
        if current.Class() == "Read":
            results.append(current)
        try:
            deps = current.dependencies(nuke.INPUTS)
        except Exception:
            deps = []
        for dep in deps:
            stack.append(dep)
    return results


# ══════════════════════════════════════════════════════════════════════
# QC CHECKER
# ══════════════════════════════════════════════════════════════════════

# QC 승인 후 재실행되는 렌더를 식별하는 전역 상태
_bpe_qc_approved: set = set()


def _guess_preset_from_script():
    """현재 열린 NK의 Write 파일 경로로 프리셋을 추론한다."""
    try:
        presets = load_presets()
        write_nodes = nuke.allNodes("Write")
        for write in write_nodes:
            file_path = _knob_value_safe(write, "file")
            for name, data in presets.items():
                code = (data.get("project_code") or "").strip().upper()
                if code and code in file_path.upper():
                    return name, data
    except Exception:
        pass
    return None, None


def collect_qc_data(write_node) -> dict:
    """렌더 대상 Write 노드에서 QC에 필요한 정보를 수집한다."""
    root = nuke.root()
    data = {}

    # Root 정보
    try:
        data["fps"] = str(root["fps"].value())
    except Exception:
        data["fps"] = "?"

    try:
        fmt = root.format()
        data["width"] = str(int(fmt.width()))
        data["height"] = str(int(fmt.height()))
        data["format_name"] = fmt.name()
    except Exception:
        data["width"] = "?"
        data["height"] = "?"
        data["format_name"] = "?"

    data["ocio_path"] = _knob_value_safe(
        root, "customOCIOConfigPath", "OCIO_config", "ocioConfigPath",
    )

    # Write 정보
    data["write_name"] = write_node.name()
    data["write_file"] = _knob_value_safe(write_node, "file")
    data["write_colorspace"] = _knob_value_safe(
        write_node, "ocioColorspace", "colorspace", "colorSpace",
    )
    data["write_file_type"] = _knob_value_safe(
        write_node, "file_type", "fileType", "file_format",
    )

    try:
        data["write_first"] = int(write_node["first"].value())
        data["write_last"] = int(write_node["last"].value())
    except Exception:
        data["write_first"] = None
        data["write_last"] = None

    # Upstream Read 분류
    all_reads = _find_upstream_reads(write_node)

    plate_reads = [
        r for r in all_reads
        if any(k in _knob_value_safe(r, "file").lower() for k in ("plate", "/org/", "\\org\\"))
    ]
    edit_reads = [
        r for r in all_reads
        if any(k in _knob_value_safe(r, "file").lower() for k in ("edit", "/edit/", "\\edit\\"))
    ]

    if plate_reads:
        pr = plate_reads[0]
        data["plate_colorspace"] = _knob_value_safe(pr, "colorspace", "colorSpace")
        data["plate_file"] = _knob_value_safe(pr, "file")
        try:
            data["plate_first"] = int(pr["first"].value())
            data["plate_last"] = int(pr["last"].value())
            data["plate_frames"] = data["plate_last"] - data["plate_first"] + 1
        except Exception:
            data["plate_first"] = None
            data["plate_last"] = None
            data["plate_frames"] = None
    else:
        data["plate_colorspace"] = None
        data["plate_file"] = None
        data["plate_frames"] = None

    if edit_reads:
        er = edit_reads[0]
        data["edit_file"] = _knob_value_safe(er, "file")
        try:
            data["edit_first"] = int(er["first"].value())
            data["edit_last"] = int(er["last"].value())
            data["edit_frames"] = data["edit_last"] - data["edit_first"] + 1
        except Exception:
            data["edit_first"] = None
            data["edit_last"] = None
            data["edit_frames"] = None
    else:
        data["edit_file"] = None
        data["edit_frames"] = None

    # 프리셋 매칭
    preset_name, preset_data = _guess_preset_from_script()
    data["preset_name"] = preset_name
    data["preset_data"] = preset_data or {}

    return data


def _qc_status_line(label, current, expected=None, ok_if_none=False):
    """체크 한 줄을 (status, label, current, note) 튜플로 반환한다."""
    if current is None or current == "":
        if ok_if_none:
            return ("ok", label, "(없음)", "")
        return ("warn", label, "(감지 안됨)", "")
    if expected is None:
        return ("ok", label, current, "")
    current_s = str(current).strip()
    expected_s = str(expected).strip()
    if current_s.lower() == expected_s.lower():
        return ("ok", label, current_s, "프리셋 일치")
    else:
        return ("warn", label, current_s, f"프리셋: {expected_s}  <- 불일치!")


def _show_qc_dialog(qc_data: dict) -> bool:
    """QC 결과를 PythonPanel 팝업으로 표시한다. True=렌더 진행, False=취소."""
    preset_data = qc_data.get("preset_data", {})
    shot_name = ""
    write_file = qc_data.get("write_file", "")
    m = re.search(r"([A-Z]\d{3}_[A-Z]\d{3}_\d{4})", write_file, re.IGNORECASE)
    if m:
        shot_name = m.group(1)

    lines = []

    def _add(label, current, expected=None, ok_if_none=False):
        st, lbl, cur, note = _qc_status_line(label, current, expected, ok_if_none)
        icon = {"ok": "OK", "warn": "!!", "error": "XX"}[st]
        note_str = f"  ({note})" if note else ""
        lines.append((st, f"[{icon}]  {lbl:<22} {cur}{note_str}"))

    # FPS
    _add(
        "FPS", qc_data.get("fps"),
        expected=preset_data.get("fps") if preset_data else None,
    )

    # 해상도
    w = qc_data.get("width", "?")
    h = qc_data.get("height", "?")
    cur_res = f"{w}x{h}"
    if preset_data:
        exp_res = f"{preset_data.get('plate_width', '?')}x{preset_data.get('plate_height', '?')}"
        _add("해상도", cur_res, expected=exp_res)
    else:
        _add("해상도", cur_res)

    # OCIO 경로
    ocio = qc_data.get("ocio_path", "")
    if ocio:
        ocio_exists = os.path.exists(ocio)
        if preset_data and preset_data.get("ocio_path"):
            _add("OCIO 경로", ocio, expected=preset_data.get("ocio_path"))
        else:
            st = "ok" if ocio_exists else "warn"
            icon = "OK" if ocio_exists else "!!"
            note = "" if ocio_exists else "  (경로 없음!)"
            lines.append((st, f"[{icon}]  {'OCIO 경로':<22} {ocio}{note}"))
    else:
        lines.append(("warn", "[!!]  OCIO 경로           (설정 없음)"))

    # Write colorspace
    _add(
        "Write 컬러스페이스", qc_data.get("write_colorspace"),
        expected=preset_data.get("write_out_colorspace") if preset_data else None,
    )

    # Write 파일 타입
    _add("Write 파일 포맷", qc_data.get("write_file_type"))

    # 플레이트 colorspace
    if qc_data.get("plate_colorspace") is not None:
        _add(
            "플레이트 컬러스페이스", qc_data.get("plate_colorspace"),
            expected=preset_data.get("read_input_transform") if preset_data else None,
        )
    else:
        lines.append(("warn", "[!!]  플레이트 컬러스페이스  (플레이트 Read 감지 안됨)"))

    # 프레임 수 비교
    plate_f = qc_data.get("plate_frames")
    edit_f = qc_data.get("edit_frames")
    if plate_f is not None and edit_f is not None:
        match = plate_f == edit_f
        icon = "OK" if match else "!!"
        note = "일치" if match else f"  <- 불일치! (편집본 {edit_f}f)"
        lines.append(
            ("ok" if match else "warn",
             f"[{icon}]  {'플레이트 길이':<22} {plate_f}f{note}")
        )
    elif plate_f is not None:
        lines.append(("ok", f"[OK]  {'플레이트 길이':<22} {plate_f}f"))
    else:
        lines.append(("warn", "[!!]  플레이트 길이         (Read 감지 안됨)"))

    if edit_f is not None and plate_f is None:
        lines.append(("ok", f"[OK]  {'편집본 길이':<22} {edit_f}f"))

    # 요약 판정
    has_warn = any(st in ("warn", "error") for st, _ in lines)
    separator = "-" * 52

    title_shot = f"  {shot_name}" if shot_name else ""
    header = f"BPE QC Checker{title_shot}\n{separator}\n"
    body_text = "\n".join(txt for _, txt in lines)
    footer = (
        f"\n{separator}\n"
        + (
            "!!  불일치 항목이 있습니다. 그대로 렌더하시겠습니까?" if has_warn
            else "OK  모든 항목이 프리셋과 일치합니다."
        )
    )

    full_text = header + body_text + footer
    return _show_qc_panel_modal(full_text)


def _show_qc_panel_modal(full_text: str) -> bool:
    """PythonPanel을 띄워 True(OK) / False(Cancel)를 반환한다."""
    panel = nukescripts.PythonPanel(
        "BPE QC Checker",
        "com.beluca.bpe.qc_checker",
    )
    try:
        panel.setMinimumSize(960, 780)
    except Exception:
        pass

    spacer_knob = nuke.Text_Knob("_spacer", "", " " * 118)
    panel.addKnob(spacer_knob)

    text_knob = nuke.Multiline_Eval_String_Knob("report", "", full_text)
    text_knob.setFlag(nuke.NO_ANIMATION)
    try:
        if hasattr(text_knob, "setHeight"):
            text_knob.setHeight(520)
    except Exception:
        pass
    panel.addKnob(text_knob)

    hint_knob = nuke.Text_Knob(
        "_hint", "", "<b>OK</b> -> 렌더 진행   /   <b>Cancel</b> -> 취소",
    )
    panel.addKnob(hint_knob)

    return bool(panel.showModalDialog())


def bpe_qc_before_render():
    """nuke.addBeforeRender 에 등록되는 콜백.

    execute 컨텍스트 안에서 QC 데이터를 수집한 뒤 RuntimeError로 렌더를 중단,
    nuke.executeDeferred 로 idle 상태에서 QC 다이얼로그를 표시한다.
    OK면 _bpe_qc_approved에 노드 이름을 추가하고 nuke.execute 재호출.
    """
    write = nuke.thisNode()
    write_name = write.name()

    # QC 승인 후 재실행된 렌더 — 통과
    if write_name in _bpe_qc_approved:
        _bpe_qc_approved.discard(write_name)
        return

    try:
        qc_data = collect_qc_data(write)
    except Exception as e:
        nuke.tprint(f"[BPE QC Checker] QC 데이터 수집 오류 (렌더 계속): {e}")
        return

    try:
        first = int(write["first"].value())
        last = int(write["last"].value())
    except Exception:
        try:
            first = int(nuke.root().firstFrame())
            last = int(nuke.root().lastFrame())
        except Exception:
            first, last = 1, 1

    def _deferred_qc_and_render():
        try:
            proceed = _show_qc_dialog(qc_data)
        except Exception as e:
            nuke.tprint(f"[BPE QC Checker] 다이얼로그 오류: {e}")
            return

        if not proceed:
            nuke.tprint("[BPE QC Checker] 사용자가 렌더를 취소했습니다.")
            return

        w = nuke.toNode(write_name)
        if w is None:
            nuke.tprint(f"[BPE QC Checker] Write 노드 '{write_name}'를 찾을 수 없습니다.")
            return

        _bpe_qc_approved.add(write_name)
        try:
            nuke.execute(w, first, last, 1)
        except Exception as e:
            _bpe_qc_approved.discard(write_name)
            nuke.tprint(f"[BPE QC Checker] 렌더 실행 오류: {e}")

    nuke.executeDeferred(_deferred_qc_and_render)
    raise RuntimeError(
        "[BPE] QC Checker 다이얼로그를 표시합니다. 확인 후 렌더가 재시작됩니다."
    )


# ══════════════════════════════════════════════════════════════════════
# POST-RENDER VIEWER
# ══════════════════════════════════════════════════════════════════════

def _bpe_output_media_kind(out_path: str, write) -> str:
    """렌더 출력이 EXR 시퀀스 / 무비 / 기타인지 추정한다."""
    p = (out_path or "").lower().replace("\\", "/")
    ft = _knob_value_safe(write, "file_type", "fileType", "file_format").lower()
    if "exr" in ft or p.endswith(".exr") or ".exr" in p:
        return "exr"
    if any(ext in p for ext in (".mov", ".mp4", ".mxf", ".avi", ".mkv")):
        return "movie"
    if any(x in ft for x in ("mov", "mp4", "prores", "h264", "dnx", "mpeg")):
        return "movie"
    return "other"


def _bpe_safe_set_read_enum(read, knob_names: tuple, preferred_values: list) -> bool:
    """Read 노드 enum 계열 knob에 대해 knob.values()에 실제로 있는 값만 setValue."""
    preferred_values = [str(v).strip() for v in preferred_values if str(v).strip()]
    seen: set = set()
    prefs = []
    for v in preferred_values:
        if v not in seen:
            seen.add(v)
            prefs.append(v)

    for kname in knob_names:
        k = read.knob(kname)
        if k is None:
            continue
        vals = []
        try:
            if hasattr(k, "values"):
                vals = list(k.values())
        except Exception:
            vals = []
        if not vals:
            for pref in prefs:
                try:
                    k.setValue(pref)
                    return True
                except Exception:
                    continue
            continue
        for pref in prefs:
            if pref in vals:
                try:
                    k.setValue(pref)
                    return True
                except Exception:
                    continue
            pl = pref.lower()
            for v in vals:
                try:
                    if str(v).strip().lower() == pl:
                        k.setValue(v)
                        return True
                except Exception:
                    continue
            for v in vals:
                try:
                    vs = str(v).lower()
                    if pl and (pl in vs or vs in pl):
                        k.setValue(v)
                        return True
                except Exception:
                    continue
    return False


def _bpe_plate_colorspace_from_write(write) -> str:
    """Write 업스트림에서 플레이트 Read를 찾아 그 colorspace 문자열을 반환한다."""
    try:
        all_reads = _find_upstream_reads(write)
    except Exception:
        return ""
    plate_reads = [
        r for r in all_reads
        if any(k in _knob_value_safe(r, "file").lower() for k in ("plate", "/org/", "\\org\\"))
    ]
    if not plate_reads:
        return ""
    return _knob_value_safe(
        plate_reads[0], "colorspace", "colorSpace", "OCIO_colorspace", "ocio_colorspace",
    )


def _bpe_configure_read_from_write(
    read, write, out_file: str, plate_colorspace: str = "",
) -> None:
    """Write 출력 형식에 맞춰 Read의 file_type/colorspace를 설정한다."""
    kind = _bpe_output_media_kind(out_file, write)
    p = out_file.lower()

    # file_type
    if kind == "exr":
        _bpe_safe_set_read_enum(read, ("file_type", "fileType"), ["exr", "openexr", "EXR", "OpenEXR"])
    elif kind == "movie":
        if ".mp4" in p:
            _bpe_safe_set_read_enum(read, ("file_type", "fileType"), ["mp4", "mpeg4", "MP4"])
        else:
            _bpe_safe_set_read_enum(
                read, ("file_type", "fileType"), ["mov", "quicktime", "MOV", "mp4"],
            )

    # colorspace
    plate_cs = (plate_colorspace or "").strip()
    w_ocio = _knob_value_safe(write, "ocioColorspace", "OCIO_colorspace", "ocio_colorspace")
    w_cs = _knob_value_safe(write, "colorspace", "colorSpace")
    tt = _knob_value_safe(
        write, "colorspace_transform", "transform_type", "transformType",
    ).lower()

    candidates = []
    if plate_cs:
        candidates.append(plate_cs)
    if w_ocio and w_ocio not in candidates:
        candidates.append(w_ocio)
    if w_cs and w_cs not in candidates:
        candidates.append(w_cs)

    if kind == "exr":
        candidates.extend(
            ["default", "scene_linear", "compositing_linear", "linear", "data", "raw"],
        )
    else:
        candidates.extend(
            ["default", "Output - Rec.709", "Output - sRGB", "sRGB", "rec709", "scene_linear"],
        )

    if "display" in tt or "view" in tt:
        extra = [
            plate_cs, w_ocio, w_cs,
            "default", "Output - Rec.709", "sRGB", "rec709",
            "scene_linear", "compositing_linear",
        ]
        seen_cs: set = set()
        candidates = [c for c in extra if c and (c not in seen_cs and not seen_cs.add(c))]  # type: ignore[func-returns-value]

    ok = _bpe_safe_set_read_enum(
        read,
        ("colorspace", "colorSpace", "OCIO_colorspace", "ocio_colorspace"),
        candidates,
    )
    if not ok:
        nuke.tprint(
            "[BPE Post-Render Viewer] Read colorspace: "
            "플레이트/Write 값이 Read 목록에 없어 Nuke 기본값 유지"
        )


def _bpe_read_reload_safe(read) -> None:
    try:
        rk = read.knob("reload")
        if rk is not None:
            rk.execute()
    except Exception:
        pass


def _bpe_set_read_frame_range_values(read, first: int, last: int) -> None:
    """first/last 값을 직접 받아 Read 노드에 설정한다."""
    for knob_name, val in (("first", first), ("last", last)):
        try:
            k = read.knob(knob_name)
            if k is not None:
                k.setValue(val)
        except Exception:
            pass
    for knob_name, val in (("origfirst", first), ("origlast", last)):
        k = read.knob(knob_name)
        if k is not None:
            try:
                k.setValue(val)
            except Exception:
                pass


def _bpe_set_read_frame_range(read, write) -> None:
    try:
        first = int(write["first"].value())
        last = int(write["last"].value())
    except Exception:
        return
    _bpe_set_read_frame_range_values(read, first, last)


def _bpe_connect_read_to_viewer(read_node) -> None:
    """Read 노드를 Viewer의 입력 0번에 연결한다."""
    try:
        viewer = next((n for n in nuke.allNodes("Viewer")), None)
        if viewer:
            viewer.setInput(0, read_node)
            nuke.tprint(f"[BPE Post-Render Viewer] Viewer -> {read_node.name()}")
    except Exception as e:
        nuke.tprint(f"[BPE Post-Render Viewer] Viewer 연결 실패: {e}")


def _bpe_defer_connect_viewer(read_name: str) -> None:
    """AfterRender 직후 Viewer 연결이 충돌할 수 있어 한 틱 미룬다."""

    def _go():
        n = nuke.toNode(read_name)
        if n:
            _bpe_connect_read_to_viewer(n)

    try:
        nuke.executeDeferred(_go)
    except Exception:
        _go()


def bpe_post_render_load():
    """nuke.addAfterRender 에 등록되는 콜백.

    렌더 완료 후 출력 시퀀스를 Read 노드로 자동 생성/갱신하고 Viewer에 연결한다.
    execute 컨텍스트 안에서는 읽기 전용만, 노드 생성은 executeDeferred로 미룬다.
    """
    try:
        write = nuke.thisNode()
        out_file = _knob_value_safe(write, "file")
        if not out_file:
            nuke.tprint(
                "[BPE Post-Render Viewer] Write 파일 경로가 비어 있어 Read 생성을 건너뜁니다."
            )
            return

        write_name = write.name()
        plate_cs = _bpe_plate_colorspace_from_write(write)
        wx = write.xpos()
        wy = write.ypos()
        try:
            write_first = int(write["first"].value())
            write_last = int(write["last"].value())
        except Exception:
            write_first = None
            write_last = None

        def _deferred(
            _wname=write_name, _out=out_file, _pcs=plate_cs,
            _wx=wx, _wy=wy, _wf=write_first, _wl=write_last,
        ):
            try:
                w = nuke.toNode(_wname)
                read_name = "bpe_render_preview"
                existing = nuke.toNode(read_name)

                if existing and existing.Class() == "Read":
                    try:
                        existing["file"].setValue(_out)
                    except Exception as e:
                        nuke.tprint(f"[BPE Post-Render Viewer] 기존 Read 경로 설정 실패: {e}")
                        return
                    if w is not None:
                        if _wf is not None and _wl is not None:
                            _bpe_set_read_frame_range_values(existing, _wf, _wl)
                        _bpe_configure_read_from_write(existing, w, _out, _pcs)
                    _bpe_read_reload_safe(existing)
                    nuke.tprint(f"[BPE Post-Render Viewer] 기존 '{read_name}' 갱신: {_out}")
                    _bpe_connect_read_to_viewer(existing)
                    return

                try:
                    read = nuke.nodes.Read(file=_out, xpos=_wx + 160, ypos=_wy)
                except Exception as e:
                    nuke.tprint(f"[BPE Post-Render Viewer] Read 노드 생성 실패: {e}")
                    return

                try:
                    read.setName(read_name, uncollide=True)
                except Exception:
                    try:
                        read["name"].setValue(read_name)
                    except Exception:
                        pass

                if w is not None:
                    if _wf is not None and _wl is not None:
                        _bpe_set_read_frame_range_values(read, _wf, _wl)
                    _bpe_configure_read_from_write(read, w, _out, _pcs)
                _bpe_read_reload_safe(read)
                nuke.tprint(f"[BPE Post-Render Viewer] Read '{read.name()}' 생성: {_out}")
                _bpe_connect_read_to_viewer(read)

            except Exception as e:
                nuke.tprint(f"[BPE Post-Render Viewer] deferred 오류: {e}")

        nuke.executeDeferred(_deferred)

    except Exception as e:
        nuke.tprint(f"[BPE Post-Render Viewer] 오류: {e}")


# ══════════════════════════════════════════════════════════════════════
# TOOL HOOKS 관리
# ══════════════════════════════════════════════════════════════════════

def reload_tool_hooks() -> None:
    """settings.json의 tools 섹션을 읽어 BeforeRender/AfterRender 훅을 등록/해제한다."""
    try:
        tools_cfg = get_tools_settings()
    except Exception as e:
        nuke.tprint(f"[BPE Tools] settings 로드 실패: {e}")
        return

    # QC Checker
    qc_enabled = tools_cfg.get("qc_checker", {}).get("enabled", False)
    try:
        nuke.removeBeforeRender(bpe_qc_before_render)
    except Exception:
        pass
    if qc_enabled:
        nuke.addBeforeRender(bpe_qc_before_render)

    # Post-Render Viewer
    prv_enabled = tools_cfg.get("post_render_viewer", {}).get("enabled", False)
    try:
        nuke.removeAfterRender(bpe_post_render_load)
    except Exception:
        pass
    if prv_enabled:
        nuke.addAfterRender(bpe_post_render_load)

    nuke.tprint(
        "[BPE Tools] Reload 완료 — "
        f"QC Checker: {'ON' if qc_enabled else 'OFF'}  |  "
        f"Post-Render Viewer: {'ON' if prv_enabled else 'OFF'}  |  "
        f"settings: {cfg.SETTINGS_FILE}"
    )
