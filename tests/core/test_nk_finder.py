# @cursor-change: 2026-07-23, 0.8.28, find_all_nukex_launchers/launcher 인자 테스트 추가
"""Tests for bpe.core.nk_finder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bpe.core.nk_finder import (
    _NK_VERSION_RE,
    NukexLauncher,
    _find_nukex_exe_under_roots,
    _find_server_root_from_drive_roots,
    _nk_is_junk_file,
    find_all_nukex_launchers,
    find_comp_render_mov,
    find_latest_comp_version_display,
    find_latest_nk_and_open,
    find_latest_nk_path,
    find_nukex_exe,
    find_nukex_exe_and_args,
    find_nukex_install_dir,
    find_plate_mov,
    find_server_root_auto,
    find_shot_folder,
    find_shot_folder_by_task,
    parse_sg_path_to_movie_string,
    patch_nk_string_trim_in_place,
    patch_string_trim_file_knob_script,
    patch_string_trim_in_nk_text,
    patch_string_trim_tcl_source,
    resolve_comp_renders_dir,
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


# ── find_latest_comp_version_display ───────────────────────────────


class TestFindLatestCompVersionDisplay:
    """find_latest_nk_path와 동일한 기준의 표시 문자열."""

    def _make_shot_tree(self, tmp_path: Path, shot_name: str) -> Path:
        ep = shot_name.split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / shot_name.upper()
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        nuke_dir.mkdir(parents=True)
        return shot_root

    def test_returns_none_when_no_nk(self, tmp_path):
        self._make_shot_tree(tmp_path, "E01_S01_004")
        assert find_latest_comp_version_display("E01_S01_004", "PRJ", str(tmp_path)) is None

    def test_returns_none_when_missing_args(self):
        assert find_latest_comp_version_display("", "PRJ", "/x") is None
        assert find_latest_comp_version_display("S", "PRJ", "") is None

    def test_returns_latest_v_from_nk_files(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_001")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        (nuke_dir / "E01_S01_001_comp_v001.nk").write_text("v1")
        (nuke_dir / "E01_S01_001_comp_v002.nk").write_text("v2")
        (nuke_dir / "E01_S01_001_comp_v003.nk").write_text("v3")

        assert find_latest_comp_version_display("E01_S01_001", "PRJ", str(tmp_path)) == "v003"

    def test_returns_v_from_version_subfolder(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E102_S017_0120")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        (nuke_dir / "v001" / "E102_S017_0120_comp_v001.nk").parent.mkdir(parents=True)
        (nuke_dir / "v001" / "E102_S017_0120_comp_v001.nk").write_text("1")
        (nuke_dir / "v003" / "E102_S017_0120_comp_v003.nk").parent.mkdir(parents=True)
        (nuke_dir / "v003" / "E102_S017_0120_comp_v003.nk").write_text("3")

        assert find_latest_comp_version_display("E102_S017_0120", "PRJ", str(tmp_path)) == "v003"

    def test_returns_none_when_no_v_in_name_or_parent(self, tmp_path):
        shot_root = self._make_shot_tree(tmp_path, "E01_S01_002")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        (nuke_dir / "new.nk").write_text("new")

        assert find_latest_comp_version_display("E01_S01_002", "PRJ", str(tmp_path)) is None


# ── find_comp_render_mov ─────────────────────────────────────────


class TestFindCompRenderMov:
    def _make_renders_tree(self, tmp_path: Path, shot_name: str) -> Path:
        ep = shot_name.split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / shot_name.upper()
        renders = shot_root / "comp" / "devl" / "renders"
        renders.mkdir(parents=True)
        return shot_root

    def test_picks_highest_version_suffix(self, tmp_path):
        """version_code 없이 호출 시 최신 버전(폴백용)."""
        self._make_renders_tree(tmp_path, "E01_S01_001")
        rd = tmp_path / "PRJ" / "04_sq" / "E01" / "E01_S01_001" / "comp" / "devl" / "renders"
        (rd / "E01_S01_001_comp_v001.mov").write_bytes(b"a")
        (rd / "E01_S01_001_comp_v007.mov").write_bytes(b"b")
        (rd / "E01_S01_001_comp_v003.mov").write_bytes(b"c")

        result = find_comp_render_mov("E01_S01_001", "PRJ", str(tmp_path))
        assert result is not None
        assert "v007" in result.name

    def test_picks_exact_version_code(self, tmp_path):
        """version_code 지정 시 해당 버전 파일 반환."""
        self._make_renders_tree(tmp_path, "E01_S01_001")
        rd = tmp_path / "PRJ" / "04_sq" / "E01" / "E01_S01_001" / "comp" / "devl" / "renders"
        (rd / "E01_S01_001_comp_v001.mov").write_bytes(b"a")
        (rd / "E01_S01_001_comp_v007.mov").write_bytes(b"b")
        (rd / "E01_S01_001_comp_v003.mov").write_bytes(b"c")

        result = find_comp_render_mov(
            "E01_S01_001", "PRJ", str(tmp_path), version_code="E01_S01_001_comp_v003"
        )
        assert result is not None
        assert "v003" in result.name

    def test_version_code_not_found_returns_none(self, tmp_path):
        """version_code 지정했는데 해당 파일 없으면 None."""
        self._make_renders_tree(tmp_path, "E01_S01_001")
        rd = tmp_path / "PRJ" / "04_sq" / "E01" / "E01_S01_001" / "comp" / "devl" / "renders"
        (rd / "E01_S01_001_comp_v001.mov").write_bytes(b"a")

        result = find_comp_render_mov(
            "E01_S01_001", "PRJ", str(tmp_path), version_code="E01_S01_001_comp_v099"
        )
        assert result is None

    def test_returns_none_when_no_mov(self, tmp_path):
        self._make_renders_tree(tmp_path, "E01_S01_002")
        assert find_comp_render_mov("E01_S01_002", "PRJ", str(tmp_path)) is None

    def test_exclude_lut_stem_prefers_non_lut(self, tmp_path):
        """exclude_lut_stem=True면 같은 버전에서 _lut.mov를 건너뛴다."""
        shot = "EP01_S08_C0070"
        ep = "EP01"
        shot_root = tmp_path / "CRS2_032" / "04_sq" / ep / shot
        rd = shot_root / "comp" / "devl" / "renders"
        rd.mkdir(parents=True)
        non_lut = rd / f"{shot}_comp_v003.mov"
        lut = rd / f"{shot}_comp_v003_lut.mov"
        non_lut.write_bytes(b"a")
        lut.write_bytes(b"b")
        # lut가 더 최신이어도 non-lut 선택
        import os
        import time

        older = time.time() - 100
        newer = time.time()
        os.utime(non_lut, (older, older))
        os.utime(lut, (newer, newer))

        result = find_comp_render_mov(shot, "CRS2_032", str(tmp_path), exclude_lut_stem=True)
        assert result is not None
        assert result.name == f"{shot}_comp_v003.mov"
        assert "_lut" not in result.stem

    def test_exclude_lut_stem_only_lut_returns_none(self, tmp_path):
        shot = "EP01_S08_C0070"
        ep = "EP01"
        rd = tmp_path / "CRS2_032" / "04_sq" / ep / shot / "comp" / "devl" / "renders"
        rd.mkdir(parents=True)
        (rd / f"{shot}_comp_v003_lut.mov").write_bytes(b"b")

        assert find_comp_render_mov(shot, "CRS2_032", str(tmp_path), exclude_lut_stem=True) is None

    def test_without_exclude_lut_mtime_can_pick_lut(self, tmp_path):
        """기본(False)이면 다른 프로젝트처럼 mtime 우선 — lut가 최신이면 lut."""
        shot = "E01_S01_001"
        self._make_renders_tree(tmp_path, shot)
        rd = tmp_path / "PRJ" / "04_sq" / "E01" / shot / "comp" / "devl" / "renders"
        non_lut = rd / f"{shot}_comp_v003.mov"
        lut = rd / f"{shot}_comp_v003_lut.mov"
        non_lut.write_bytes(b"a")
        lut.write_bytes(b"b")
        import os
        import time

        older = time.time() - 100
        newer = time.time()
        os.utime(non_lut, (older, older))
        os.utime(lut, (newer, newer))

        result = find_comp_render_mov(shot, "PRJ", str(tmp_path))
        assert result is not None
        assert result.name.endswith("_lut.mov")

    def test_returns_none_when_renders_missing(self, tmp_path):
        ep = "E01_S01_003".split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / "E01_S01_003"
        (shot_root / "comp" / "devl" / "nuke").mkdir(parents=True)
        assert find_comp_render_mov("E01_S01_003", "PRJ", str(tmp_path)) is None


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
        (pf / "Nuke14.0" / "NukeX14.0.exe").parent.mkdir(parents=True)
        (pf / "Nuke14.0" / "NukeX14.0.exe").write_text("exe")
        (pf / "Nuke15.1" / "NukeX15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "NukeX15.1.exe").write_text("exe")

        got = _find_nukex_exe_under_roots([pf])
        assert got is not None
        assert "15.1" in got.parent.name
        assert got.name.lower().startswith("nukex")

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
        (pf / "Nuke15.1" / "NukeX15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "NukeX15.1.exe").write_text("ok")
        (pf / "NukeStudio15.1" / "NukeStudio15.1.exe").parent.mkdir(parents=True)
        (pf / "NukeStudio15.1" / "NukeStudio15.1.exe").write_text("bad")

        got = _find_nukex_exe_under_roots([pf])
        assert got is not None
        assert "Studio" not in got.parent.name

    def test_plain_nuke_exe_only_returns_none(self, tmp_path):
        """일반 Nuke(Nuke*.exe)만 있으면 NukeX를 쓰지 않는다."""
        pf = tmp_path / "pf"
        (pf / "Nuke15.1" / "Nuke15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "Nuke15.1.exe").write_text("no")

        assert _find_nukex_exe_under_roots([pf]) is None


class TestFindNukexExeEnv:
    def test_bpe_nukex_exe_override(self, tmp_path, monkeypatch):
        exe = tmp_path / "NukeX_custom.exe"
        exe.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe))
        got = find_nukex_exe()
        assert got == exe.resolve()

    def test_bpe_nukex_exe_rejects_plain_nuke_on_windows(self, tmp_path, monkeypatch):
        exe = tmp_path / "Nuke15.1.exe"
        exe.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe))
        monkeypatch.setattr("sys.platform", "win32")
        assert find_nukex_exe() is None


# ── find_nukex_install_dir ───────────────────────────────────────


class TestFindNukexInstallDir:
    def test_matches_exe_parent_under_roots(self, tmp_path, monkeypatch):
        pf = tmp_path / "pf"
        (pf / "Nuke15.1" / "NukeX15.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke15.1" / "NukeX15.1.exe").write_text("exe")
        monkeypatch.setattr("bpe.core.nk_finder._nuke_program_dirs", lambda: [pf])
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)
        got = find_nukex_install_dir()
        assert got == (pf / "Nuke15.1").resolve()

    def test_bpe_nukex_exe_override_parent(self, tmp_path, monkeypatch):
        exe = tmp_path / "NukeX_custom.exe"
        exe.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe))
        got = find_nukex_install_dir()
        assert got == exe.parent.resolve()


# ── find_nukex_exe_and_args / Start Menu ─────────────────────────


class TestFindNukexViaStartMenu:
    def test_nuke14_style_exe_with_nukex_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        sm = tmp_path / "sm" / "The Foundry"
        (sm / "Nuke 14.1v4").mkdir(parents=True)
        (sm / "Nuke 14.1v4" / "NukeX 14.1v4.lnk").write_text("")
        pf = tmp_path / "pf"
        (pf / "Nuke14.1v4" / "Nuke14.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke14.1v4" / "Nuke14.1.exe").write_text("exe")
        monkeypatch.setattr("bpe.core.nk_finder._start_menu_foundry_root", lambda: sm)
        monkeypatch.setattr("bpe.core.nk_finder._nuke_program_dirs", lambda: [pf])
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)
        exe, args = find_nukex_exe_and_args()
        assert exe is not None
        assert exe.name == "Nuke14.1.exe"
        assert args == ["--nukex"]

    def test_start_menu_without_matching_exe_falls_back_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        sm = tmp_path / "sm" / "The Foundry"
        (sm / "Nuke 14.1v4").mkdir(parents=True)
        (sm / "Nuke 14.1v4" / "NukeX 14.1v4.lnk").write_text("")
        monkeypatch.setattr("bpe.core.nk_finder._start_menu_foundry_root", lambda: sm)
        monkeypatch.setattr(
            "bpe.core.nk_finder._nuke_program_dirs",
            lambda: [tmp_path / "empty_pf"],
        )
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)
        exe, args = find_nukex_exe_and_args()
        assert exe is None
        assert args == []

    def test_bpe_nukex_exe_override_skips_start_menu(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        sm = tmp_path / "sm" / "The Foundry"
        (sm / "Nuke 14.1v4").mkdir(parents=True)
        (sm / "Nuke 14.1v4" / "NukeX 14.1v4.lnk").write_text("")
        exe_good = tmp_path / "NukeX15.1.exe"
        exe_good.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe_good))
        monkeypatch.setattr("bpe.core.nk_finder._start_menu_foundry_root", lambda: sm)
        exe, args = find_nukex_exe_and_args()
        assert exe == exe_good.resolve()
        assert args == []


# ── find_shot_folder ──────────────────────────────────────────────


class TestFindShotFolder:
    def test_prefers_comp_devl_nuke(self, tmp_path):
        ep = "E01_S01_001".split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / "E01_S01_001"
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        nuke_dir.mkdir(parents=True)
        got = find_shot_folder("E01_S01_001", "PRJ", str(tmp_path))
        assert got == nuke_dir.resolve()

    def test_falls_back_to_shot_root(self, tmp_path):
        ep = "E01_S01_002".split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / "E01_S01_002"
        shot_root.mkdir(parents=True)
        got = find_shot_folder("E01_S01_002", "PRJ", str(tmp_path))
        assert got == shot_root.resolve()

    def test_heuristic_when_standard_path_missing(self, tmp_path):
        shot = tmp_path / "PRJ" / "extra" / "E99_S99_099"
        shot.mkdir(parents=True)
        got = find_shot_folder("E99_S99_099", "PRJ", str(tmp_path))
        assert got is not None
        assert got.name == "E99_S99_099"

    def test_returns_none_for_missing_args(self):
        assert find_shot_folder("", "PRJ", "/x") is None
        assert find_shot_folder("S", "PRJ", "") is None


class TestFindShotFolderByTask:
    """마이테스크 「폴더 열기」 전용 — 태스크별 디렉터리."""

    def _make_standard_shot(self, tmp_path: Path, shot_code: str) -> Path:
        ep = shot_code.split("_")[0].upper()
        return tmp_path / "PRJ" / "04_sq" / ep / shot_code

    def test_comp_opens_comp_devl(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_010")
        devl = shot_root / "comp" / "devl"
        devl.mkdir(parents=True)
        got = find_shot_folder_by_task("E01_S01_010", "PRJ", str(tmp_path), "Comp")
        assert got == devl.resolve()

    def test_comp_case_insensitive(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_011")
        devl = shot_root / "comp" / "devl"
        devl.mkdir(parents=True)
        assert (
            find_shot_folder_by_task("E01_S01_011", "PRJ", str(tmp_path), "COMP") == devl.resolve()
        )

    def test_comp_fallback_shot_root_when_devl_missing(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_012")
        shot_root.mkdir(parents=True)
        got = find_shot_folder_by_task("E01_S01_012", "PRJ", str(tmp_path), "comp")
        assert got == shot_root.resolve()

    def test_fx_opens_fx_dir_case_variants(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_020")
        fx_dir = shot_root / "fx"
        fx_dir.mkdir(parents=True)
        for tc in ("fx", "Fx", "FX"):
            got = find_shot_folder_by_task("E01_S01_020", "PRJ", str(tmp_path), tc)
            assert got == fx_dir.resolve()

    def test_matte_opens_matte_dir_case_variants(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_030")
        matte_dir = shot_root / "matte"
        matte_dir.mkdir(parents=True)
        for tc in ("matte", "Matte", "MATTE"):
            got = find_shot_folder_by_task("E01_S01_030", "PRJ", str(tmp_path), tc)
            assert got == matte_dir.resolve()

    def test_other_task_delegates_to_find_shot_folder(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_040")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        nuke_dir.mkdir(parents=True)
        got = find_shot_folder_by_task("E01_S01_040", "PRJ", str(tmp_path), "Lighting")
        assert got == nuke_dir.resolve()

    def test_empty_task_content_delegates_to_find_shot_folder(self, tmp_path):
        shot_root = self._make_standard_shot(tmp_path, "E01_S01_041")
        nuke_dir = shot_root / "comp" / "devl" / "nuke"
        nuke_dir.mkdir(parents=True)
        got = find_shot_folder_by_task("E01_S01_041", "PRJ", str(tmp_path), "")
        assert got == nuke_dir.resolve()

    def test_returns_none_for_missing_args(self):
        assert find_shot_folder_by_task("", "PRJ", "/x", "comp") is None
        assert find_shot_folder_by_task("S", "PRJ", "", "comp") is None


# ── find_plate_mov ───────────────────────────────────────────────


class TestFindPlateMov:
    def _make_plate_org(self, tmp_path: Path, shot_name: str) -> Path:
        ep = shot_name.split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / shot_name.upper()
        plate_org = shot_root / "plate" / "org"
        plate_org.mkdir(parents=True)
        return plate_org

    def test_prefers_highest_version_with_mov(self, tmp_path):
        plate_org = self._make_plate_org(tmp_path, "E01_S01_010")
        (plate_org / "v001" / "mov").mkdir(parents=True)
        (plate_org / "v001" / "mov" / "a.mov").write_bytes(b"x")
        (plate_org / "v003" / "mov").mkdir(parents=True)
        (plate_org / "v003" / "mov" / "b.mov").write_bytes(b"y")

        result = find_plate_mov("E01_S01_010", "PRJ", str(tmp_path))
        assert result is not None
        assert "v003" in str(result).replace("\\", "/")
        assert result.name == "b.mov"

    def test_falls_back_when_newer_version_has_no_mov(self, tmp_path):
        plate_org = self._make_plate_org(tmp_path, "E01_S01_011")
        (plate_org / "v002" / "mov").mkdir(parents=True)
        (plate_org / "v001" / "mov").mkdir(parents=True)
        (plate_org / "v001" / "mov" / "only.mov").write_bytes(b"z")

        result = find_plate_mov("E01_S01_011", "PRJ", str(tmp_path))
        assert result is not None
        assert result.name == "only.mov"

    def test_returns_none_when_no_mov(self, tmp_path):
        plate_org = self._make_plate_org(tmp_path, "E01_S01_012")
        (plate_org / "v001" / "mov").mkdir(parents=True)

        assert find_plate_mov("E01_S01_012", "PRJ", str(tmp_path)) is None

    def test_returns_none_missing_plate_org(self, tmp_path):
        ep = "E01_S01_013".split("_")[0].upper()
        shot_root = tmp_path / "PRJ" / "04_sq" / ep / "E01_S01_013"
        shot_root.mkdir(parents=True)

        assert find_plate_mov("E01_S01_013", "PRJ", str(tmp_path)) is None


# ── patch_nk_string_trim_in_place ────────────────────────────────


_OLD_MOV = (
    r' file "\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]'
    r'/renders/\[string trim \[file tail \[value root.name]] .nk].mov"'
)
_OLD_EXR = (
    r' file "\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]'
    r"/renders/\[string trim \[file tail \[value root.name]] .nk]"
    r'/\[string trim \[file tail \[value root.name]] .nk].%04d.exr"'
)
_NEW_MOV = (
    r' file "\[file dirname \[file dirname \[file dirname \[value root.name]]]]'
    r'/renders/\[file rootname \[file tail \[value root.name]]].mov"'
)
_NEW_EXR = (
    r' file "\[file dirname \[file dirname \[file dirname \[value root.name]]]]'
    r"/renders/\[file rootname \[file tail \[value root.name]]]"
    r'/\[file rootname \[file tail \[value root.name]]].%04d.exr"'
)


class TestPatchNkStringTrimInPlace:
    def _make_nk(self, tmp_path: Path, content: str) -> Path:
        nk = tmp_path / "shot.nk"
        nk.write_text(content, encoding="utf-8")
        return nk

    def test_patches_mov_write(self, tmp_path):
        nk = self._make_nk(tmp_path, f"Write {{\n{_OLD_MOV}\n name eo7Write1\n}}\n")
        assert patch_nk_string_trim_in_place(nk) is True
        content = nk.read_text(encoding="utf-8")
        assert "string trim" not in content
        assert "file dirname" in content

    def test_patches_exr_write(self, tmp_path):
        nk = self._make_nk(tmp_path, f"Write {{\n{_OLD_EXR}\n name Write2\n}}\n")
        assert patch_nk_string_trim_in_place(nk) is True
        content = nk.read_text(encoding="utf-8")
        assert "string trim" not in content
        assert ".%04d.exr" in content

    def test_no_change_when_already_patched(self, tmp_path):
        nk = self._make_nk(tmp_path, f"Write {{\n{_NEW_MOV}\n name eo7Write1\n}}\n")
        assert patch_nk_string_trim_in_place(nk) is False

    def test_patches_both_write_nodes(self, tmp_path):
        content = (
            f"Write {{\n{_OLD_MOV}\n name eo7Write1\n}}\nWrite {{\n{_OLD_EXR}\n name Write2\n}}\n"
        )
        nk = self._make_nk(tmp_path, content)
        assert patch_nk_string_trim_in_place(nk) is True
        patched = nk.read_text(encoding="utf-8")
        assert "string trim" not in patched
        assert ".mov" in patched
        assert ".%04d.exr" in patched


class TestPatchStringTrimAllExtensions:
    """regex 기반 확장자 무관 패치."""

    _OLD_DPX = (
        r' file "\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]'
        r"/renders/\[string trim \[file tail \[value root.name]] .nk]"
        r'/\[string trim \[file tail \[value root.name]] .nk].%04d.dpx"'
    )

    def test_patches_dpx_sequence_in_nk_body(self):
        body = f"Write {{\n{self._OLD_DPX}\n name Write1\n}}\n"
        out = patch_string_trim_in_nk_text(body)
        assert "string trim" not in out
        assert "file dirname" in out
        assert ".%04d.dpx" in out

    def test_patches_tiff_hash_frames(self):
        old = (
            r' file "\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]'
            r"/renders/\[string trim \[file tail \[value root.name]] .nk]"
            r'/\[string trim \[file tail \[value root.name]] .nk].####.tiff"'
        )
        body = f"Write {{\n{old}\n name W\n}}\n"
        out = patch_string_trim_in_nk_text(body)
        assert "string trim" not in out
        assert ".####.tiff" in out

    def test_patches_percent_d_no_pad(self):
        old = (
            r' file "\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]'
            r"/renders/\[string trim \[file tail \[value root.name]] .nk]"
            r'/\[string trim \[file tail \[value root.name]] .nk].%d.exr"'
        )
        out = patch_string_trim_in_nk_text(f"Write {{\n{old}\n name W\n}}\n")
        assert "string trim" not in out
        assert ".%d.exr" in out

    def test_patch_string_trim_tcl_source_unescaped(self):
        s = (
            "[string trim [value root.name] nuke/[file tail [value root.name]]]"
            "/renders/[string trim [file tail [value root.name]] .nk]/"
            "[string trim [file tail [value root.name]] .nk].%04d.dpx"
        )
        out = patch_string_trim_tcl_source(s)
        assert "string trim" not in out
        assert "[file dirname [file dirname [file dirname [value root.name]]]]" in out

    def test_patch_string_trim_file_knob_script_escaped_fallback(self):
        """NK 디스크 형식(``\\[``) 이 ``toScript()`` 에 남는 경우."""
        s = (
            r"\[string trim \[value root.name] nuke/\[file tail \[value root.name]]]"
            r"/renders/\[string trim \[file tail \[value root.name]] .nk]/"
            r"\[string trim \[file tail \[value root.name]] .nk].%05d.tif"
        )
        out = patch_string_trim_file_knob_script(s)
        assert "string trim" not in out
        assert ".%05d.tif" in out


class TestParseSgPathToMovieString:
    def test_none_and_empty(self) -> None:
        assert parse_sg_path_to_movie_string(None) == ""
        assert parse_sg_path_to_movie_string("") == ""

    def test_plain_path(self) -> None:
        assert parse_sg_path_to_movie_string("W:/renders/x.mov") == "W:/renders/x.mov"


class TestResolveCompRendersDir:
    def test_returns_comp_devl_renders_when_present(self, tmp_path) -> None:
        server_root = tmp_path / "srv"
        project_code = "SNO_015"
        shot_name = "S010_0020"
        shot_root = server_root / project_code / "04_sq" / "S010" / "S010_0020"
        target = shot_root / "comp" / "devl" / "renders"
        target.mkdir(parents=True)
        got = resolve_comp_renders_dir(shot_name, project_code, str(server_root))
        assert got is not None
        assert got.resolve() == target.resolve()


# ── find_all_nukex_launchers ─────────────────────────────────────


class TestFindAllNukexLaunchers:
    def test_multiple_installs_sorted_desc(self, tmp_path, monkeypatch):
        pf = tmp_path / "pf"
        (pf / "Nuke14.0" / "NukeX14.0.exe").parent.mkdir(parents=True)
        (pf / "Nuke14.0" / "NukeX14.0.exe").write_text("exe")
        (pf / "Nuke17.0" / "NukeX17.0.exe").parent.mkdir(parents=True)
        (pf / "Nuke17.0" / "NukeX17.0.exe").write_text("exe")
        monkeypatch.setattr("bpe.core.nk_finder._nuke_program_dirs", lambda: [pf])
        # Start Menu 스캔은 비워둔다 (legacy 경로만 검증).
        monkeypatch.setattr("bpe.core.nk_finder._collect_start_menu_candidates", lambda: [])
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)

        got = find_all_nukex_launchers()
        assert [nl.version for nl in got] == [(17, 0, 0), (14, 0, 0)]
        assert got[0].label == "NukeX 17.0"
        assert got[1].label == "NukeX 14.0"
        assert all(nl.args == [] for nl in got)

    def test_dedupe_by_major_minor_prefers_start_menu(self, tmp_path, monkeypatch):
        pf = tmp_path / "pf"
        (pf / "Nuke14.1" / "NukeX14.1.exe").parent.mkdir(parents=True)
        (pf / "Nuke14.1" / "NukeX14.1.exe").write_text("exe")
        sm_exe = pf / "Nuke14.1" / "Nuke14.1.exe"
        sm_exe.write_text("exe")
        monkeypatch.setattr("bpe.core.nk_finder._nuke_program_dirs", lambda: [pf])
        monkeypatch.setattr(
            "bpe.core.nk_finder._collect_start_menu_candidates",
            lambda: [((14, 1, 4), sm_exe)],
        )
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)

        got = find_all_nukex_launchers()
        # (14, 1) 은 Start Menu 후보가 우선 → --nukex, exe 는 Nuke14.1.exe
        assert len(got) == 1
        assert got[0].args == ["--nukex"]
        assert got[0].exe == sm_exe

    def test_env_override_returns_single(self, tmp_path, monkeypatch):
        exe = tmp_path / "Nuke15.1" / "NukeX_custom.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
        monkeypatch.setenv("BPE_NUKEX_EXE", str(exe))
        # override 시 스캔 함수를 타면 안 된다.
        monkeypatch.setattr(
            "bpe.core.nk_finder._collect_start_menu_candidates",
            lambda: (_ for _ in ()).throw(AssertionError("should not scan")),
        )
        got = find_all_nukex_launchers()
        assert len(got) == 1
        assert got[0].exe == exe.resolve()
        assert got[0].args == []

    def test_empty_when_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bpe.core.nk_finder._nuke_program_dirs", lambda: [tmp_path / "empty"])
        monkeypatch.setattr("bpe.core.nk_finder._collect_start_menu_candidates", lambda: [])
        monkeypatch.delenv("BPE_NUKEX_EXE", raising=False)
        assert find_all_nukex_launchers() == []


# ── find_latest_nk_and_open(launcher=...) ────────────────────────


class TestFindLatestNkAndOpenLauncher:
    def test_uses_given_launcher(self, tmp_path, monkeypatch):
        nk = tmp_path / "shot_v001.nk"
        nk.write_text("nk")
        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr("bpe.core.nk_finder.find_latest_nk_path", lambda *a, **k: nk)
        monkeypatch.setattr(
            "bpe.core.nk_finder.patch_nk_string_trim_in_place", lambda *a, **k: False
        )

        calls = {}

        def fake_popen(args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs

        monkeypatch.setattr("bpe.core.nk_finder.subprocess.Popen", fake_popen)
        # 지정 launcher 를 쓰면 find_nukex_exe_and_args 를 타면 안 된다.
        monkeypatch.setattr(
            "bpe.core.nk_finder.find_nukex_exe_and_args",
            lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
        )

        launcher = NukexLauncher(
            version=(14, 0, 0),
            exe=Path("C:/Program Files/Nuke14.0/NukeX14.0.exe"),
            args=["--nukex"],
            label="NukeX 14.0",
        )
        find_latest_nk_and_open("SHOT", "PRJ", str(tmp_path), launcher=launcher)

        assert calls["args"][0] == str(launcher.exe)
        assert calls["args"][1] == "--nukex"
        assert calls["kwargs"].get("close_fds") is True
