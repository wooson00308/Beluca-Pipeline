"""Tests for bpe.core.mov_colorspace — 플레이트 MOV 컬러스페이스 자동 인식."""

from __future__ import annotations

import struct
from pathlib import Path

from bpe.core.mov_colorspace import (
    GAMMA,
    REC709,
    _classify,
    detect_mov_colorspace,
    find_plate_movs_in_dir,
    inspect_mov_color,
    inspect_plate_colorspace,
)

# ---------------------------------------------------------------------------
# ISO-BMFF 박스 빌더 (테스트용 최소 MOV 합성)
# ---------------------------------------------------------------------------


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + typ + payload


def _colr_nclc(primaries: int, transfer: int, matrix: int) -> bytes:
    return _box(b"colr", b"nclc" + struct.pack(">HHH", primaries, transfer, matrix))


def _gama(value: float) -> bytes:
    return _box(b"gama", struct.pack(">I", int(round(value * 65536))))


def _visual_sample_entry(children: bytes, codec: bytes = b"apch") -> bytes:
    # VisualSampleEntry 고정 헤더 78바이트 + 자식 박스들
    return _box(codec, bytes(78) + children)


def _stsd(sample_entry: bytes) -> bytes:
    # FullBox(version+flags=4) + entry_count(4) + entries
    return _box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + sample_entry)


def _hdlr(handler_type: bytes) -> bytes:
    # version+flags(4) + pre_defined(4) + handler_type(4) + reserved(12)
    return _box(b"hdlr", bytes(8) + handler_type + bytes(12))


def _video_moov(children: bytes) -> bytes:
    stbl = _box(b"stbl", _stsd(_visual_sample_entry(children)))
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", _hdlr(b"vide") + minf)
    trak = _box(b"trak", mdia)
    return _box(b"moov", trak)


def _write_mov(path: Path, children: bytes) -> Path:
    # ftyp + (작은) mdat + moov 순서로 써서 실제 파일 구조를 흉내냄
    ftyp = _box(b"ftyp", b"qt  " + bytes(8))
    mdat = _box(b"mdat", b"\x00" * 32)
    path.write_bytes(ftyp + mdat + _video_moov(children))
    return path


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_bt709_transfer(self):
        result, _ = _classify("nclc", 1, None)
        assert result == REC709

    def test_other_709_family(self):
        for trc in (6, 14, 15):
            assert _classify("nclc", trc, None)[0] == REC709

    def test_gamma_transfer(self):
        assert _classify("nclc", 4, None)[0] == GAMMA
        assert _classify("nclc", 13, None)[0] == GAMMA

    def test_unknown_transfer_is_none(self):
        # PQ(16), HLG(18), unspecified(2) 등은 판별 불가
        for trc in (2, 16, 18):
            assert _classify("nclc", trc, None)[0] is None

    def test_gama_atom_gamma(self):
        assert _classify(None, None, 2.2)[0] == GAMMA

    def test_gama_atom_linear_is_none(self):
        assert _classify(None, None, 1.0)[0] is None

    def test_no_tags_is_gamma(self):
        # 태그 없는 ProRes → 스튜디오 관례상 Gamma 2.2
        assert _classify(None, None, None)[0] == GAMMA


# ---------------------------------------------------------------------------
# inspect_mov_color / detect_mov_colorspace
# ---------------------------------------------------------------------------


class TestInspectMovColor:
    def test_rec709_colr(self, tmp_path):
        mov = _write_mov(tmp_path / "a.mov", _colr_nclc(1, 1, 1))
        info = inspect_mov_color(mov)
        assert info.result == REC709
        assert info.colr_type == "nclc"
        assert info.transfer == 1

    def test_gamma_untagged(self, tmp_path):
        # colr/gama 없음
        mov = _write_mov(tmp_path / "b.mov", b"")
        info = inspect_mov_color(mov)
        assert info.result == GAMMA
        assert info.colr_type is None

    def test_gamma_via_gama_atom(self, tmp_path):
        mov = _write_mov(tmp_path / "c.mov", _gama(2.2))
        info = inspect_mov_color(mov)
        assert info.result == GAMMA
        assert info.gamma is not None and abs(info.gamma - 2.2) < 0.01

    def test_unknown_transfer(self, tmp_path):
        mov = _write_mov(tmp_path / "d.mov", _colr_nclc(9, 16, 9))  # PQ-ish
        info = inspect_mov_color(mov)
        assert info.result is None

    def test_detect_wrapper(self, tmp_path):
        mov = _write_mov(tmp_path / "e.mov", _colr_nclc(1, 1, 1))
        assert detect_mov_colorspace(mov) == REC709

    def test_missing_file(self, tmp_path):
        info = inspect_mov_color(tmp_path / "nope.mov")
        assert info.result is None

    def test_not_a_mov(self, tmp_path):
        bad = tmp_path / "x.mov"
        bad.write_bytes(b"not a real mov file")
        assert inspect_mov_color(bad).result is None


# ---------------------------------------------------------------------------
# 폴더 단위 헬퍼
# ---------------------------------------------------------------------------


class TestPlateDirHelpers:
    def test_find_movs_sorted(self, tmp_path):
        (tmp_path / "B.mov").write_bytes(b"x")
        (tmp_path / "a.mov").write_bytes(b"x")
        (tmp_path / "note.txt").write_bytes(b"x")
        found = find_plate_movs_in_dir(tmp_path)
        assert [p.name for p in found] == ["a.mov", "B.mov"]

    def test_find_movs_empty(self, tmp_path):
        assert find_plate_movs_in_dir(tmp_path) == []

    def test_find_movs_missing_dir(self, tmp_path):
        assert find_plate_movs_in_dir(tmp_path / "nope") == []

    def test_inspect_plate_rec709(self, tmp_path):
        _write_mov(tmp_path / "shot_org_v001.mov", _colr_nclc(1, 1, 1))
        assert inspect_plate_colorspace(tmp_path).result == REC709

    def test_inspect_plate_gamma_untagged(self, tmp_path):
        _write_mov(tmp_path / "shot_org_v001.mov", b"")
        assert inspect_plate_colorspace(tmp_path).result == GAMMA

    def test_inspect_plate_no_mov(self, tmp_path):
        info = inspect_plate_colorspace(tmp_path)
        assert info.result is None
        assert "MOV" in info.reason
