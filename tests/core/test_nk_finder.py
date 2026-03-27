"""Tests for bpe.core.nk_finder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bpe.core.nk_finder import (
    _NK_VERSION_RE,
    _find_nukex_exe_under_roots,
    _find_server_root_from_drive_roots,
    _nk_is_junk_file,
    find_latest_nk_path,
    find_nukex_exe,
    find_server_root_auto,
)

# ── _nk_is_junk_file ────────────────────────────────────────────


class TestNkIsJunkFile:
    @pytest.mark.parametrize(
        "name",
        [
            "shot_v001.nk~",
            "shot.nk.autosave",
            "shot_autosave.nk",
            "shot.AUTOSAVE.nk",
            "~shot_v001.nk",
        ],
    )
    def test_junk_detected(self, name):
        assert _nk_is_junk_file(Path(name)) is True

    @pytest.mark.parametrize(
        "name",
        [
            "shot_v001.nk",
            "E107_S022_0080_comp_v003.nk",
            "test.nk",
        ],
    )
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

    def test_finds_latest_in_version_subfolders(self, tmp_path):
        """nuke/v001, nuke/v003 구조에서 최신 버전 폴더의 nk를 고른다."""
        shot_root = self._make_shot_tree(tmp_path, "E102_S017_0120")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        (nuke_dir / "v001" / "E102_S017_0120_comp_v001.nk").parent.mkdir(parents=True)
        (nuke_dir / "v001" / "E102_S017_0120_comp_v001.nk").write_text("1")
        (nuke_dir / "v003" / "E102_S017_0120_comp_v003.nk").parent.mkdir(parents=True)
        (nuke_dir / "v003" / "E102_S017_0120_comp_v003.nk").write_text("3")

        result = find_latest_nk_path("E102_S017_0120", "PRJ", str(tmp_path))
        assert result is not None
        assert "v003" in str(result).replace("\\", "/")
        assert "v003" in result.name


# ── find_server_root_auto / drive scan ───────────────────────────


class TestFindServerRootFromDriveRoots:
    def test_picks_highest_year(self, tmp_path):
        fake_w = tmp_path / "fake_w"
        (fake_w / "vfx" / "project_2025" / "SBS_030").mkdir(parents=True)
        (fake_w / "vfx" / "project_2026" / "SBS_030").mkdir(parents=True)

        got = _find_server_root_from_drive_roots("SBS_030", [fake_w])
        assert got is not None
        assert str(Path(got).name).lower() == "project_2026"

    def test_missing_project_folder_ignored(self, tmp_path):
        fake_w = tmp_path / "fake_w"
        (fake_w / "vfx" / "project_2026" / "OTHER").mkdir(parents=True)

        assert _find_server_root_from_drive_roots("SBS_030", [fake_w]) is None


class TestFindServerRootAuto:
    def test_non_windows_returns_none(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        assert find_server_root_auto("SBS_030") is None


# ── find_nukex_exe ───────────────────────────────────────────────


class TestFindNukexExeUnderRoots:
    def test_prefers_higher_version_folder(self, tmp_path):
        pf = tmp_path / "pf"
        (pf / "Nuke14.0" / "Nuke14.0.exe").parent.mkdir(parents=True)
        (pf / "Nuke14.0" / "Nuke14.0.exe").write_text("exe")
        (pf / "Nuke15.1" / "Nuke15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "Nuke15.1.exe").write_text("exe")

        got = _find_nukex_exe_under_roots([pf])
        assert got is not None
        assert "15.1" in got.parent.name

    def test_prefers_nukex_named_exe_in_same_major_line(self, tmp_path):
        pf = tmp_path / "pf"
        (pf / "Nuke15.1v1" / "Nuke15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1v1" / "Nuke15.1.exe").write_text("a")
        (pf / "Nuke15.1v1" / "NukeX15.1.exe").write_text("b")

        got = _find_nukex_exe_under_roots([pf])
        assert got is not None
        assert got.name.lower().startswith("nukex")

    def test_skips_studio_folder(self, tmp_path):
        pf = tmp_path / "pf"
        (pf / "Nuke15.1" / "Nuke15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "Nuke15.1.exe").write_text("ok")
        (pf / "NukeStudio15.1" / "NukeStudio15.1.exe").parent.mkdir(parents=True)
        (pf / "NukeStudio15.1" / "NukeStudio15.1.exe").write_text("bad")

        got = _find_nukex_exe_under_roots([pf])
        assert got is not None
        assert "Studio" not in got.parent.name


class TestFindNukexExeEnv:
    def test_bpe_nukex_exe_override(self, tmp_path, monkeypatch):
        exe = tmp_path / "custom_nukex.exe"
        exe.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe))
        got = find_nukex_exe()
        assert got == exe.resolve()
