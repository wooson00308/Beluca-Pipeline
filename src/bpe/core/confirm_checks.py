"""컨펌 창의 기계 검사 — 프레임 수·fps·해상도만 판정한다.

색·그레인은 판정하지 않는다(사람이 본다). 규격을 못 읽으면 통과가 아니라 "모름"이다.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional

from bpe.core.confirm_probe import VideoInfo

STATE_PASS = "pass"
STATE_FAIL = "fail"
STATE_UNKNOWN = "unknown"

FPS_TOLERANCE = 0.01


class CheckResult(NamedTuple):
    name: str
    state: str
    message: str


def _fmt_fps(v: Optional[float]) -> str:
    return f"{v:.3f}" if v else "?"


def check_work_against_reference(
    work: Optional[VideoInfo],
    reference: Optional[VideoInfo],
    reference_label: str,
    *,
    compare_resolution: bool = True,
) -> List[CheckResult]:
    """작업본 규격을 기준(편집본, 없으면 원본)과 대조한 결과 3줄.

    *compare_resolution* 이 꺼져 있으면(기준이 원본이라 크기가 다를 수 있을 때)
    해상도는 판정하지 않고 값만 알려 준다.
    """
    if work is None:
        msg = "작업본 규격을 읽지 못함"
        return [
            CheckResult("프레임", STATE_UNKNOWN, msg),
            CheckResult("fps", STATE_UNKNOWN, msg),
            CheckResult("해상도", STATE_UNKNOWN, msg),
        ]
    if reference is None:
        msg = f"{reference_label} 없음 — 대조하지 못함"
        return [
            CheckResult("프레임", STATE_UNKNOWN, f"{work.frame_count or '?'} · {msg}"),
            CheckResult("fps", STATE_UNKNOWN, f"{_fmt_fps(work.fps)} · {msg}"),
            CheckResult("해상도", STATE_UNKNOWN, f"{work.width}×{work.height} · {msg}"),
        ]

    out: List[CheckResult] = []
    wf, rf = work.frame_count, reference.frame_count
    if wf is None or rf is None:
        out.append(CheckResult("프레임", STATE_UNKNOWN, f"{wf or '?'} / {rf or '?'} 모름"))
    elif wf == rf:
        out.append(CheckResult("프레임", STATE_PASS, f"프레임 {wf}/{rf} 통과"))
    else:
        out.append(
            CheckResult(
                "프레임", STATE_FAIL, f"프레임 수 다름: {reference_label} {rf} / 작업본 {wf}"
            )
        )

    if work.fps is None or reference.fps is None:
        out.append(CheckResult("fps", STATE_UNKNOWN, "fps 모름"))
    elif abs(work.fps - reference.fps) <= FPS_TOLERANCE:
        out.append(CheckResult("fps", STATE_PASS, f"fps {_fmt_fps(work.fps)} 통과"))
    else:
        out.append(
            CheckResult(
                "fps",
                STATE_FAIL,
                f"fps 다름: {reference_label} {_fmt_fps(reference.fps)} "
                f"/ 작업본 {_fmt_fps(work.fps)}",
            )
        )

    ws, rs = (work.width, work.height), (reference.width, reference.height)
    if not compare_resolution:
        note = "" if ws == rs else f" ({reference_label} {rs[0]}×{rs[1]})"
        out.append(CheckResult("해상도", STATE_UNKNOWN, f"해상도 {ws[0]}×{ws[1]}{note}"))
    elif ws == rs:
        out.append(CheckResult("해상도", STATE_PASS, f"해상도 {ws[0]}×{ws[1]} 통과"))
    else:
        out.append(
            CheckResult(
                "해상도",
                STATE_FAIL,
                f"해상도 다름: {reference_label} {rs[0]}×{rs[1]} / 작업본 {ws[0]}×{ws[1]}",
            )
        )
    return out


def has_failure(results: List[CheckResult]) -> bool:
    return any(r.state == STATE_FAIL for r in results)


def failure_lines(results: List[CheckResult]) -> List[str]:
    """메모에 넣을 실패 문장들."""
    return [r.message for r in results if r.state == STATE_FAIL]
