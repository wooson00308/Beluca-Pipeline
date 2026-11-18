"""컨펌 창의 기계 검사 — 프레임 수·fps·해상도, 그리고 프리셋이 있으면 코덱·색 표시.

기준은 두 가지다. 프레임 수는 같은 샷의 edit(없으면 ORG plate) 영상 길이와 대조하고,
나머지는 프로젝트 프리셋(납품 프리셋)과 대조한다. edit 은 길이만 참고한다.
그레인·색 느낌은 판정하지 않는다(사람이 본다). 못 읽으면 통과가 아니라 "모름"이다.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional

from bpe.core.confirm_probe import VideoInfo, codec_label
from bpe.core.confirm_standard import ProjectStandard

STATE_PASS = "pass"
STATE_FAIL = "fail"
STATE_UNKNOWN = "unknown"

FPS_TOLERANCE = 0.01
PRESET_LABEL = "프리셋"


class CheckResult(NamedTuple):
    name: str
    state: str
    message: str


def _fmt_fps(v: Optional[float]) -> str:
    return f"{v:.3f}" if v else "?"


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f}MB"


def cut_file_message(work: VideoInfo) -> str:
    """현재버전 파일이 중간에 끊겼으면 그 사실을 알리는 글, 아니면 빈 글."""
    if not work.is_cut:
        return ""
    total = work.bytes_present + work.bytes_missing
    return f"파일이 잘림: {_mb(total)} 중 {_mb(work.bytes_present)} 만 있음 — 뒷부분 그림 없음"


def short_decode_message(total: int, shown: int) -> str:
    """풀어 보니 그림이 모자랄 때의 글 — *total* 장 중 *shown* 장만 풀렸다."""
    return f"파일이 잘림: {total}장 중 {shown}장만 볼 수 있음"


def _frames(work: VideoInfo, ref: Optional[VideoInfo], ref_label: str) -> CheckResult:
    cut = cut_file_message(work)
    if cut:  # 머리 글의 프레임 수가 맞아도 그림이 다 들어 있지 않다
        return CheckResult("프레임", STATE_FAIL, cut)
    wf = work.frame_count
    if ref is None:
        return CheckResult(
            "프레임", STATE_UNKNOWN, f"{wf or '?'} · {ref_label} 없음 — 대조하지 못함"
        )
    rf = ref.frame_count
    if wf is None or rf is None:
        return CheckResult("프레임", STATE_UNKNOWN, f"{wf or '?'} / {rf or '?'} 모름")
    if wf == rf:
        return CheckResult("프레임", STATE_PASS, f"프레임 {wf}/{rf} 통과")
    return CheckResult("프레임", STATE_FAIL, f"프레임 수 다름: {ref_label} {rf} / 현재버전 {wf}")


def _fps(work: VideoInfo, want: Optional[float], label: str, missing: str) -> CheckResult:
    if want is None:
        return CheckResult("fps", STATE_UNKNOWN, missing or "fps 모름")
    if work.fps is None:
        return CheckResult("fps", STATE_UNKNOWN, "fps 모름")
    if abs(work.fps - want) <= FPS_TOLERANCE:
        return CheckResult("fps", STATE_PASS, f"fps {_fmt_fps(work.fps)} 통과")
    return CheckResult(
        "fps", STATE_FAIL, f"fps 다름: {label} {_fmt_fps(want)} / 현재버전 {_fmt_fps(work.fps)}"
    )


def _codec(work: VideoInfo, standard: ProjectStandard) -> CheckResult:
    have = (work.codec or "").strip().lower()
    shown = codec_label(work) or "?"
    if not have:
        return CheckResult("코덱", STATE_UNKNOWN, "코덱 모름")
    if have == standard.codec:
        return CheckResult("코덱", STATE_PASS, f"코덱 {shown} 통과")
    return CheckResult(
        "코덱", STATE_FAIL, f"코덱 다름: {PRESET_LABEL} {standard.codec_title} / 현재버전 {shown}"
    )


def _color(work: VideoInfo, standard: ProjectStandard) -> CheckResult:
    have = (work.color_space or "").strip().lower()
    if not have or have == "unknown":
        return CheckResult(
            "색 표시", STATE_UNKNOWN, f"색 표시 없음 ({PRESET_LABEL} {standard.look}) — 눈으로 확인"
        )
    if have in standard.color_tags:
        return CheckResult("색 표시", STATE_PASS, f"색 표시 {have} 통과")
    return CheckResult(
        "색 표시", STATE_FAIL, f"색 표시 다름: {PRESET_LABEL} {standard.look} / 현재버전 {have}"
    )


def check_work_against_reference(
    work: Optional[VideoInfo],
    reference: Optional[VideoInfo],
    reference_label: str,
    *,
    standard: Optional[ProjectStandard] = None,
    plate: Optional[VideoInfo] = None,
    plate_label: str = "ORG plate",
) -> List[CheckResult]:
    """현재버전 규격을 기준과 대조한 결과.

    - 프레임 수: *reference*(같은 샷의 edit, 없으면 ORG plate) 영상의 길이와 대조한다.
      edit 은 길이만 참고한다 — 해상도·fps 는 edit 과 맞추지 않는다.
    - fps: 프리셋(*standard*)에 값이 있으면 프리셋과, 없으면 *plate*(ORG plate)와 대조한다.
    - 해상도: 프리셋의 누크 틀이 MOV 를 내보내는 크기와 대조한다(크기가 여럿이면 그중 하나면
      통과). 틀에서 크기를 못 읽으면 판정하지 않고 값만 알려 준다.
    - 코덱·색 표시: 프리셋에 값이 있을 때만.
    """
    if work is None:
        msg = "현재버전 규격을 읽지 못함"
        return [
            CheckResult("프레임", STATE_UNKNOWN, msg),
            CheckResult("fps", STATE_UNKNOWN, msg),
            CheckResult("해상도", STATE_UNKNOWN, msg),
        ]
    out: List[CheckResult] = [_frames(work, reference, reference_label)]

    if standard is not None and standard.fps is not None:
        out.append(_fps(work, standard.fps, PRESET_LABEL, ""))
    elif plate is not None:
        out.append(_fps(work, plate.fps, plate_label, "fps 모름"))
    else:
        out.append(CheckResult("fps", STATE_UNKNOWN, f"fps {_fmt_fps(work.fps)} · 기준 없음"))

    ws = (work.width, work.height)
    wants = standard.mov_sizes if standard is not None else ()
    if not wants:
        out.append(CheckResult("해상도", STATE_UNKNOWN, f"해상도 {ws[0]}×{ws[1]} · 기준 없음"))
    elif ws in wants:
        out.append(CheckResult("해상도", STATE_PASS, f"해상도 {ws[0]}×{ws[1]} 통과"))
    else:
        expect = " 또는 ".join(f"{w}×{h}" for w, h in wants)
        out.append(
            CheckResult(
                "해상도",
                STATE_FAIL,
                f"해상도 다름: {PRESET_LABEL} {expect} / 현재버전 {ws[0]}×{ws[1]}",
            )
        )

    if standard is not None and standard.codec:
        out.append(_codec(work, standard))
    if standard is not None and standard.color_tags:
        out.append(_color(work, standard))
    return out


def basis_text(
    reference_label: str, has_reference: bool, standard: Optional[ProjectStandard]
) -> str:
    """무엇을 기준으로 봤는지 한 줄 — 「프리셋 SBS_030 · 프레임 수는 edit」."""
    head = f"{PRESET_LABEL} {standard.preset}" if standard is not None else f"{PRESET_LABEL} 없음"
    if not has_reference:
        return f"{head} · 프레임 수 기준 없음"
    return f"{head} · 프레임 수는 {reference_label}"


def has_failure(results: List[CheckResult]) -> bool:
    return any(r.state == STATE_FAIL for r in results)


def failure_lines(results: List[CheckResult]) -> List[str]:
    """메모에 넣을 실패 문장들."""
    return [r.message for r in results if r.state == STATE_FAIL]
