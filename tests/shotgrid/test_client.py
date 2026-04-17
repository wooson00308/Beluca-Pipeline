"""Tests for bpe.shotgrid.client — connection settings & helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bpe.core.settings import save_settings
from bpe.shotgrid.client import connect_from_settings, reset_default_sg, resolve_sudo_login
from bpe.shotgrid.client import test_connection as sg_test_connection
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
        sg._add_entity(
            "HumanUser", {"id": 10, "name": "Kim", "login": "kim", "email": "kim@example.com"}
        )
        assert resolve_sudo_login(sg, 10) == "kim"

    def test_falls_back_to_email(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "HumanUser", {"id": 11, "name": "Lee", "login": "", "email": "lee@example.com"}
        )
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


class TestConnectFromSettingsHttpProxy:
    def test_passes_none_when_http_proxy_empty(
        self, tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BPE_SHOTGRID_NO_SYSTEM_PROXY", "1")
        monkeypatch.setattr("bpe.shotgrid.client.resolve_shotgun_ca_certs_path", lambda _s: None)
        mock_cls = MagicMock()
        monkeypatch.setattr("bpe.shotgrid.client.Shotgun", mock_cls)
        connect_from_settings("", "", "")
        _args, kwargs = mock_cls.call_args
        assert kwargs.get("http_proxy") is None
        assert kwargs.get("ca_certs") is None

    def test_passes_http_proxy_from_merged_settings(
        self, tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_settings({"shotgrid": {"http_proxy": "corp-proxy:8080"}})
        monkeypatch.setattr("bpe.shotgrid.client.resolve_shotgun_ca_certs_path", lambda _s: None)
        mock_cls = MagicMock()
        monkeypatch.setattr("bpe.shotgrid.client.Shotgun", mock_cls)
        connect_from_settings("", "", "")
        _args, kwargs = mock_cls.call_args
        assert kwargs.get("http_proxy") == "corp-proxy:8080"


class TestConnectFromSettingsCaCerts:
    def test_passes_ca_certs_from_settings(
        self, tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pem = tmp_app_dir / "custom.pem"
        pem.write_bytes(b"-----BEGIN CERTIFICATE-----\nYQ==\n-----END CERTIFICATE-----\n")
        save_settings({"shotgrid": {"ca_certs": str(pem)}})
        monkeypatch.setenv("BPE_SHOTGRID_NO_SYSTEM_PROXY", "1")
        mock_cls = MagicMock()
        monkeypatch.setattr("bpe.shotgrid.client.Shotgun", mock_cls)
        connect_from_settings("", "", "")
        _args, kwargs = mock_cls.call_args
        assert kwargs.get("ca_certs") == str(pem.resolve())
