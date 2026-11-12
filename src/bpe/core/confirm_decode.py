"""컨펌 창용 영상 풀기 — ffmpeg 로 프레임을 16비트 RGB 바이트로 받는 명령과 계산.

프로세스 실행과 스레드는 gui 워커가 맡는다. 여기는 명령 만들기·바이트 계산·
프레임 번호 변환만 둔다(표준 라이브러리만).
"""

from __future__ import annotations

from typing import BinaryIO, Iterator, List, Optional, Tuple

BYTES_PER_SAMPLE = 2  # rgb48le / rgba64le
DEFAULT_COLOR_MATRIX = "bt709"


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
) -> List[str]:
    """*path* 를 rawvideo 16비트 RGB 로 표준 출력에 푸는 ffmpeg 명령.

    - 색 행렬을 항상 명시한다(태그 없는 ProRes 를 ffmpeg 가 601 로 풀지 않게).
    - ``start_index`` 는 0부터 세는 프레임 번호. 앞에서부터 풀며 건너뛰므로 정확하다.
    - ``-fps_mode passthrough`` 로 프레임이 복제·삭제되지 않게 한다.
    """
    filters: List[str] = []
    if start_index > 0:
        filters.append(f"select=gte(n\\,{int(start_index)})")
    size = f"{int(width)}:{int(height)}" if width and height else "iw:ih"
    filters.append(f"scale={size}:in_color_matrix={color_matrix}")

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
