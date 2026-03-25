"""Tests for bpe.core.shot_builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.core.shot_builder import build_shot_paths, parse_shot_name

# ── parse_shot_name ──────────────────────────────────────────────


class TestParseShotName:
    def test_normal(self):
        result = parse_shot_name("E107_S022_0080")
        assert result == {"ep": "E107", "full": "E107_S022_0080"}

    def test_lowercase_normalised(self):
        result = parse_shot_name("e107_s022_0080")
        assert result is not None
        assert result["ep"] == "E107"
        assert result["full"] == "E107_S022_0080"

    def test_whitespace_stripped(self):
        result = parse_shot_name("  E107_S022_0080  ")
        assert result is not None
        assert result["full"] == "E107_S022_0080"

    def test_two_parts(self):
        result = parse_shot_name("EP01_SH001")
        assert result is not None
        assert result["ep"] == "EP01"

    @pytest.mark.parametrize(
        "bad_input",
        [
            "",
            "   ",
            "NOUNDERSCORES",
            None,
        ],
    )
    def test_invalid_returns_none(self, bad_input):
        assert parse_shot_name(bad_input) is None


# ── build_shot_paths ─────────────────────────────────────────────


class TestBuildShotPaths:
    def test_structure(self):
        paths = build_shot_paths("/server", "PRJ", "E107_S022_0080")
        assert paths is not None
        root = Path("/server/PRJ/04_sq/E107/E107_S022_0080")
        assert paths["shot_root"] == root
        assert paths["nuke_dir"] == root / "comp" / "devl" / "nuke"
        assert paths["plate_hi"] == root / "plate" / "org" / "v001" / "hi"
        assert paths["edit"] == root / "edit"
        assert paths["renders"] == root / "comp" / "devl" / "renders"
        assert paths["element"] == root / "comp" / "devl" / "element"

    def test_all_keys_present(self):
        paths = build_shot_paths("/s", "P", "A_B")
        assert paths is not None
        expected_keys = {"shot_root", "nuke_dir", "plate_hi", "edit", "renders", "element"}
        assert set(paths.keys()) == expected_keys

    def test_invalid_shot_returns_none(self):
        assert build_shot_paths("/s", "P", "NOPE") is None

    def test_values_are_paths(self):
        paths = build_shot_paths("/s", "P", "EP_SH")
        assert paths is not None
        for v in paths.values():
            assert isinstance(v, Path)
