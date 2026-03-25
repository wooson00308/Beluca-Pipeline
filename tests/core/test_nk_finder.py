"""Tests for bpe.core.nk_finder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bpe.core.nk_finder import (
    _NK_VERSION_RE,
    _nk_is_junk_file,
    find_latest_nk_path,
)


# ── _nk_is_junk_file ────────────────────────────────────────────

class TestNkIsJunkFile:
    @pytest.mark.parametrize("name", [
        "shot_v001.nk~",
        "shot.nk.autosave",
        "shot_autosave.nk",
        "shot.AUTOSAVE.nk",
        "~shot_v001.nk",
    ])
    def test_junk_detected(self, name):
        assert _nk_is_junk_file(Path(name)) is True

    @pytest.mark.parametrize("name", [
        "shot_v001.nk",
        "E107_S022_0080_comp_v003.nk",
        "test.nk",
    ])
    def test_normal_not_junk(self, name):
        assert _nk_is_junk_file(Path(name)) is False


# ── _NK_VERSION_RE ───────────────────────────────────────────────

class TestVersionRegex:
    def test_extracts_version(self):
        m = _NK_VERSION_RE.search("shot_v003.nk")
        assert m is not None
        assert m.group(1) == "003"

    def test_uppercase(self):
        m = _NK_VERSION_RE.search("shot_V12.nk")
        assert m is not None
        assert m.group(1) == "12"

    def test_multiple(self):
        matches = _NK_VERSION_RE.findall("shot_v001_v002.nk")
        assert matches == ["001", "002"]

    def test_no_version(self):
        assert _NK_VERSION_RE.search("shot.nk") is None


# ── find_latest_nk_path ─────────────────────────────────────────

class TestFindLatestNkPath:
    def _make_shot_tree(self, tmp_path: Path, shot_name: str) -> Path:
        """tmp_path 아래에 표준 샷 디렉토리 구조를 만들고 shot_root를 반환."""
        ep = shot_name.split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / shot_name.upper()
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        nuke_dir.mkdir(parents=True)
        return shot_root

    def test_finds_latest_version(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_001")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"

        (nuke_dir / "E01_S01_001_comp_v001.nk").write_text("v1")
        (nuke_dir / "E01_S01_001_comp_v002.nk").write_text("v2")
        (nuke_dir / "E01_S01_001_comp_v003.nk").write_text("v3")

        result = find_latest_nk_path("E01_S01_001", "PRJ", str(tmp_path))
        assert result is not None
        assert "v003" in result.name

    def test_falls_back_to_mtime(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_002")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"

        old = nuke_dir / "old.nk"
        old.write_text("old")
        # 과거 시간으로 설정
        os.utime(old, (0, 0))

        new = nuke_dir / "new.nk"
        new.write_text("new")

        result = find_latest_nk_path("E01_S01_002", "PRJ", str(tmp_path))
        assert result is not None
        assert result.name == "new.nk"

    def test_skips_junk_files(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_003")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"

        (nuke_dir / "E01_S01_003_comp_v001.nk").write_text("good")
        (nuke_dir / "E01_S01_003_comp_v002.nk.autosave").write_text("junk")
        (nuke_dir / "E01_S01_003_comp_v002.nk~").write_text("junk")

        result = find_latest_nk_path("E01_S01_003", "PRJ", str(tmp_path))
        assert result is not None
        assert "v001" in result.name

    def test_returns_none_for_empty(self, tmp_path):
        self._make_shot_tree(tmp_path, "E01_S01_004")
        result = find_latest_nk_path("E01_S01_004", "PRJ", str(tmp_path))
        assert result is None

    def test_returns_none_missing_args(self):
        assert find_latest_nk_path("", "PRJ", "/nonexistent") is None
        assert find_latest_nk_path("SHOT", "PRJ", "") is None

    def test_prefers_name_match(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_005")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"

        (nuke_dir / "E01_S01_005_comp_v001.nk").write_text("match")
        (nuke_dir / "OTHER_SHOT_v099.nk").write_text("no match but higher ver")

        result = find_latest_nk_path("E01_S01_005", "PRJ", str(tmp_path))
        assert result is not None
        assert "E01_S01_005" in result.name
