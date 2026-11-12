"""conftest 의 방어선 — 격리 없는 테스트는 실제 ShotGrid 에 연결하지 못한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.shotgrid.client import connect_from_settings


def test_real_shotgun_connection_is_blocked(tmp_app_dir: Path) -> None:
    _ = tmp_app_dir
    with pytest.raises(AssertionError, match="실제 ShotGrid"):
        connect_from_settings("https://example.shotgrid.invalid", "script", "key")
