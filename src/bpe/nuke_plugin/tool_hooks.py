"""Tool Hooks — QC Checker (BeforeRender) 및 Post-Render Viewer (AfterRender)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import nuke
import nukescripts

import bpe.core.config as cfg
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import (
    normalize_path_str,
    normalize_unc_to_drive,
    renders_dir_from_nk_path_robust,
)
from bpe.core.presets import load_presets
from bpe.core.settings import get_tools_settings, get_unc_mappings

logger = get_logger("nuke_plugin.tool_hooks")

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
_bpe_qc_in_progress: set = set()
_bpe_qc_panel_open: bool = False

_SHOT_NAME_RE = re.compile(r"([A-Z]\d{2,4}_[A-Z]\d{2,4}_\d{3,5})", re.IGNORECASE)
_PROJECT_YEAR_RE = re.compile(r"project_(\d{4})", re.IGNORECASE)
_PROJECT_CODE_RE = re.compile(r"^[A-Z]{2,6}_\d{2,4}$", re.IGNORECASE)

_EXR_FPS_KEYS = (
    "input/frame_rate",
    "input/fps",
    "exr/nuke/fps",
    "exr/framesPerSecond",
    "exr/fps",
    "nuke/fps",
)
_EXR_TIMECODE_KEYS = (
    "input/timecode",
    "exr/timeCode",
    "timecode",
    "exr/timecode",
    "nuke/timecode",
)
_EXR_COLORSPACE_KEYS = (
    "input/colorspace",
    "exr/colorInteropID",
    "exr/renderingTransform",
    "exr/nuke/colorspace",
    "exr/InputColorspace",
    "nuke/colorspace",
    "exr/colorSpace",
    "exr/arri/Input Color Space",
)

_QC_SEP = "\u2500" * 54


def _qc_log_info(msg: str, *args: Any) -> None:
    """Script Editor + BPE 로그 파일에 QC 진행 상황 기록."""
    try:
        logger.info(msg, *args)
    except Exception:
        pass
    try:
        if args:
            nuke.tprint("[BPE QC] " + (msg % args))
        else:
            nuke.tprint("[BPE QC] " + msg)
    except Exception:
        pass


def _qc_log_warning(msg: str, *args: Any) -> None:
    try:
        logger.warning(msg, *args)
    except Exception:
        pass
    try:
        if args:
            nuke.tprint("[BPE QC] WARNING: " + (msg % args))
        else:
            nuke.tprint("[BPE QC] WARNING: " + msg)
    except Exception:
        pass


def _qc_log_error(msg: str, *args: Any, exc: Optional[BaseException] = None) -> None:
    try:
        if exc is not None:
            logger.exception(msg, *args)
        else:
            logger.error(msg, *args)
    except Exception:
        pass
    try:
        if args:
            nuke.tprint("[BPE QC] ERROR: " + (msg % args))
        else:
            nuke.tprint("[BPE QC] ERROR: " + msg)
        if exc is not None:
            nuke.tprint("[BPE QC] ERROR detail: %s" % exc)
    except Exception:
        pass


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


def _score_and_pick_plate_read(all_reads: list, write_node) -> Tuple[Any, int]:
    """점수 기반으로 플레이트 Read 노드를 선택한다."""
    if not all_reads:
        return None, 0

    try:
        write_first = int(write_node["first"].value())
        write_last = int(write_node["last"].value())
        write_frames = write_last - write_first + 1
    except Exception:
        write_frames = None

    scores: Dict[str, Tuple[int, Any]] = {}
    for r in all_reads:
        score = 0
        path = _knob_value_safe(r, "file").lower().replace("\\", "/")

        for kw in ("plate", "/org/", "raw", "/input/", "/src/", "originals"):
            if kw in path:
                score += 8
                break

        for kw in ("edit", "previs", "preview", "/ref/", "grade", "overlay", "lut"):
            if kw in path:
                score -= 8
                break

        ft = _knob_value_safe(r, "file_type", "fileType").lower()
        if "exr" in ft or path.endswith(".exr"):
            score += 3

        try:
            r_first = int(r["first"].value())
            r_last = int(r["last"].value())
            r_frames = r_last - r_first + 1
            if r_frames <= 1:
                score -= 10
            else:
                score += 5
                if write_frames is not None:
                    diff = abs(r_frames - write_frames)
                    if diff == 0:
                        score += 5
                    elif diff <= 10:
                        score += 2
        except Exception:
            pass

        scores[r.name()] = (score, r)

    if not scores:
        return None, 0

    best_name = max(scores, key=lambda k: scores[k][0])
    best_score, best_node = scores[best_name]
    return best_node, best_score


def _parse_fps_from_meta_value(raw: Any) -> Optional[str]:
    """EXR framesPerSecond Rational (n/d) 또는 float/str → 소수 FPS 문자열."""
    if raw is None:
        return None
    s = str(raw).strip()
    if "/" in s:
        try:
            num, den = s.split("/", 1)
            val = float(num) / float(den)
            if abs(val - 23.976) < 0.01:
                return "23.976"
            if abs(val - 29.97) < 0.01:
                return "29.97"
            if abs(val - 59.94) < 0.01:
                return "59.94"
            return f"{val:.3f}".rstrip("0").rstrip(".")
        except (ValueError, ZeroDivisionError):
            return s
    try:
        val = float(s)
        return f"{val:.3f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


def _read_plate_exr_metadata(plate_read) -> dict:
    """Nuke Read metadata knob에서 EXR 헤더 정보를 읽는다."""
    result: Dict[str, Any] = {
        "fps": None,
        "timecode": None,
        "colorspace": None,
        "all_keys": [],
        "error": None,
    }
    try:
        mk = plate_read.knob("metadata")
        if mk is None:
            result["error"] = "metadata knob 없음"
            return result

        try:
            raw = mk.value()
            if isinstance(raw, dict):
                meta = raw
            else:
                result["error"] = "metadata 타입 불명확"
                return result
        except Exception as e:
            result["error"] = "metadata.value() 실패: %s" % e
            return result

        result["all_keys"] = list(meta.keys())[:30]

        for key in _EXR_FPS_KEYS:
            if key in meta:
                result["fps"] = _parse_fps_from_meta_value(meta[key])
                break

        for key in _EXR_TIMECODE_KEYS:
            if key in meta:
                result["timecode"] = str(meta[key])
                break

        for key in _EXR_COLORSPACE_KEYS:
            if key in meta:
                result["colorspace"] = str(meta[key])
                break

    except Exception as e:
        result["error"] = str(e)
        _qc_log_warning("EXR 메타데이터 읽기 실패: %s", str(e))
    return result


def _find_plate_server_path(root_name: str) -> Tuple[Optional[str], Optional[str]]:
    """root.name에서 샷 정보를 추출해 서버 plate 경로를 파생한다."""
    if not root_name:
        return None, "root.name이 비어 있습니다"

    norm = root_name.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]

    basename = parts[-1] if parts else ""
    stem = os.path.splitext(basename)[0]
    shot_m = _SHOT_NAME_RE.search(stem)
    if not shot_m:
        shot_m = _SHOT_NAME_RE.search(norm)
    if not shot_m:
        return None, "샷 이름 패턴을 찾을 수 없습니다 (파일명: %s)" % basename
    shot_name = shot_m.group(1).upper()

    project_code = None
    for part in parts:
        if _PROJECT_CODE_RE.match(part):
            project_code = part.upper()
            break
    if not project_code:
        return None, "경로에서 프로젝트 코드를 찾을 수 없습니다"

    server_root = None
    for i, part in enumerate(parts):
        if _PROJECT_YEAR_RE.match(part):
            if len(parts[0]) == 2 and parts[0][1] == ":":
                server_root = parts[0] + "/" + "/".join(parts[1 : i + 1])
            else:
                server_root = "/".join(parts[: i + 1])
            break
    if not server_root:
        return None, "서버 루트(project_YYYY)를 경로에서 찾을 수 없습니다"

    try:
        from bpe.core.shot_builder import build_shot_paths

        paths = build_shot_paths(server_root, project_code, shot_name)
    except Exception as e:
        _qc_log_warning("build_shot_paths 실패 shot=%s project=%s: %s", shot_name, project_code, e)
        return None, "build_shot_paths 실패: %s" % e

    if not paths:
        return None, "샷 경로 없음 (shot=%s, project=%s)" % (shot_name, project_code)

    plate_org = paths["shot_root"] / "plate" / "org"
    try:
        if not plate_org.is_dir():
            return None, "plate/org 폴더 없음: %s" % normalize_path_str(str(plate_org))
    except OSError as e:
        return None, "plate/org 접근 오류: %s" % e

    try:
        ver_dirs = sorted(
            [
                d
                for d in plate_org.iterdir()
                if d.is_dir() and re.match(r"^v\d+$", d.name, re.IGNORECASE)
            ],
            key=lambda d: int(d.name[1:]),
            reverse=True,
        )
    except OSError as e:
        return None, "버전 폴더 탐색 실패: %s" % e

    if not ver_dirs:
        return None, "plate/org 아래 버전 폴더 없음: %s" % normalize_path_str(str(plate_org))

    latest = ver_dirs[0]
    for sub in ("hi", "mov"):
        sub_dir = latest / sub
        try:
            if sub_dir.is_dir():
                return normalize_path_str(str(sub_dir)), None
        except OSError:
            continue

    return normalize_path_str(str(latest)), None


def collect_qc_data(write_node) -> dict:
    """렌더 대상 Write 노드에서 QC 3카테고리 데이터를 수집한다."""
    root = nuke.root()
    data: Dict[str, Any] = {}

    data["write_name"] = write_node.name()
    data["write_file"] = _knob_value_safe(write_node, "file")

    m_shot = _SHOT_NAME_RE.search(data["write_file"])
    data["shot_name"] = m_shot.group(1).upper() if m_shot else ""

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
        data["width"] = data["height"] = data["format_name"] = "?"

    data["write_colorspace"] = _knob_value_safe(
        write_node, "ocioColorspace", "colorspace", "colorSpace"
    )
    data["write_file_type"] = _knob_value_safe(write_node, "file_type", "fileType", "file_format")

    try:
        data["write_first"] = int(write_node["first"].value())
        data["write_last"] = int(write_node["last"].value())
    except Exception:
        data["write_first"] = data["write_last"] = None

    data["mov_write_name"] = None
    data["mov_fps"] = None
    for wn in nuke.allNodes("Write"):
        if wn.name() == data["write_name"]:
            continue
        ft = _knob_value_safe(wn, "file_type", "fileType").lower()
        if "mov" in ft or "mp4" in ft:
            data["mov_write_name"] = wn.name()
            data["mov_fps"] = _knob_value_safe(wn, "fps")
            break

    data["ocio_path"] = _knob_value_safe(
        root, "customOCIOConfigPath", "OCIO_config", "ocioConfigPath"
    )

    all_reads = _find_upstream_reads(write_node)
    plate_read, plate_score = _score_and_pick_plate_read(all_reads, write_node)

    data["plate_read_name"] = plate_read.name() if plate_read else None
    data["plate_score"] = plate_score

    if plate_read:
        data["plate_file"] = _knob_value_safe(plate_read, "file")
        data["plate_colorspace"] = _knob_value_safe(plate_read, "colorspace", "colorSpace")
        try:
            data["plate_first"] = int(plate_read["first"].value())
            data["plate_last"] = int(plate_read["last"].value())
            data["plate_frames"] = data["plate_last"] - data["plate_first"] + 1
        except Exception:
            data["plate_first"] = data["plate_last"] = data["plate_frames"] = None
    else:
        data["plate_file"] = data["plate_colorspace"] = None
        data["plate_first"] = data["plate_last"] = data["plate_frames"] = None

    try:
        root_name = nuke.root()["name"].value()
    except Exception:
        root_name = ""
    plate_server, plate_server_err = _find_plate_server_path(root_name)
    data["plate_server_path"] = plate_server
    data["plate_server_error"] = plate_server_err

    if plate_read:
        meta = _read_plate_exr_metadata(plate_read)
        data["meta_fps"] = meta.get("fps")
        data["meta_timecode"] = meta.get("timecode")
        data["meta_colorspace"] = meta.get("colorspace")
        data["meta_all_keys"] = meta.get("all_keys", [])
        data["meta_error"] = meta.get("error")
        if meta.get("all_keys"):
            _qc_log_info(
                "EXR metadata keys (sample): %s",
                ", ".join(meta.get("all_keys", [])[:8]),
            )
    else:
        data["meta_fps"] = data["meta_timecode"] = data["meta_colorspace"] = None
        data["meta_all_keys"] = []
        data["meta_error"] = "플레이트 Read 노드 감지 실패"

    preset_name, preset_data = _guess_preset_from_script()
    data["preset_name"] = preset_name
    data["preset_data"] = preset_data or {}

    _qc_log_info(
        "QC 데이터 수집 완료 write=%s shot=%s preset=%s plate=%s score=%s",
        data["write_name"],
        data.get("shot_name") or "?",
        preset_name or "(없음)",
        data.get("plate_read_name") or "(없음)",
        plate_score,
    )
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
    """3카테고리 QC 리포트를 PythonPanel 텍스트로 표시. True=렌더 진행, False=취소."""
    preset_data = qc_data.get("preset_data", {})
    shot_name = qc_data.get("shot_name", "")

    lines: List[Tuple[str, str]] = []

    def _h(title: str) -> None:
        lines.append(("info", "\n[%s]" % title))
        lines.append(("info", _QC_SEP))

    def _add(label, current, expected=None, ok_if_none=False, note_extra=""):
        st, lbl, cur, note = _qc_status_line(label, current, expected, ok_if_none)
        note_str = "  (%s)" % note if note else ""
        if note_extra:
            note_str += "  %s" % note_extra
        icon = {"ok": "OK", "warn": "!!", "error": "XX"}[st]
        lines.append((st, "[%s]  %-26s %s%s" % (icon, lbl, cur, note_str)))

    _h("A  납품 규약  Delivery Compliance")

    _add(
        "FPS",
        qc_data.get("fps"),
        expected=preset_data.get("fps") if preset_data else None,
    )

    w, h = qc_data.get("width", "?"), qc_data.get("height", "?")
    cur_res = "%sx%s" % (w, h)
    if preset_data:
        exp_res = "%sx%s" % (
            preset_data.get("plate_width", "?"),
            preset_data.get("plate_height", "?"),
        )
        _add("해상도", cur_res, expected=exp_res)
    else:
        _add("해상도", cur_res)

    _add(
        "Write 컬러스페이스",
        qc_data.get("write_colorspace"),
        expected=preset_data.get("write_out_colorspace") if preset_data else None,
    )

    _add(
        "출력 포맷",
        qc_data.get("write_file_type"),
        expected=preset_data.get("delivery_format") if preset_data else None,
    )

    wf = qc_data.get("write_first")
    wl = qc_data.get("write_last")
    try:
        root_first = int(nuke.root().firstFrame())
        root_last = int(nuke.root().lastFrame())
    except Exception:
        root_first = root_last = None
    if wf is not None and wl is not None:
        range_str = "%s ~ %s  (%df)" % (wf, wl, wl - wf + 1)
        if root_first is not None:
            if wf == root_first and wl == root_last:
                lines.append(("ok", "[OK]  %-26s %s" % ("프레임 범위", range_str)))
            else:
                lines.append(
                    (
                        "warn",
                        "[!!]  %-26s %s  (Root: %s~%s)"
                        % ("프레임 범위", range_str, root_first, root_last),
                    )
                )
        else:
            lines.append(("ok", "[OK]  %-26s %s" % ("프레임 범위", range_str)))
    else:
        lines.append(("warn", "[!!]  %-26s (감지 안됨)" % "프레임 범위"))

    mov_fps = qc_data.get("mov_fps")
    if mov_fps:
        _add(
            "MOV FPS (%s)" % qc_data.get("mov_write_name", "?"),
            mov_fps,
            expected=preset_data.get("mov_fps") if preset_data else None,
        )

    _h("B  작업 설정  Work Setup")

    ocio = qc_data.get("ocio_path", "")
    if ocio:
        ocio_ok = os.path.exists(ocio)
        exp_ocio = preset_data.get("ocio_path") if preset_data else None
        if exp_ocio:
            _add("OCIO 경로", ocio, expected=exp_ocio)
        else:
            icon = "OK" if ocio_ok else "!!"
            st = "ok" if ocio_ok else "warn"
            note = "" if ocio_ok else "  (파일 없음!)"
            lines.append((st, "[%s]  %-26s %s%s" % (icon, "OCIO 경로", ocio, note)))
    else:
        lines.append(("warn", "[!!]  %-26s (설정 없음)" % "OCIO 경로"))

    plate_score = qc_data.get("plate_score", 0)
    plate_name = qc_data.get("plate_read_name")
    if plate_name:
        lines.append(
            (
                "ok",
                "[OK]  %-26s %s  (감지 신뢰도: %d점)" % ("플레이트 Read", plate_name, plate_score),
            )
        )
    else:
        lines.append(("warn", "[!!]  %-26s (감지 실패)" % "플레이트 Read"))

    if qc_data.get("plate_colorspace") is not None:
        _add(
            "플레이트 컬러스페이스",
            qc_data.get("plate_colorspace"),
            expected=preset_data.get("read_input_transform") if preset_data else None,
        )
    else:
        lines.append(("warn", "[!!]  %-26s (감지 안됨)" % "플레이트 컬러스페이스"))

    plate_file = qc_data.get("plate_file", "")
    if plate_file:
        check_path = re.sub(
            r"%\d*d",
            str(qc_data.get("plate_first", 0) or 0).zfill(4),
            plate_file,
        )
        check_path = re.sub(
            r"#+",
            str(qc_data.get("plate_first", 0) or 0).zfill(4),
            check_path,
        )
        exists = os.path.exists(check_path)
        icon = "OK" if exists else "!!"
        st = "ok" if exists else "warn"
        short = normalize_path_str(plate_file)[-50:]
        lines.append((st, "[%s]  %-26s ...%s" % (icon, "플레이트 파일", short)))
    else:
        lines.append(("warn", "[!!]  %-26s (경로 없음)" % "플레이트 파일"))

    srv_path = qc_data.get("plate_server_path")
    srv_err = qc_data.get("plate_server_error")
    if srv_path:
        loaded_norm = normalize_path_str(plate_file or "").lower().replace("\\", "/")
        server_norm = normalize_path_str(srv_path).lower().replace("\\", "/")
        if server_norm and server_norm in loaded_norm:
            lines.append(("ok", "[OK]  %-26s 일치 (%s)" % ("서버 플레이트 경로", srv_path[-40:])))
        else:
            lines.append(
                (
                    "warn",
                    "[!!]  %-26s 불일치!\n      서버: %s\n      로드: %s"
                    % ("서버 플레이트 경로", srv_path, plate_file or "(없음)"),
                )
            )
    else:
        lines.append(("warn", "[!!]  %-26s %s" % ("서버 플레이트 경로", srv_err or "(확인 불가)")))

    plate_f = qc_data.get("plate_frames")
    write_frames_count = None
    if qc_data.get("write_first") is not None and qc_data.get("write_last") is not None:
        write_frames_count = qc_data["write_last"] - qc_data["write_first"] + 1
    if plate_f is not None and write_frames_count is not None:
        match = plate_f == write_frames_count
        icon = "OK" if match else "!!"
        note = "일치" if match else "  <- 불일치! (Write %df)" % write_frames_count
        lines.append(
            (
                "ok" if match else "warn",
                "[%s]  %-26s %df  %s" % (icon, "플레이트 프레임 수", plate_f, note),
            )
        )
    elif plate_f is not None:
        lines.append(("ok", "[OK]  %-26s %df" % ("플레이트 프레임 수", plate_f)))
    else:
        lines.append(("warn", "[!!]  %-26s (감지 안됨)" % "플레이트 프레임 수"))

    _h("C  EXR 메타데이터  Plate Raw Metadata")

    meta_err = qc_data.get("meta_error")
    if meta_err and not qc_data.get("meta_fps") and not qc_data.get("meta_timecode"):
        lines.append(("warn", "[!!]  메타데이터                    (%s)" % meta_err))
    else:
        m_fps = qc_data.get("meta_fps")
        r_fps = qc_data.get("fps")
        if m_fps:
            try:
                match_fps = abs(float(m_fps) - float(r_fps)) < 0.01
                icon = "OK" if match_fps else "!!"
                note = "Root FPS 일치" if match_fps else "Root FPS %s 불일치!" % r_fps
                lines.append(
                    (
                        "ok" if match_fps else "warn",
                        "[%s]  %-26s %s  (%s)" % (icon, "EXR FPS (원본)", m_fps, note),
                    )
                )
            except (ValueError, TypeError):
                lines.append(("ok", "[OK]  %-26s %s" % ("EXR FPS (원본)", m_fps)))
        else:
            lines.append(("warn", "[!!]  %-26s (메타 없음)" % "EXR FPS (원본)"))

        m_tc = qc_data.get("meta_timecode")
        if m_tc:
            lines.append(("ok", "[OK]  %-26s %s" % ("타임코드", m_tc)))
        else:
            lines.append(("warn", "[!!]  %-26s (메타 없음)" % "타임코드"))

        m_cs = qc_data.get("meta_colorspace")
        if m_cs:
            _add(
                "EXR 컬러스페이스 (원본)",
                m_cs,
                expected=preset_data.get("read_input_transform") if preset_data else None,
            )
        else:
            lines.append(("warn", "[!!]  %-26s (메타 없음)" % "EXR 컬러스페이스 (원본)"))

    has_warn = any(st in ("warn", "error") for st, _ in lines if st != "info")
    warn_count = sum(1 for st, _ in lines if st == "warn")

    title_shot = "  —  %s" % shot_name if shot_name else ""
    preset_info = (
        "  [프리셋: %s]" % qc_data["preset_name"]
        if qc_data.get("preset_name")
        else "  [프리셋 없음 — 비교 항목 제한]"
    )

    header = "BPE QC Checker%s\n%s\n%s\n" % (title_shot, preset_info, _QC_SEP)
    body = "\n".join(txt for _, txt in lines)
    footer_text = (
        "!! 경고 %d개 항목이 있습니다. 그대로 렌더하시겠습니까?" % warn_count
        if has_warn
        else "OK  모든 항목이 통과했습니다."
    )
    footer = "\n%s\n%s" % (_QC_SEP, footer_text)
    full_text = header + body + footer

    proceed = _show_qc_panel_modal(full_text)
    _qc_log_info(
        "QC 리포트 결과 write=%s proceed=%s warns=%d",
        qc_data.get("write_name"),
        proceed,
        warn_count,
    )
    return proceed


def _show_qc_panel_modal(full_text: str) -> bool:
    """PythonPanel 텍스트 리포트. True=렌더 진행, False=취소."""
    global _bpe_qc_panel_open
    if _bpe_qc_panel_open:
        _qc_log_warning("QC 다이얼로그가 이미 열려 있어 중복 표시를 건너뜁니다")
        return False
    _bpe_qc_panel_open = True
    try:
        panel = nukescripts.PythonPanel(
            "BPE QC Checker",
            "com.beluca.bpe.qc_checker",
        )
        try:
            panel.setMinimumSize(1000, 820)
        except Exception:
            pass

        spacer = nuke.Text_Knob("_spacer", "", " " * 124)
        panel.addKnob(spacer)

        text_knob = nuke.Multiline_Eval_String_Knob("report", "", full_text)
        text_knob.setFlag(nuke.NO_ANIMATION)
        try:
            if hasattr(text_knob, "setHeight"):
                text_knob.setHeight(580)
        except Exception:
            pass
        panel.addKnob(text_knob)

        hint = nuke.Text_Knob(
            "_hint",
            "",
            "<b>OK</b> → 렌더 진행   /   <b>Cancel</b> → 취소 (수정 후 재렌더)",
        )
        panel.addKnob(hint)

        return bool(panel.showModalDialog())
    except Exception as e:
        _qc_log_error("QC 패널 표시 실패", exc=e)
        return False
    finally:
        _bpe_qc_panel_open = False


def _execute_write_safe(write_name: str, first: int, last: int) -> None:
    """QC 승인 후 Write 노드를 안전하게 실행한다."""
    w = nuke.toNode(write_name)
    if w is None:
        _qc_log_error("Write 노드 '%s'를 찾을 수 없습니다", write_name)
        return
    try:
        _qc_log_info("렌더 재시작 write=%s frames=%s-%s", write_name, first, last)
        nuke.execute(w, first, last, 1)
    except Exception as e:
        _bpe_qc_approved.discard(write_name)
        _qc_log_error("렌더 실행 오류 write=%s", write_name, exc=e)


def bpe_qc_before_render():
    """nuke.addBeforeRender — QC 확인 후 렌더 진행 또는 취소."""
    write = nuke.thisNode()
    write_name = write.name()

    if write_name in _bpe_qc_approved:
        _bpe_qc_approved.discard(write_name)
        _qc_log_info("QC 승인 통과 write=%s", write_name)
        return

    if write_name in _bpe_qc_in_progress:
        _qc_log_info("QC 다이얼로그 진행 중 — 중복 beforeRender 무시 write=%s", write_name)
        return

    try:
        qc_data = collect_qc_data(write)
    except Exception as e:
        _qc_log_error("QC 데이터 수집 오류 (렌더 계속)", exc=e)
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

    _bpe_qc_in_progress.add(write_name)
    _qc_log_info("beforeRender QC 시작 write=%s", write_name)

    def _outer():
        def _inner():
            _bpe_qc_in_progress.discard(write_name)
            try:
                want_qc = nuke.ask(
                    "BPE QC Checker  —  %s\n\n"
                    "렌더 전 QC 체크를 실행하시겠습니까?\n\n"
                    "  OK     → QC 체크 후 결과 확인\n"
                    "  Cancel → 체크 건너뛰고 바로 렌더" % write_name
                )
            except Exception as e:
                _qc_log_warning("QC 확인 다이얼로그 실패: %s", e)
                want_qc = False

            w = nuke.toNode(write_name)
            if w is None:
                _qc_log_error("Write 노드 '%s' 없음", write_name)
                return

            if not want_qc:
                _qc_log_info("QC 건너뛰기 — 바로 렌더 write=%s", write_name)
                _bpe_qc_approved.add(write_name)
                nuke.executeDeferred(lambda: _execute_write_safe(write_name, first, last))
                return

            try:
                proceed = _show_qc_dialog(qc_data)
            except Exception as e:
                _qc_log_error("QC 리포트 다이얼로그 오류", exc=e)
                return

            if proceed:
                _bpe_qc_approved.add(write_name)
                nuke.executeDeferred(lambda: _execute_write_safe(write_name, first, last))
            else:
                _qc_log_info("사용자가 렌더 취소 — 수정 후 재렌더 write=%s", write_name)

        nuke.executeDeferred(_inner)

    nuke.executeDeferred(_outer)
    raise RuntimeError("[BPE QC] 체크 다이얼로그를 표시합니다. 확인 후 렌더가 재시작됩니다.")


def run_qc_now() -> None:
    """setup_pro 메뉴 '지금 QC 체크' — 선택 Write 또는 목록에서 선택."""
    writes = [n for n in nuke.selectedNodes() if n.Class() == "Write"]
    if not writes:
        writes = nuke.allNodes("Write")
    if not writes:
        nuke.message("[BPE QC] 스크립트에 Write 노드가 없습니다.")
        return

    if len(writes) == 1:
        target = writes[0]
    else:
        names = [w.name() for w in writes]
        p = nukescripts.PythonPanel("QC 대상 Write 선택", "com.beluca.bpe.qc_select")
        e = nuke.Enumeration_Knob("write_sel", "Write 노드", names)
        p.addKnob(e)
        if not p.showModalDialog():
            return
        sel_name = e.value()
        target = nuke.toNode(sel_name)
        if target is None:
            return

    _qc_log_info("수동 QC 실행 write=%s", target.name())
    try:
        qc_data = collect_qc_data(target)
    except Exception as e:
        _qc_log_error("수동 QC 데이터 수집 오류", exc=e)
        nuke.message("[BPE QC] 데이터 수집 오류:\n%s" % e)
        return

    try:
        _show_qc_dialog(qc_data)
    except Exception as e:
        _qc_log_error("수동 QC 리포트 표시 오류", exc=e)


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
        r
        for r in all_reads
        if any(k in _knob_value_safe(r, "file").lower() for k in ("plate", "/org/", "\\org\\"))
    ]
    if not plate_reads:
        return ""
    return _knob_value_safe(
        plate_reads[0],
        "colorspace",
        "colorSpace",
        "OCIO_colorspace",
        "ocio_colorspace",
    )


def _bpe_configure_read_from_write(
    read,
    write,
    out_file: str,
    plate_colorspace: str = "",
) -> None:
    """Write 출력 형식에 맞춰 Read의 file_type/colorspace를 설정한다."""
    kind = _bpe_output_media_kind(out_file, write)
    p = out_file.lower()

    # file_type
    if kind == "exr":
        _bpe_safe_set_read_enum(
            read, ("file_type", "fileType"), ["exr", "openexr", "EXR", "OpenEXR"]
        )
    elif kind == "movie":
        if ".mp4" in p:
            _bpe_safe_set_read_enum(read, ("file_type", "fileType"), ["mp4", "mpeg4", "MP4"])
        else:
            _bpe_safe_set_read_enum(
                read,
                ("file_type", "fileType"),
                ["mov", "quicktime", "MOV", "mp4"],
            )

    # colorspace
    plate_cs = (plate_colorspace or "").strip()
    w_ocio = _knob_value_safe(write, "ocioColorspace", "OCIO_colorspace", "ocio_colorspace")
    w_cs = _knob_value_safe(write, "colorspace", "colorSpace")
    tt = _knob_value_safe(
        write,
        "colorspace_transform",
        "transform_type",
        "transformType",
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
            plate_cs,
            w_ocio,
            w_cs,
            "default",
            "Output - Rec.709",
            "sRGB",
            "rec709",
            "scene_linear",
            "compositing_linear",
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
            _wname=write_name,
            _out=out_file,
            _pcs=plate_cs,
            _wx=wx,
            _wy=wy,
            _wf=write_first,
            _wl=write_last,
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
# WRITE 경로 보정 (UNC + 잘못된 Tcl string trim 대응)
# ══════════════════════════════════════════════════════════════════════

_SINGLE_FILE_EXTS = frozenset({"mov", "mp4", "mxf", "avi"})


def _bpe_normalize_root_and_read_paths() -> None:
    """``root.name`` 과 Read ``file`` 의 UNC 를 ``W:`` 등 드라이브 경로로 통일."""
    try:
        rk = nuke.root()["name"]
        rn = rk.value()
    except Exception:
        return
    if rn:
        new_rn = normalize_path_str(rn)
        old_s = str(rn).replace("\\", "/").rstrip("/")
        if new_rn.rstrip("/") != old_s.rstrip("/"):
            try:
                rk.setValue(new_rn)
            except Exception:
                pass
    for node in nuke.allNodes("Read"):
        fk = node.knob("file")
        if fk is None:
            continue
        try:
            if fk.hasExpression():
                continue
        except Exception:
            continue
        try:
            cur_s = str(fk.value())
        except Exception:
            continue
        if not cur_s.strip():
            continue
        new_v = normalize_path_str(cur_s)
        if new_v.replace("\\", "/").rstrip("/") != cur_s.replace("\\", "/").rstrip("/"):
            try:
                fk.setExpression("")
                fk.setValue(new_v)
            except Exception:
                pass


def _bpe_is_bpe_managed_write_path(script_text: str) -> bool:
    """``value root.name`` 기반 BPE 템플릿/레거시 Write 만 대상으로 한다."""
    if "value root.name" not in script_text:
        return False
    if "string trim" in script_text:
        return True
    st = script_text.replace("\\", "/").lower()
    if "file dirname" in script_text and "/renders/" in st:
        return True
    return False


def _bpe_extract_frame_pattern_from_script(script_text: str) -> str:
    """Write ``file`` Tcl/값에서 프레임 패턴(``%04d``, ``####`` 등)을 추출. 기본 ``%04d``."""
    t = script_text.replace("\\", "")
    m = re.search(r"\.(%\d*d|#+)\.(\w+)", t)
    if m:
        fp = m.group(1)
        if fp.startswith("#"):
            n = len(fp)
            return f"%{max(n, 4)}d" if n >= 4 else "%d"
        return fp
    return "%04d"


def _bpe_write_ext_from_node(node, script_text: str) -> str:
    """Write ``file_type`` 또는 기존 경로에서 확장자 추출."""
    ft = node.knob("file_type")
    if ft is not None:
        try:
            v = str(ft.value()).strip().lower()
            if v:
                return v
        except Exception:
            pass
    t = script_text.replace("\\", "")
    m = re.search(r"\.(%\d*d|#+)\.(\w+)", t)
    if m:
        return m.group(2).lower()
    m2 = re.search(r"\.(\w+)(?:\s|$|\"|\])", t)
    if m2:
        return m2.group(1).lower()
    return "exr"


def _bpe_absolute_write_path_for_root(
    root_name: str,
    script_text: str,
    node,
    unc_mappings: Dict[str, str],
) -> Optional[str]:
    """``comp/devl/renders`` + UNC→드라이브 정규화 + 시퀀스/단일 파일 규칙."""
    renders_dir = renders_dir_from_nk_path_robust(root_name)
    if not renders_dir:
        return None
    renders_dir = normalize_unc_to_drive(renders_dir, unc_mappings)
    normalized = root_name.replace("\\", "/")
    nk_basename = os.path.basename(normalized)
    shot_ver = os.path.splitext(nk_basename)[0]
    ext = _bpe_write_ext_from_node(node, script_text)
    if ext in _SINGLE_FILE_EXTS:
        return f"{renders_dir}/{shot_ver}.{ext}"
    fp = _bpe_extract_frame_pattern_from_script(script_text)
    return f"{renders_dir}/{shot_ver}/{shot_ver}.{fp}.{ext}"


def _bpe_apply_write_string_trim_fix() -> int:
    """BPE 관리 Write 노드의 ``file`` 을 ``comp/devl/renders`` 절대 경로(``W:/``)로 설정한다.

    ``string trim``/``file dirname`` Tcl 은 UNC·비표준 NK 깊이에서 잘못된 결과를 낼 수 있어
    onLoad/onSave 마다 ``root.name`` 기준으로 재계산한다.

    Returns:
        갱신된 Write 노드 수.
    """
    _bpe_normalize_root_and_read_paths()
    patched = 0
    try:
        root_name = nuke.root()["name"].value()
    except Exception:
        return 0
    if not root_name:
        return 0
    try:
        unc_mappings = get_unc_mappings()
    except Exception:
        unc_mappings = {}
    for node in nuke.allNodes("Write"):
        file_knob = node.knob("file")
        if file_knob is None:
            continue
        try:
            script_text = file_knob.toScript()
        except Exception:
            continue
        if not _bpe_is_bpe_managed_write_path(script_text):
            continue
        abs_path = _bpe_absolute_write_path_for_root(root_name, script_text, node, unc_mappings)
        if not abs_path:
            continue
        try:
            cur = file_knob.value()
        except Exception:
            cur = ""
        if str(cur).replace("\\", "/").rstrip("/") == abs_path.replace("\\", "/").rstrip("/"):
            continue
        try:
            file_knob.setExpression("")
        except Exception:
            pass
        try:
            file_knob.setValue(abs_path)
        except Exception:
            continue
        patched += 1
        nuke.tprint(f"[BPE] Write 경로 보정: {node.name()}")
    return patched


def bpe_fix_write_paths_on_save() -> None:
    """onScriptSave — BPE 관리 Write 의 ``file`` 을 ``comp/devl/renders`` 절대 경로로 갱신."""
    try:
        if not nuke.root()["name"].value():
            return
        _bpe_apply_write_string_trim_fix()
    except Exception as e:
        nuke.tprint(f"[BPE] Write 경로 보정(onSave) 실패: {e}")


def bpe_fix_write_paths_on_load() -> None:
    """onScriptLoad — 스크립트 열 직후 BPE 관리 Write 절대 경로 보정 (직접 연 NK 대응)."""
    try:
        nuke.executeDeferred(_bpe_fix_write_paths_on_load_deferred)
    except Exception as e:
        nuke.tprint(f"[BPE] Write 경로 보정(onLoad) 실패: {e}")


def _bpe_fix_write_paths_on_load_deferred() -> None:
    try:
        if not nuke.root()["name"].value():
            return
        _bpe_apply_write_string_trim_fix()
        try:
            nuke.root().setModified(False)
        except Exception:
            pass
    except Exception as e:
        nuke.tprint(f"[BPE] Write 경로 보정(load deferred) 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# TOOL HOOKS 관리
# ══════════════════════════════════════════════════════════════════════


def reload_tool_hooks() -> None:
    """settings.json의 tools 섹션을 읽어 BeforeRender/AfterRender 훅을 등록/해제한다."""
    try:
        tools_cfg = get_tools_settings()
    except Exception as e:
        logger.error("settings 로드 실패: %s", e)
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

    # Write 경로 보정 (항상 활성 — UNC + string trim 버그 대응)
    try:
        nuke.removeOnScriptSave(bpe_fix_write_paths_on_save)
    except Exception:
        pass
    try:
        nuke.addOnScriptSave(bpe_fix_write_paths_on_save)
    except Exception as e:
        nuke.tprint(f"[BPE Tools] addOnScriptSave(Write 경로 보정) 등록 실패: {e}")

    try:
        nuke.removeOnScriptLoad(bpe_fix_write_paths_on_load)
    except Exception:
        pass
    try:
        nuke.addOnScriptLoad(bpe_fix_write_paths_on_load)
    except Exception as e:
        nuke.tprint(f"[BPE Tools] addOnScriptLoad(Write 경로 보정) 등록 실패: {e}")

    msg = (
        "[BPE Tools] Reload 완료 — "
        "QC Checker: %s  |  Post-Render Viewer: %s  |  "
        "Write 경로 보정(onLoad/onSave): ON  |  settings: %s"
        % (
            "ON" if qc_enabled else "OFF",
            "ON" if prv_enabled else "OFF",
            cfg.SETTINGS_FILE,
        )
    )
    logger.info(
        "reload_tool_hooks qc=%s post_render=%s settings=%s",
        qc_enabled,
        prv_enabled,
        cfg.SETTINGS_FILE,
    )
    nuke.tprint(msg)
