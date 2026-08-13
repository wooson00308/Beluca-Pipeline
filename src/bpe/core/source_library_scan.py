# @cursor-change: 2026-08-13, 0.12.x, 3D·ball_pass 카테고리 한정 PNG/TGA 시퀀스 묶기(opt-in)
"""소스 라이브러리 스캔 — 폴더 한 단계 나열 + 플레이트 시퀀스 묶기.

가벼움이 최우선이라 이 모듈은 재귀 탐색을 하지 않는다. 호출자가 필요한 폴더를
한 단계씩만 요청하고, 전체 인덱싱은 백그라운드 워커가 폴더 단위로 나눠 돈다.

``nk_generator`` 에도 비슷한 시퀀스 탐색이 있지만 그쪽은 샷 이름 규칙(``E###_S###_``)과
플레이트 폴더 구조에 묶여 있고 4자리 패딩만 가정한다. 라이브러리는 외부 소스가 섞여
패딩 폭이 제각각이라 여기서 독립적으로 다시 구현한다.

번호가 붙은 JPG/PNG 등 스틸은 기본적으로 파일마다 카드로 둔다. EXR/DPX/CIN
플레이트만 시퀀스 한 벌로 합친다. 단, ``STILL_SEQUENCE_CATEGORIES`` 카테고리
(3D·ball_pass — 패스별 PNG/TGA 렌더 폴더)에서만 워커가 ``allow_still_sequences=True``
를 넘겨 3장 이상 연속 번호 PNG/TGA/TIF 를 시퀀스로 묶는다.
``try_build_pack`` 은 CS ``pack_roots`` 스캔 워커가 호출한다.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

# 스캔 대상이 되는 프레임형 확장자 (스틸·플레이트 포함)
SEQUENCE_EXTS = frozenset(
    {".exr", ".dpx", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".tga", ".cin"}
)
# 번호 접미가 있어도 시퀀스로 묶는 플레이트만 (나머지는 파일당 still 카드)
PLATE_SEQUENCE_EXTS = frozenset({".exr", ".dpx", ".cin"})
# 단일 파일 동영상 확장자
MOVIE_EXTS = frozenset({".mov", ".mp4", ".mxf", ".avi", ".mkv", ".m4v", ".webm"})
# 라이브러리에서 취급하는 전체 확장자
MEDIA_EXTS = frozenset(SEQUENCE_EXTS | MOVIE_EXTS)

KIND_SEQUENCE = "sequence"
KIND_MOVIE = "movie"
KIND_STILL = "still"

# 프레임 번호는 이름 맨 뒤 연속 숫자. 패딩 폭을 고정하지 않는다.
_TRAILING_DIGITS_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")

# 시퀀스로 인정할 최소 프레임 수. 1장뿐이면 스틸로 본다.
_MIN_SEQUENCE_FRAMES = 2

# ── 스틸 확장자 시퀀스 묶기 (opt-in — STILL_SEQUENCE_CATEGORIES 한정) ──
# 이 카테고리(등록 루트 바로 아래 폴더명, 대소문자 무시)에서만 PNG/TGA/TIF 연번을
# 시퀀스로 묶는다. 패스별 렌더 폴더가 낱장 카드 수백 장으로 퍼지는 것을 막는 용도.
STILL_SEQUENCE_CATEGORIES = frozenset({"3d", "ball_pass"})
_STILL_SEQUENCE_CANDIDATE_EXTS = frozenset({".png", ".tga", ".tif", ".tiff"})
# 스틸 확장자는 오탐(레퍼런스 이미지 세트)을 피하려고 플레이트(2장)보다 높은 기준.
_MIN_STILL_SEQUENCE_FRAMES = 3

# 팩 내부 실제 소스 폴더명 (대소문자 무시)
_IMAGE_SUBDIR_NAMES = frozenset({"image", "images"})
_THUMB_MOV_SUFFIX = ".thumb.mov"
_STILL_EXTS = frozenset({".jpg", ".jpeg"})


class FileEntry(NamedTuple):
    """스캔한 파일 하나. 파일시스템 없이 테스트하기 위해 값만 담는다."""

    name: str
    size_bytes: int
    mtime: float


class LibraryItem(NamedTuple):
    """라이브러리 항목 하나 — 시퀀스 한 벌, 동영상 한 개, 또는 스틸 한 장.

    팩이면 ``representative``=JPG, ``seq_pattern``=image/ 시퀀스,
    ``preview_file``=.thumb.mov 이다.
    """

    name: str  # 화면에 보여줄 이름 (시퀀스는 프레임 번호 없는 이름)
    kind: str  # KIND_SEQUENCE / KIND_MOVIE / KIND_STILL
    ext: str  # ".exr" 처럼 점 포함 소문자
    seq_pattern: str  # 시퀀스면 "plate.%04d.exr", 그 외에는 실제 파일명
    representative: str  # 썸네일을 뽑을 실제 파일명 (시퀀스는 중간 프레임)
    frame_first: int
    frame_last: int
    frame_count: int
    size_bytes: int  # 시퀀스는 전체 프레임 합계
    mtime: float  # 그룹 내 최신 mtime
    preview_file: str = ""  # 팩 프리뷰 MOV (없으면 빈 문자열)


def split_trailing_number(stem: str) -> Optional[Tuple[str, str]]:
    """``"plate.1001"`` → ``("plate.", "1001")``. 끝이 숫자가 아니면 ``None``."""
    m = _TRAILING_DIGITS_RE.match(stem)
    if m is None:
        return None
    return m.group("prefix"), m.group("num")


def split_name_ext(name: str) -> Tuple[str, str]:
    """확장자를 소문자로 분리한다. 확장자가 없으면 빈 문자열."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name, ""
    return stem, "." + ext.lower()


def frame_pattern(prefix: str, ext: str, pad_widths: Sequence[int]) -> str:
    """프레임 번호 자리를 ``%0Nd`` 로 바꾼 이름. 패딩 폭이 섞여 있으면 ``%d``."""
    widths = {int(w) for w in pad_widths}
    if len(widths) == 1:
        width = widths.pop()
        token = "%d" if width <= 1 else "%0{}d".format(width)
    else:
        token = "%d"
    return "{}{}{}".format(prefix, token, ext)


def expand_frame_pattern(pattern: str, frame: int) -> str:
    """``"plate.%04d.exr"`` + 1001 → ``"plate.1001.exr"``. 패턴이 없으면 그대로 반환."""
    if "%" not in pattern:
        return pattern
    try:
        return pattern % int(frame)
    except (TypeError, ValueError):
        return pattern


def group_entries(
    entries: Sequence[FileEntry],
    allow_still_sequences: bool = False,
) -> List[LibraryItem]:
    """한 폴더의 파일 목록을 라이브러리 항목으로 묶는다 (파일시스템 접근 없음).

    EXR/DPX/CIN 은 같은 접두사 + 확장자의 숫자 파일을 시퀀스 한 벌로 합친다.
    JPG/PNG 등 그 외 스틸은 번호가 있어도 파일마다 still 카드다.

    ``allow_still_sequences=True`` (STILL_SEQUENCE_CATEGORIES 카테고리 전용)면
    PNG/TGA/TIF 도 3장 이상 + 연속 번호 + 패딩 균일일 때 시퀀스로 묶는다.
    기본값 False 에서는 기존 동작과 완전히 동일하다.
    """
    # (prefix, ext) -> [(frame, FileEntry, pad_width)]
    seq_groups: Dict[Tuple[str, str], List[Tuple[int, FileEntry, int]]] = {}
    singles: List[Tuple[FileEntry, str]] = []

    for entry in entries:
        stem, ext = split_name_ext(entry.name)
        if ext not in MEDIA_EXTS:
            continue
        if ext in MOVIE_EXTS:
            singles.append((entry, ext))
            continue
        seq_candidate = ext in PLATE_SEQUENCE_EXTS or (
            allow_still_sequences and ext in _STILL_SEQUENCE_CANDIDATE_EXTS
        )
        if not seq_candidate:
            singles.append((entry, ext))
            continue
        parts = split_trailing_number(stem)
        if parts is None:
            singles.append((entry, ext))
            continue
        prefix, num = parts
        seq_groups.setdefault((prefix, ext), []).append((int(num), entry, len(num)))

    items: List[LibraryItem] = []

    for (prefix, ext), members in seq_groups.items():
        min_frames = (
            _MIN_SEQUENCE_FRAMES if ext in PLATE_SEQUENCE_EXTS else _MIN_STILL_SEQUENCE_FRAMES
        )
        if len(members) < min_frames:
            # 기준 미달이면 시퀀스가 아니라 스틸로 취급한다.
            singles.extend((entry, ext) for _f, entry, _w in members)
            continue
        members.sort(key=lambda it: it[0])
        frames = [f for f, _e, _w in members]
        if ext not in PLATE_SEQUENCE_EXTS:
            # 스틸 확장자 전용 가드 (플레이트 동작은 불변):
            # 1) 번호가 실제 연속에 가까울 때만 — 날짜/타임스탬프 파일명 오인 방지.
            #    (구간 길이가 장수의 2배를 넘으면 시퀀스가 아니라고 본다)
            # 2) 패딩 폭 균일 — 혼재 시 %d 폴백이 존재하지 않는 경로를 만들 수 있음.
            span = frames[-1] - frames[0] + 1
            widths = {w for _f, _e, w in members}
            if span > len(members) * 2 or len(widths) != 1:
                singles.extend((entry, ext) for _f, entry, _w in members)
                continue
        pattern = frame_pattern(prefix, ext, [w for _f, _e, w in members])
        # 썸네일은 중간 프레임이 내용을 가장 잘 보여준다 (앞뒤는 페이드인/아웃이 흔함).
        mid_frame, mid_entry, _mid_w = members[len(members) // 2]
        items.append(
            LibraryItem(
                name=prefix.rstrip("._- ") or prefix or mid_entry.name,
                kind=KIND_SEQUENCE,
                ext=ext,
                seq_pattern=pattern,
                representative=mid_entry.name,
                frame_first=frames[0],
                frame_last=frames[-1],
                frame_count=len(frames),
                size_bytes=sum(e.size_bytes for _f, e, _w in members),
                mtime=max(e.mtime for _f, e, _w in members),
            )
        )

    for entry, ext in singles:
        stem, _ext = split_name_ext(entry.name)
        items.append(
            LibraryItem(
                name=stem or entry.name,
                kind=KIND_MOVIE if ext in MOVIE_EXTS else KIND_STILL,
                ext=ext,
                seq_pattern=entry.name,
                representative=entry.name,
                frame_first=0,
                frame_last=0,
                frame_count=1,
                size_bytes=entry.size_bytes,
                mtime=entry.mtime,
            )
        )

    items.sort(key=lambda it: it.name.lower())
    return items


def read_dir(path: str) -> Tuple[List[str], List[FileEntry]]:
    """폴더 한 단계만 읽어 ``(하위 폴더명, 미디어 파일 목록)`` 을 반환한다.

    네트워크 폴더에서 ``stat`` 을 파일마다 새로 부르지 않도록 ``scandir`` 의 캐시된
    ``DirEntry.stat()`` 을 쓴다. 접근 불가 항목은 조용히 건너뛴다.
    """
    subdirs: List[str] = []
    files: List[FileEntry] = []
    try:
        with os.scandir(path) as it:
            for de in it:
                name = de.name
                if name.startswith("."):
                    continue
                try:
                    if de.is_dir(follow_symlinks=False):
                        subdirs.append(name)
                        continue
                    if not de.is_file(follow_symlinks=False):
                        continue
                    _stem, ext = split_name_ext(name)
                    if ext not in MEDIA_EXTS:
                        continue
                    st = de.stat(follow_symlinks=False)
                    files.append(FileEntry(name, int(st.st_size), float(st.st_mtime)))
                except OSError:
                    continue
    except OSError:
        return [], []
    subdirs.sort(key=str.lower)
    return subdirs, files


def scan_dir_items(path: str) -> List[LibraryItem]:
    """폴더 하나의 라이브러리 항목 목록 (하위 폴더는 보지 않는다)."""
    _subdirs, files = read_dir(path)
    return group_entries(files)


def find_image_subdir(subdirs: Sequence[str]) -> Optional[str]:
    """``image`` / ``images`` (대소문자 무시) 하위 폴더명을 반환."""
    for name in subdirs:
        if str(name).lower() in _IMAGE_SUBDIR_NAMES:
            return str(name)
    return None


def _thumb_mov_base(name: str) -> Optional[str]:
    """``foo.thumb.mov`` → ``foo``. 아니면 None."""
    lower = name.lower()
    if not lower.endswith(_THUMB_MOV_SUFFIX):
        return None
    return name[: len(name) - len(_THUMB_MOV_SUFFIX)]


def try_build_pack(
    dir_path: str,
    subdirs: Sequence[str],
    files: Sequence[FileEntry],
) -> Optional[Tuple[LibraryItem, List[str]]]:
    """컴프 소스 팩이면 ``(항목, 소비한 하위폴더명 목록)`` 을 반환.

    조건 (모두 충족):
    * 같은 basename 의 JPG/JPEG 하나 + ``.thumb.mov`` 하나
    * ``image``/``images`` 하위에 시퀀스 1벌 이상

    아니면 ``None`` — 호출자는 기존 ``group_entries`` 로 폴백한다.
    """
    image_subdir = find_image_subdir(subdirs)
    if image_subdir is None:
        return None

    jpgs: Dict[str, FileEntry] = {}
    thumbs: Dict[str, FileEntry] = {}
    for entry in files:
        stem, ext = split_name_ext(entry.name)
        if ext in _STILL_EXTS:
            jpgs[stem] = entry
            continue
        base = _thumb_mov_base(entry.name)
        if base is not None:
            thumbs[base] = entry

    matches = [(jpgs[b], thumbs[b]) for b in jpgs if b in thumbs]
    if len(matches) != 1:
        return None
    jpg_entry, mov_entry = matches[0]
    pack_base, _jpg_ext = split_name_ext(jpg_entry.name)

    image_path = join_path(dir_path, image_subdir)
    _img_subs, image_files = read_dir(image_path)
    image_items = group_entries(image_files)
    sequences = [it for it in image_items if it.kind == KIND_SEQUENCE]
    if not sequences:
        return None

    preferred = [
        s
        for s in sequences
        if pack_base.lower() in s.name.lower() or s.name.lower() in pack_base.lower()
    ]
    seq = preferred[0] if preferred else max(sequences, key=lambda s: int(s.frame_count))

    image_rel = image_subdir.replace("\\", "/")
    seq_pattern = "{}/{}".format(image_rel, seq.seq_pattern)
    mtime = max(float(jpg_entry.mtime), float(mov_entry.mtime), float(seq.mtime))
    pack = LibraryItem(
        name=pack_base or seq.name,
        kind=KIND_SEQUENCE,
        ext=seq.ext,
        seq_pattern=seq_pattern,
        representative=jpg_entry.name,
        frame_first=int(seq.frame_first),
        frame_last=int(seq.frame_last),
        frame_count=int(seq.frame_count),
        size_bytes=int(seq.size_bytes) + int(jpg_entry.size_bytes) + int(mov_entry.size_bytes),
        mtime=mtime,
        preview_file=mov_entry.name,
    )
    return pack, [image_subdir]


def pack_freshness_mtime(dir_path: str, image_subdir: str) -> float:
    """팩 폴더와 ``image/`` 중 더 최신 mtime — 재인덱싱 판단용."""
    return max(dir_mtime(dir_path), dir_mtime(join_path(dir_path, image_subdir)))


def dir_mtime(path: str) -> float:
    """폴더 자신의 mtime. 실패하면 0.0 — 인덱스 재검사 판단에만 쓴다."""
    try:
        return float(os.stat(path).st_mtime)
    except OSError:
        return 0.0


def relative_dir(root: str, path: str) -> str:
    """루트 기준 상대 폴더 경로(슬래시 구분). 루트 자신이면 빈 문자열."""
    root_n = root.replace("\\", "/").rstrip("/")
    path_n = path.replace("\\", "/").rstrip("/")
    if path_n == root_n:
        return ""
    prefix = root_n + "/"
    if path_n.startswith(prefix):
        return path_n[len(prefix) :]
    return path_n


def category_of(dir_rel: str) -> str:
    """카테고리 = 루트 바로 아래 첫 폴더명. 루트 직속 파일은 빈 문자열."""
    if not dir_rel:
        return ""
    return dir_rel.split("/", 1)[0]


def join_path(dir_path: str, name: str) -> str:
    """슬래시 기준으로 폴더와 파일명을 잇는다 (표시·ffmpeg 전달용)."""
    return "{}/{}".format(dir_path.replace("\\", "/").rstrip("/"), name)


def item_frame_path(dir_path: str, item: LibraryItem, frame: int) -> str:
    """시퀀스 항목의 특정 프레임 실제 경로. 시퀀스가 아니면 파일 자신."""
    if item.kind != KIND_SEQUENCE:
        return join_path(dir_path, item.seq_pattern)
    return join_path(dir_path, expand_frame_pattern(item.seq_pattern, frame))


def row_dir_path(row: Dict[str, Any]) -> str:
    """인덱스 행에서 폴더 절대경로를 복원한다."""
    root = str(row.get("root") or "").replace("\\", "/").rstrip("/")
    dir_rel = str(row.get("dir_rel") or "")
    return "{}/{}".format(root, dir_rel) if dir_rel else root


def row_representative_path(row: Dict[str, Any]) -> str:
    """썸네일을 뽑을 실제 파일 경로 (시퀀스는 중간 프레임)."""
    return join_path(row_dir_path(row), str(row.get("representative") or ""))


def row_preview_path(row: Dict[str, Any]) -> str:
    """팩 프리뷰 MOV 경로. 없으면 빈 문자열."""
    preview = str(row.get("preview_file") or "").strip()
    if not preview:
        return ""
    return join_path(row_dir_path(row), preview)


def row_pattern_path(row: Dict[str, Any]) -> str:
    """Nuke 등에 넘길 경로 — 시퀀스는 ``%04d`` 패턴이 그대로 남는다."""
    return join_path(row_dir_path(row), str(row.get("seq_pattern") or ""))


def row_first_frame_path(row: Dict[str, Any]) -> str:
    """실제로 존재하는 첫 프레임 파일 경로 (드래그 앤 드롭용)."""
    return row_frame_path(row, int(row.get("frame_first") or 0))


def row_frame_path(row: Dict[str, Any], frame: int) -> str:
    """인덱스 행의 특정 프레임 경로. 시퀀스가 아니면 파일 자신."""
    if str(row.get("kind") or "") != KIND_SEQUENCE:
        return row_pattern_path(row)
    return join_path(
        row_dir_path(row),
        expand_frame_pattern(str(row.get("seq_pattern") or ""), frame),
    )


def row_frame_label(row: Dict[str, Any]) -> str:
    """항목 아래에 보여줄 짧은 설명 (프레임 범위 또는 종류)."""
    kind = str(row.get("kind") or "")
    ext = str(row.get("ext") or "").lstrip(".").upper()
    if kind == KIND_SEQUENCE:
        return "{}  {}-{}  ({}f)".format(
            ext,
            int(row.get("frame_first") or 0),
            int(row.get("frame_last") or 0),
            int(row.get("frame_count") or 0),
        )
    return ext or kind


def filmstrip_frames(first: int, last: int, count: int) -> List[int]:
    """프레임 범위에서 균등하게 ``count`` 개를 고른다 (필름스트립용)."""
    if count <= 0:
        return []
    first_i, last_i = int(first), int(last)
    if last_i < first_i:
        first_i, last_i = last_i, first_i
    total = last_i - first_i + 1
    if total <= count:
        return list(range(first_i, last_i + 1))
    step = (total - 1) / float(count - 1) if count > 1 else 0.0
    return [first_i + int(round(step * i)) for i in range(count)]
