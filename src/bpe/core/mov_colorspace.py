"""플레이트 MOV의 컬러스페이스(Rec.709 vs Gamma 2.2)를 QuickTime/ISO-BMFF
메타데이터에서 자동 판별한다.

이 모듈은 **MMK_028 프로젝트 전용** Shot Builder 자동 컬러 인식에만 쓰인다.
순수 표준 라이브러리만 사용하며(Python 3.9 호환), 비디오 트랙 sample entry
안쪽의 ``colr`` 박스(nclc/nclx)와 레거시 ``gama`` 아톰을 읽는다.

스튜디오 관례(샘플 검증 완료):
- Rec.709 플레이트 → ``colr`` nclc/nclx, transfer=1(BT.709) 로 태그됨.
- Gamma 2.2 플레이트 → ``colr``/``gama`` 가 아예 없는 태그 없는 ProRes.
- 그 외 알 수 없는 태그(PQ/HLG/로그 등) → 판별 불가(None) → 호출부가 안전 중단.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from bpe.core.logging import get_logger

logger = get_logger("mov_colorspace")

REC709 = "REC709"
GAMMA = "GAMMA"

# 컬러를 화면에 노출하지 않으려고 사람이 읽는 표시는 별도로 둔다.
DISPLAY_NAME = {
    REC709: "Rec.709",
    GAMMA: "Gamma 2.2",
}

# 자식 박스를 그대로 담는 컨테이너 박스
_CONTAINERS = frozenset({b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"})

# VisualSampleEntry 고정 헤더 길이(박스 헤더 8바이트 제외):
# SampleEntry(8) + VisualSampleEntry(70) = 78
_VISUAL_SAMPLE_ENTRY_FIXED = 78

_VIDEO_GLOBS = ("*.mov", "*.mp4", "*.m4v", "*.mxf")

# BT.709 계열로 보는 transfer characteristics (모두 709 곡선을 공유)
_REC709_TRANSFER = frozenset({1, 6, 14, 15})
# 감마/2.2 계열로 보는 transfer characteristics
_GAMMA_TRANSFER = frozenset({4, 13})


class MovColorInfo(NamedTuple):
    """MOV 컬러 판별 결과와 근거."""

    result: Optional[str]  # REC709 / GAMMA / None
    reason: str  # 로그용 사람이 읽는 근거
    colr_type: Optional[str]  # "nclc"/"nclx"/None
    primaries: Optional[int]
    transfer: Optional[int]
    matrix: Optional[int]
    gamma: Optional[float]


# ---------------------------------------------------------------------------
# 저수준 ISO-BMFF 박스 워커
# ---------------------------------------------------------------------------


def _iter_boxes(data: bytes, start: int, end: int):
    """``data[start:end]`` 안의 형제 박스들을 ``(type, content_start, box_end, box_start)``
    로 순회한다. 64비트 크기(size==1)와 끝까지(size==0)를 처리한다."""
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", data, pos)[0]
        typ = data[pos + 4 : pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            break
        box_end = min(pos + size, end)
        yield typ, pos + header, box_end, pos
        pos = pos + size if size > 0 else box_end


def _find_box(data: bytes, start: int, end: int, target: bytes) -> Optional[Tuple[int, int]]:
    """``[start, end)`` 직계 자식 중 첫 ``target`` 박스의 ``(content_start, box_end)``."""
    for typ, cs, ce, _bs in _iter_boxes(data, start, end):
        if typ == target:
            return cs, ce
    return None


def _load_moov_bytes(path: Path) -> Optional[bytes]:
    """파일을 통째로 읽지 않고 최상위 박스를 훑어 ``moov`` 내용만 메모리에 올린다.

    ``mdat``(수십~수백 MB)는 seek 로 건너뛴다."""
    try:
        total = path.stat().st_size
    except OSError:
        return None
    if total < 16:
        return None
    try:
        with path.open("rb") as f:
            pos = 0
            while pos + 8 <= total:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                size = struct.unpack(">I", hdr[:4])[0]
                typ = hdr[4:8]
                header = 8
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = struct.unpack(">Q", ext)[0]
                    header = 16
                elif size == 0:
                    size = total - pos
                if size < header:
                    break
                if typ == b"moov":
                    f.seek(pos + header)
                    want = size - header
                    # 비정상적으로 큰 moov 방어 (64MB 상한)
                    if want <= 0 or want > 64 * 1024 * 1024:
                        return None
                    return f.read(want)
                pos += size
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# colr / gama 추출
# ---------------------------------------------------------------------------


def _read_video_color_tags(
    moov: bytes,
) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int], Optional[float]]:
    """비디오 트랙 sample entry 안의 ``colr``/``gama`` 를 읽는다.

    Returns:
        ``(colr_type, primaries, transfer, matrix, gamma)`` — 없으면 각 None.
    """
    end = len(moov)
    for typ, cs, ce, _bs in _iter_boxes(moov, 0, end):
        if typ != b"trak":
            continue
        mdia = _find_box(moov, cs, ce, b"mdia")
        if not mdia:
            continue
        mds, mde = mdia
        hdlr = _find_box(moov, mds, mde, b"hdlr")
        if not hdlr:
            continue
        hs, _he = hdlr
        # hdlr: version(1)+flags(3)+pre_defined(4)+handler_type(4)
        if hs + 12 > mde:
            continue
        handler = moov[hs + 8 : hs + 12]
        if handler != b"vide":
            continue
        minf = _find_box(moov, mds, mde, b"minf")
        if not minf:
            continue
        stbl = _find_box(moov, minf[0], minf[1], b"stbl")
        if not stbl:
            continue
        stsd = _find_box(moov, stbl[0], stbl[1], b"stsd")
        if not stsd:
            continue
        ss, se = stsd
        # stsd FullBox: version(1)+flags(3)+entry_count(4)
        if ss + 8 > se:
            continue
        entries_start = ss + 8
        for _etyp, _ecs, ece, ebs in _iter_boxes(moov, entries_start, se):
            child_start = ebs + 8 + _VISUAL_SAMPLE_ENTRY_FIXED
            if child_start >= ece:
                continue
            colr_type: Optional[str] = None
            pri = trc = mat = None
            gamma: Optional[float] = None
            for ctyp, ccs, cce, _cbs in _iter_boxes(moov, child_start, ece):
                if ctyp == b"colr" and cce - ccs >= 4:
                    ctype = moov[ccs : ccs + 4]
                    if ctype in (b"nclc", b"nclx") and cce - ccs >= 10:
                        colr_type = ctype.decode("latin1")
                        pri = struct.unpack_from(">H", moov, ccs + 4)[0]
                        trc = struct.unpack_from(">H", moov, ccs + 6)[0]
                        mat = struct.unpack_from(">H", moov, ccs + 8)[0]
                elif ctyp == b"gama" and cce - ccs >= 4:
                    gamma = struct.unpack_from(">I", moov, ccs)[0] / 65536.0
            return colr_type, pri, trc, mat, gamma
        return None, None, None, None, None
    return None, None, None, None, None


def _classify(
    colr_type: Optional[str],
    transfer: Optional[int],
    gamma: Optional[float],
) -> Tuple[Optional[str], str]:
    """추출한 태그를 REC709/GAMMA/None 로 분류하고 근거 문자열을 반환한다."""
    if colr_type and transfer is not None:
        if transfer in _REC709_TRANSFER:
            return REC709, f"colr {colr_type} transfer={transfer} (BT.709)"
        if transfer in _GAMMA_TRANSFER:
            return GAMMA, f"colr {colr_type} transfer={transfer} (gamma)"
        # PQ(16)/HLG(18)/unspecified(2)/log 등 — 알 수 없음
        return None, f"colr {colr_type} transfer={transfer} (지원하지 않는 transfer)"
    if gamma is not None:
        if gamma >= 1.8:
            return GAMMA, f"gama={gamma:.3f}"
        return None, f"gama={gamma:.3f} (gamma 2.2 아님)"
    # colr/gama 둘 다 없음 = 태그 없는 ProRes → 스튜디오 관례상 Gamma 2.2
    return GAMMA, "컬러 태그 없음 (태그 없는 ProRes → Gamma 2.2)"


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def inspect_mov_color(mov_path: Path) -> MovColorInfo:
    """단일 MOV 파일의 컬러 판별 결과를 근거와 함께 반환한다."""
    moov = _load_moov_bytes(mov_path)
    if moov is None:
        return MovColorInfo(None, "moov 박스를 읽지 못함", None, None, None, None, None)
    colr_type, pri, trc, mat, gamma = _read_video_color_tags(moov)
    result, reason = _classify(colr_type, trc, gamma)
    logger.debug(
        "MOV 컬러 판별 %s: result=%s colr=%s pri=%s trc=%s mat=%s gama=%s",
        mov_path.name,
        result,
        colr_type,
        pri,
        trc,
        mat,
        gamma,
    )
    return MovColorInfo(result, reason, colr_type, pri, trc, mat, gamma)


def detect_mov_colorspace(mov_path: Path) -> Optional[str]:
    """MOV 한 개의 컬러스페이스를 ``REC709``/``GAMMA``/None 으로 반환한다."""
    return inspect_mov_color(mov_path).result


def find_plate_movs_in_dir(plate_dir: Path) -> List[Path]:
    """``plate_dir`` 안의 비디오 파일들을 이름 정렬로 반환한다(없으면 빈 리스트).

    Shot Builder/NK 생성과 동일하게 ``plate_hi``(최신 v###/hi 또는 h) 폴더에서 찾는다.
    """
    if not plate_dir.is_dir():
        return []
    movs: List[Path] = []
    try:
        for pattern in _VIDEO_GLOBS:
            movs.extend(p for p in plate_dir.glob(pattern) if p.is_file())
    except OSError:
        return []
    return sorted(movs, key=lambda p: p.name.lower())


def inspect_plate_colorspace(plate_dir: Path) -> MovColorInfo:
    """``plate_dir`` 의 대표 MOV(이름 정렬 첫 파일)로 컬러를 판별한다.

    MOV 가 하나도 없으면 ``result=None`` 과 근거를 돌려준다.
    """
    movs = find_plate_movs_in_dir(plate_dir)
    if not movs:
        return MovColorInfo(None, "플레이트 폴더에 MOV 파일이 없음", None, None, None, None, None)
    return inspect_mov_color(movs[0])
