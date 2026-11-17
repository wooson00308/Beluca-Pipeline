"""컨펌 창 메모리 한도 — PC 메모리에 맞춰 정한다(설정에 적어 둔 값이 있으면 그 값)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import bpe.core.confirm_memory as cm
import bpe.core.settings as settings_mod
from bpe.core.atomic_io import write_json_file
from bpe.core.confirm_memory import CACHE_MAX_MB, CACHE_MIN_MB, auto_cache_mb, total_memory_mb

GB = 1024


def test_auto_limit_is_half_the_memory_between_4gb_and_32gb() -> None:
    assert auto_cache_mb(128 * GB) == 32 * GB  # 큰 PC 는 32GB 에서 멈춘다
    assert auto_cache_mb(64 * GB) == 32 * GB
    assert auto_cache_mb(60 * GB) == 30 * GB
    assert auto_cache_mb(32 * GB) == 16 * GB
    assert auto_cache_mb(16 * GB) == 8 * GB
    # 작은 PC 도 예전 기본값(4GB)보다 줄지는 않는다
    assert auto_cache_mb(8 * GB) == 4 * GB and auto_cache_mb(4 * GB) == 4 * GB
    # 메모리를 못 읽었으면 예전 기본값
    assert auto_cache_mb(None) == CACHE_MIN_MB and auto_cache_mb(0) == CACHE_MIN_MB
    assert (CACHE_MIN_MB, CACHE_MAX_MB) == (4096, 32768)


def test_total_memory_is_read_once_and_survives_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm, "_total_read", False)
    monkeypatch.setattr(cm, "_total_mb", None)
    real = total_memory_mb()
    assert real is None or real > 256  # 이 시험을 도는 PC 의 실제 메모리
    calls = []

    def _boom() -> Any:
        calls.append(1)
        raise OSError("no sysconf")

    monkeypatch.setattr(cm, "_read_total_memory_mb", _boom)
    assert total_memory_mb() == real and calls == []  # 한 번 읽은 값은 다시 읽지 않는다
    monkeypatch.setattr(cm, "_total_read", False)
    assert total_memory_mb() is None and calls == [1]  # 못 읽어도 터지지 않는다


def test_settings_use_the_auto_limit_unless_a_value_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "total_memory_mb", lambda: 64 * GB)
    # 설정 파일이 없거나 값이 없으면 PC 메모리에 맞춘 값
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 32 * GB
    write_json_file(f, {"confirm": {"list_group": "x"}})
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 32 * GB
    monkeypatch.setattr(settings_mod, "total_memory_mb", lambda: None)
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 4096
    # 직접 적어 둔 값이 있으면 그 값(너무 작은 값만 256 으로 올린다)
    write_json_file(f, {"confirm": {"cache_mb": 12000}})
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 12000
    write_json_file(f, {"confirm": {"cache_mb": 10}})
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 256
    # 못 읽는 값은 없는 것으로 보고 자동 값
    monkeypatch.setattr(settings_mod, "total_memory_mb", lambda: 128 * GB)
    write_json_file(f, {"confirm": {"cache_mb": "많이"}})
    assert settings_mod.get_confirm_settings(f)["cache_mb"] == 32 * GB
    # 다른 칸을 저장해도 한도가 파일에 박히지 않는다(PC 를 바꾸면 그 PC 에 맞게 다시 정해진다)
    write_json_file(f, {})
    settings_mod.save_confirm_settings({"list_group": "y"}, f)
    assert "cache_mb" not in settings_mod.load_settings(f)["confirm"]
