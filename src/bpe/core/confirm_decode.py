"""컨펌 창용 영상 풀기 — ffmpeg 로 프레임을 16비트 RGB 바이트로 받는 명령과 계산.

프로세스 실행과 스레드는 gui 워커가 맡는다. 여기는 명령 만들기·바이트 계산·
프레임 번호 변환만 둔다(표준 라이브러리만).
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from typing import BinaryIO, Iterator, List, Optional, Tuple

from bpe.core.win_subprocess import no_console_subprocess_kwargs

BYTES_PER_SAMPLE = 2  # rgb48le / rgba64le
DEFAULT_COLOR_MATRIX = "bt709"

# 크기를 줄이는 방법. 누크의 Reformat 기본 필터(Cubic)와 같은 식으로 줄인다.
#  - plain: 영상에 저장된 값 그대로 줄인다(빠름). 두 판을 같은 비율로 줄일 때는 이것으로 충분하다.
#  - linear709 / linear22: 누크처럼 선형 색으로 바꾼 뒤 줄이고 되돌린다. 원본(UHD)만 줄여서
#    납품본(1080)과 뺄 때 그레인이 가장 잘 지워진다(실측: 남는 그레인 11 % → 5 %). 절반쯤 느리다.
RESAMPLE_PLAIN = "plain"
RESAMPLE_LINEAR_709 = "linear709"
RESAMPLE_LINEAR_22 = "linear22"
_NUKE_CUBIC_FLAGS = "flags=bicubic:param0=0:param1=0"
_ZSCALE_TRANSFER = {RESAMPLE_LINEAR_709: "709", RESAMPLE_LINEAR_22: "bt470m"}
_ZSCALE_RGB = "primariesin=709:primaries=709:matrixin=gbr:matrix=gbr:rangein=full:range=full"


@lru_cache(maxsize=8)
def ffmpeg_has_filter(ffmpeg: str, name: str) -> bool:
    """이 ffmpeg 에 *name* 필터가 들어 있나(선형으로 줄이려면 ``zscale`` 이 있어야 한다)."""
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=20,
            **no_console_subprocess_kwargs(),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    text = out.decode("utf-8", "replace")
    return any(len(p) > 1 and p[1] == name for p in (ln.split() for ln in text.splitlines()))


def frame_byte_size(width: int, height: int, *, alpha: bool = False) -> int:
    """16비트 프레임 한 장의 바이트 수."""
    if width <= 0 or height <= 0:
        return 0
    return width * height * (4 if alpha else 3) * BYTES_PER_SAMPLE


def estimate_cache_bytes(width: int, height: int, frames: int, *, alpha: bool = False) -> int:
    return frame_byte_size(width, height, alpha=alpha) * max(0, frames)


def fit_decode_size(width: int, height: int, max_width: int, max_height: int) -> Tuple[int, int]:
    """한도보다 크면 비율을 지켜 줄인 크기(짝수). 한도 안이면 그대로."""
    if width <= 0 or height <= 0:
        return (0, 0)
    if width <= max_width and height <= max_height:
        return (width, height)
    scale = min(max_width / width, max_height / height)
    w = max(2, int(width * scale) // 2 * 2)
    h = max(2, int(height * scale) // 2 * 2)
    return (w, h)


def build_decode_command(
    ffmpeg: str,
    path: str,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    start_index: int = 0,
    frame_count: Optional[int] = None,
    alpha: bool = False,
    color_matrix: str = DEFAULT_COLOR_MATRIX,
    resample: str = RESAMPLE_PLAIN,
) -> List[str]:
    """*path* 를 rawvideo 16비트 RGB 로 표준 출력에 푸는 ffmpeg 명령.

    - 색 행렬을 항상 명시한다(태그 없는 ProRes 를 ffmpeg 가 601 로 풀지 않게).
    - ``start_index`` 는 0부터 세는 프레임 번호. 앞에서부터 풀며 건너뛰므로 정확하다.
    - ``-fps_mode passthrough`` 로 프레임이 복제·삭제되지 않게 한다.
    - 크기를 줄일 때는 누크 Cubic 과 같은 식을 쓴다. *resample* 이 ``linear…`` 이면 누크처럼
      선형 색에서 줄인다(ffmpeg 에 ``zscale`` 필터가 있어야 한다 — :func:`ffmpeg_has_filter`).
    """
    filters: List[str] = []
    if start_index > 0:
        filters.append(f"select=gte(n\\,{int(start_index)})")
    transfer = _ZSCALE_TRANSFER.get(resample)
    if not (width and height):
        filters.append(f"scale=iw:ih:in_color_matrix={color_matrix}")
    elif transfer:
        # RGB 로 푼다 → 선형으로 → 누크 Cubic 으로 줄인다 → 원래 곡선으로 되돌린다.
        # (한 필터에 몰아 쓰면 줄이기를 먼저 해 버려 효과가 없다 — 실측으로 확인)
        filters.append(
            f"scale=iw:ih:in_color_matrix={color_matrix}:flags=bicubic+accurate_rnd+full_chroma_int"
        )
        filters.append("format=gbrpf32le")
        filters.append(f"zscale=transferin={transfer}:transfer=linear:{_ZSCALE_RGB}")
        filters.append(f"zscale=w={int(width)}:h={int(height)}:filter=bicubic:param_a=0:param_b=0")
        filters.append(f"zscale=transferin=linear:transfer={transfer}:{_ZSCALE_RGB}")
    else:
        filters.append(
            f"scale={int(width)}:{int(height)}:{_NUKE_CUBIC_FLAGS}:in_color_matrix={color_matrix}"
        )

    cmd: List[str] = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-i",
        path,
        "-an",
        "-vf",
        ",".join(filters),
        "-fps_mode",
        "passthrough",
    ]
    if frame_count is not None:
        cmd += ["-frames:v", str(max(0, int(frame_count)))]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba64le" if alpha else "rgb48le", "-"]
    return cmd


def read_exact_frames(stream: BinaryIO, frame_size: int) -> Iterator[bytes]:
    """*stream* 에서 프레임 크기만큼씩 끊어 돌려준다. 모자란 마지막 조각은 버린다."""
    if frame_size <= 0:
        return
    while True:
        chunks: List[bytes] = []
        need = frame_size
        while need > 0:
            b = stream.read(need)
            if not b:
                break
            chunks.append(b)
            need -= len(b)
        if need > 0:
            return
        yield b"".join(chunks)


def frame_to_index(frame: int, frame_start: int) -> int:
    """화면 프레임 번호(예: 1015) → 0부터 세는 번호."""
    return int(frame) - int(frame_start)


def index_to_frame(index: int, frame_start: int) -> int:
    return int(index) + int(frame_start)


def lut3d_filter(cube_path: str) -> str:
    """ffmpeg ``lut3d`` 필터 글 — 윈도우 경로의 ``\\`` 와 ``:`` 를 필터 문법에 맞게 바꾼다."""
    safe = str(cube_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"lut3d=file='{safe}':interp=trilinear"


def build_still_command(
    ffmpeg: str,
    path: str,
    index: int,
    *,
    max_edge: int = 1280,
    lut_file: str = "",
    color_matrix: str = DEFAULT_COLOR_MATRIX,
) -> List[str]:
    """*path* 의 *index* 번째(0부터) 프레임 한 장을 PNG 로 표준 출력에 내는 ffmpeg 명령.

    긴 변이 *max_edge* 를 넘으면 줄인다. *lut_file* (.cube) 을 주면 그 룩업을 씌운다.
    """
    edge = max(16, int(max_edge))
    filters = [
        f"select=eq(n\\,{max(0, int(index))})",
        f"scale=w='min(iw,{edge})':h='min(ih,{edge})':force_original_aspect_ratio=decrease"
        f":force_divisible_by=2:{_NUKE_CUBIC_FLAGS}:in_color_matrix={color_matrix}",
        "format=rgb48le",
    ]
    if lut_file:
        filters.append(lut3d_filter(lut_file))
    return [
        ffmpeg, "-v", "error", "-nostdin", "-i", path, "-an",
        "-vf", ",".join(filters),
        "-fps_mode", "passthrough", "-frames:v", "1",
        "-f", "image2pipe", "-c:v", "png", "-pix_fmt", "rgb24", "-",
    ]  # fmt: skip
