"""Tests for bpe.core.presets."""

from __future__ import annotations

from pathlib import Path

from bpe.core.presets import (
    delete_preset,
    delete_preset_template,
    ensure_store,
    find_matching_preset_keys,
    get_preset,
    load_preset_template,
    load_presets,
    save_preset_template,
    save_presets,
    upsert_preset,
)
from bpe.core.settings import get_presets_dir


def test_ensure_store_creates_dirs(tmp_app_dir: Path) -> None:
    ensure_store()
    assert (get_presets_dir() / "presets.json").exists()


def test_empty_presets(tmp_app_dir: Path) -> None:
    assert load_presets() == {}


def test_save_and_load(tmp_app_dir: Path) -> None:
    data = {"SBS_030": {"fps": "23.976", "project_code": "SBS_030"}}
    save_presets(data)
    loaded = load_presets()
    assert loaded["SBS_030"]["fps"] == "23.976"


def test_upsert_and_get(tmp_app_dir: Path) -> None:
    upsert_preset("TEST", {"fps": "24"})
    p = get_preset("TEST")
    assert p is not None
    assert p["fps"] == "24"

    upsert_preset("TEST", {"fps": "30"})
    assert get_preset("TEST")["fps"] == "30"


def test_delete_preset(tmp_app_dir: Path) -> None:
    upsert_preset("DEL_ME", {"fps": "24"})
    assert delete_preset("DEL_ME") is True
    assert get_preset("DEL_ME") is None
    assert delete_preset("DEL_ME") is False


def test_get_nonexistent(tmp_app_dir: Path) -> None:
    assert get_preset("NOPE") is None


class TestFindMatchingPresetKeys:
    """find_matching_preset_keys 매칭 규칙 검증."""

    def test_exact_match_only(self) -> None:
        presets = {"SHWEQ_023": {}, "OTHER_001": {}}
        assert find_matching_preset_keys(presets, "shweq_023") == ["SHWEQ_023"]

    def test_exact_and_suffix(self) -> None:
        presets = {"SHWEQ_023": {}, "SHWEQ_023_AI": {}, "OTHER_001": {}}
        result = find_matching_preset_keys(presets, "shweq_023")
        # 정확 일치가 앞에, 나머지는 알파벳 순
        assert result == ["SHWEQ_023", "SHWEQ_023_AI"]

    def test_suffix_only_no_exact(self) -> None:
        presets = {"SHWEQ_023_AI": {}, "SHWEQ_023_VFX": {}}
        result = find_matching_preset_keys(presets, "SHWEQ_023")
        assert result == ["SHWEQ_023_AI", "SHWEQ_023_VFX"]

    def test_no_underscore_boundary_prevents_overmatch(self) -> None:
        # SHWEQ_0234 는 SHWEQ_023_으로 시작하지 않으므로 매칭 안 됨
        presets = {"SHWEQ_0234": {}, "SHWEQ_023": {}}
        result = find_matching_preset_keys(presets, "shweq_023")
        assert result == ["SHWEQ_023"]

    def test_different_project_not_matched(self) -> None:
        presets = {"MVK_028": {}, "MVK_028_AI": {}, "SBS_030": {}}
        result = find_matching_preset_keys(presets, "SBS_030")
        assert result == ["SBS_030"]

    def test_empty_project_code(self) -> None:
        presets = {"SHWEQ_023": {}}
        assert find_matching_preset_keys(presets, "") == []
        assert find_matching_preset_keys(presets, "   ") == []

    def test_empty_presets(self) -> None:
        assert find_matching_preset_keys({}, "SHWEQ_023") == []

    def test_case_insensitive_matching(self) -> None:
        presets = {"SHWEQ_023": {}, "SHWEQ_023_AI": {}}
        # 소문자 project_code도 매칭
        assert find_matching_preset_keys(presets, "shweq_023") == [
            "SHWEQ_023",
            "SHWEQ_023_AI",
        ]

    def test_exact_match_is_first_even_if_multiple_suffixes(self) -> None:
        presets = {"PROJ_A": {}, "PROJ_A_AI": {}, "PROJ_A_VFX": {}}
        result = find_matching_preset_keys(presets, "PROJ_A")
        assert result[0] == "PROJ_A"
        assert set(result) == {"PROJ_A", "PROJ_A_AI", "PROJ_A_VFX"}


def test_preset_template_lifecycle(tmp_app_dir: Path) -> None:
    assert load_preset_template("T1") is None

    save_preset_template("T1", "Root {\n fps 24\n}")
    content = load_preset_template("T1")
    assert content is not None
    assert "fps 24" in content

    delete_preset_template("T1")
    assert load_preset_template("T1") is None
