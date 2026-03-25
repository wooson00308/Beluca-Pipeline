"""Tests for bpe.shotgrid.client — connection settings & helpers."""

from __future__ import annotations

import pytest

from bpe.shotgrid.client import reset_default_sg
from bpe.shotgrid.client import test_connection as sg_test_connection
from bpe.shotgrid.client import resolve_sudo_login
from bpe.shotgrid.errors import ShotGridError
from tests.shotgrid.mock_sg import MockShotgun


class TestTestConnection:

    def test_with_project(self) -> None:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 1, "name": "Demo"})
        result = sg_test_connection(sg)
        assert "연결 성공" in result
        assert "Demo" in result

    def test_empty_site(self) -> None:
        sg = MockShotgun()
        result = sg_test_connection(sg)
        assert "연결 성공" in result


class TestResolveSudoLogin:

    def test_returns_login(self) -> None:
        sg = MockShotgun()
        sg._add_entity("HumanUser", {"id": 10, "name": "Kim", "login": "kim", "email": "kim@example.com"})
        assert resolve_sudo_login(sg, 10) == "kim"

    def test_falls_back_to_email(self) -> None:
        sg = MockShotgun()
        sg._add_entity("HumanUser", {"id": 11, "name": "Lee", "login": "", "email": "lee@example.com"})
        assert resolve_sudo_login(sg, 11) == "lee@example.com"

    def test_falls_back_to_fallback(self) -> None:
        sg = MockShotgun()
        sg._add_entity("HumanUser", {"id": 12, "name": "Park", "login": "", "email": ""})
        assert resolve_sudo_login(sg, 12, fallback_login="park_fb") == "park_fb"

    def test_user_not_found_returns_fallback(self) -> None:
        sg = MockShotgun()
        assert resolve_sudo_login(sg, 999, fallback_login="fb") == "fb"

    def test_user_not_found_no_fallback(self) -> None:
        sg = MockShotgun()
        assert resolve_sudo_login(sg, 999) is None


class TestResetDefaultSg:

    def test_no_error_when_no_cache(self) -> None:
        # Should not raise even if nothing is cached
        reset_default_sg()
