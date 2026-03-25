"""Tests for bpe.shotgrid.parser — shot code & version name extraction."""

from __future__ import annotations

import pytest

from bpe.shotgrid.parser import parse_shot_code_from_filename, parse_version_name_from_filename

# ── parse_shot_code_from_filename ────────────────────────────────────


class TestParseShotCode:
    """Shot code extraction from filenames and paths."""

    @pytest.mark.parametrize(
        "filename, expected",
        [
            # Pattern 1: E###_S###_####
            ("E107_S022_0080_comp_v001.mov", "E107_S022_0080"),
            ("e107_s022_0080.exr", "e107_s022_0080"),
            # Pattern 2: EP##_s##_c####
            ("EP09_s06_c0030_comp_v003.mov", "EP09_s06_c0030"),
            ("EP09_s16_c0130_comp.mov", "EP09_s16_c0130"),
            # Pattern 3: short EP variant
            ("EP01_s02_c013.mov", "EP01_s02_c013"),
            # Pattern 4: show_###_###_#### (3-segment)
            ("TLS_101_029_0005_comp_v003.mov", "TLS_101_029_0005"),
            ("ABC_12_34_56_something.exr", "ABC_12_34_56"),
            # Pattern 5: E###_S### (2-part)
            ("E107_S022_comp_v001.mov", "E107_S022"),
            # No match
            ("random_file_v001.mov", None),
            ("", None),
        ],
    )
    def test_basic_patterns(self, filename: str, expected: str | None) -> None:
        assert parse_shot_code_from_filename(filename) == expected

    def test_path_directory_fallback(self) -> None:
        """If the filename has no shot code, walk directory parts."""
        path = "/projects/EP09_s06_c0030/renders/comp_v001.mov"
        assert parse_shot_code_from_filename(path) == "EP09_s06_c0030"

    def test_stem_takes_priority(self) -> None:
        """Stem match wins over directory match."""
        path = "/projects/E107_S022/renders/TLS_101_029_0005_comp_v001.mov"
        assert parse_shot_code_from_filename(path) == "TLS_101_029_0005"


# ── parse_version_name_from_filename ─────────────────────────────────


class TestParseVersionName:
    def test_strips_extension(self) -> None:
        assert (
            parse_version_name_from_filename("E107_S022_0080_comp_v001.mov")
            == "E107_S022_0080_comp_v001"
        )

    def test_sequence_with_frame_number(self) -> None:
        assert (
            parse_version_name_from_filename("E107_S022_0080_comp_v001.1001.mov")
            == "E107_S022_0080_comp_v001.1001"
        )

    def test_no_extension(self) -> None:
        assert parse_version_name_from_filename("just_a_name") == "just_a_name"
