"""컨펌 창용 영상 규격 읽기 (ffprobe).

못 읽으면 ``None`` 을 돌려준다 — 가짜 기본값을 만들지 않는다. "모름"과 "다름"을
구분해야 대조 결과를 믿을 수 있기 때문이다.
"""

from __future__ import annotations

import json
import os
import struct
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
    # 파일이 중간에 끊겼을 때만 채운다(멀쩡하면 0): 모자란 바이트 수와 지금 있는 바이트 수.
    # 영상 머리 글의 프레임 수는 끊긴 파일에서도 온전하게 적혀 있어 그것만으로는 알 수 없다.
    bytes_missing: int = 0
    bytes_present: int = 0

    @property
    def is_cut(self) -> bool:
        """파일이 중간에 끊겨 뒷부분 그림이 없는가."""
        return self.bytes_missing > 0

    @property
    def has_alpha(self) -> bool:
        return self.pix_fmt.lower().startswith(_ALPHA_PIX_FMT_PREFIXES)


_CODEC_NAMES = {
    "h264": "H.264",
    "hevc": "H.265",
    "dnxhd": "DNxHD",
    "mjpeg": "MJPEG",
    "mpeg4": "MPEG-4",
}
_PRORES_PROFILES = {
    "proxy": "ProRes 422 Proxy",
    "lt": "ProRes 422 LT",
    "standard": "ProRes 422",
    "hq": "ProRes 422 HQ",
    "4444": "ProRes 4444",
    "xq": "ProRes 4444 XQ",
}


def codec_label(info: VideoInfo) -> str:
    """화면에 적을 코덱 이름 — ``prores`` + ``HQ`` → ``ProRes 422 HQ``."""
    codec = (info.codec or "").strip()
    profile = (info.profile or "").strip()
    if codec.lower() == "prores":
        return _PRORES_PROFILES.get(profile.lower(), f"ProRes {profile}".strip())
    name = _CODEC_NAMES.get(codec.lower(), codec)
    return " ".join(x for x in (name, profile) if x)


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


# MOV·MP4 파일 맨 위에 올 수 있는 덩어리 이름(첫 덩어리가 이 가운데 하나일 때만 믿는다)
_TOP_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")


def container_shortfall(path: str) -> int:
    """MOV·MP4 파일이 중간에 끊겼으면 모자란 바이트 수, 아니면 0.

    이런 파일은 맨 위 덩어리마다 자기 크기를 적어 둔다. 그 크기들을 차례로 따라가다가
    적힌 크기가 실제 파일 끝을 넘으면 끊긴 것이다(보내거나 복사하다 끊긴 파일). 목차가
    앞에 있는 파일은 끊겨도 프레임 수가 온전하게 읽혀, 열어 보기 전에는 알 수 없다.
    파일 몇 군데만 읽으므로 빠르다. 다른 형식이거나 못 읽으면 0(모름).
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            pos = 0
            while pos < size:
                fh.seek(pos)
                head = fh.read(16)
                if len(head) < 8:
                    return 0
                length, kind = struct.unpack(">I4s", head[:8])
                if pos == 0 and kind not in _TOP_BOXES:
                    return 0  # MOV·MP4 가 아니다
                if length == 1:  # 큰 덩어리 — 크기가 뒤 8바이트에 적혀 있다
                    if len(head) < 16:
                        return 0
                    length = struct.unpack(">Q", head[8:16])[0]
                elif length == 0:  # 파일 끝까지
                    return 0
                if length < 8:
                    return 0
                if pos + length > size:
                    return pos + length - size
                pos += length
    except (OSError, struct.error):
        return 0
    return 0


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
    info = parse_ffprobe_json(proc.stdout.decode("utf-8", errors="replace"))
    if info is None:
        return None
    missing = container_shortfall(path)
    if missing > 0:
        try:
            present = os.path.getsize(path)
        except OSError:
            present = 0
        logger.warning("confirm_probe: 파일이 끊김 %s (모자람 %d 바이트)", path, missing)
        info = info._replace(bytes_missing=missing, bytes_present=present)
    return info
