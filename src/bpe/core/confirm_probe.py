"""컨펌 창용 영상 규격 읽기 (ffprobe).

못 읽으면 ``None`` 을 돌려준다 — 가짜 기본값을 만들지 않는다. "모름"과 "다름"을
구분해야 대조 결과를 믿을 수 있기 때문이다.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, NamedTuple, Optional

from bpe.core.ffmpeg_paths import resolve_ffprobe
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs

logger = get_logger("core.confirm_probe")

_PROBE_TIMEOUT_SECS = 30
_ALPHA_PIX_FMT_PREFIXES = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya")


class VideoInfo(NamedTuple):
    width: int
    height: int
    fps: Optional[float]
    frame_count: Optional[int]
    codec: str
    profile: str
    pix_fmt: str
    color_space: str
    timecode: str

    @property
    def has_alpha(self) -> bool:
        return self.pix_fmt.lower().startswith(_ALPHA_PIX_FMT_PREFIXES)


def parse_rate(text: Any) -> Optional[float]:
    """``"24000/1001"`` / ``"24"`` → float. 못 읽으면 ``None``."""
    s = str(text or "").strip()
    if not s:
        return None
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            d = float(den)
            if d == 0:
                return None
            v = float(num) / d
        else:
            v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_video_stream(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    for s in streams:
        if isinstance(s, dict) and s.get("codec_type", "video") == "video":
            return s
    return None


def parse_ffprobe_json(text: str) -> Optional[VideoInfo]:
    """ffprobe ``-of json`` 출력 → :class:`VideoInfo`. 영상 스트림이 없으면 ``None``."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    st = _first_video_stream(payload)
    if st is None:
        return None
    try:
        width = int(st.get("width") or 0)
        height = int(st.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    frame_count: Optional[int]
    try:
        frame_count = int(str(st.get("nb_frames")))
    except (TypeError, ValueError):
        frame_count = None
    if frame_count is not None and frame_count <= 0:
        frame_count = None

    tags = _as_dict(st.get("tags"))
    fmt_tags = _as_dict(_as_dict(payload.get("format")).get("tags"))
    timecode = str(tags.get("timecode") or fmt_tags.get("timecode") or "")

    return VideoInfo(
        width=width,
        height=height,
        fps=parse_rate(st.get("r_frame_rate")) or parse_rate(st.get("avg_frame_rate")),
        frame_count=frame_count,
        codec=str(st.get("codec_name") or ""),
        profile=str(st.get("profile") or ""),
        pix_fmt=str(st.get("pix_fmt") or ""),
        color_space=str(st.get("color_space") or ""),
        timecode=timecode,
    )


def build_probe_command(ffprobe: str, path: str) -> List[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,"
        "avg_frame_rate,nb_frames,color_space:stream_tags=timecode:format_tags=timecode",
        "-of",
        "json",
        path,
    ]


def probe_video(path: str, ffprobe: Optional[str] = None) -> Optional[VideoInfo]:
    """*path* 의 규격. ffprobe 가 없거나 실패하면 ``None``."""
    exe = ffprobe or resolve_ffprobe()
    if not exe:
        logger.warning("confirm_probe: ffprobe 를 찾지 못함")
        return None
    try:
        proc = subprocess.run(
            build_probe_command(exe, path),
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECS,
            **no_console_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("confirm_probe: ffprobe 실행 실패: %s", e)
        return None
    if proc.returncode != 0:
        logger.warning("confirm_probe: ffprobe 종료 코드 %s", proc.returncode)
        return None
    return parse_ffprobe_json(proc.stdout.decode("utf-8", errors="replace"))
