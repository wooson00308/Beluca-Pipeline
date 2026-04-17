"""Tests for bpe.core.shotgrid_proxy."""

from __future__ import annotations

import sys
import urllib.request

import pytest

from bpe.core.shotgrid_proxy import (
    _parse_proxy_server_value,
    normalize_proxy_for_shotgun,
    resolve_shotgun_http_proxy,
    shotgrid_http_proxy_diag,
)


def test_normalize_strips_scheme() -> None:
    assert normalize_proxy_for_shotgun("http://host:8080") == "host:8080"
    assert normalize_proxy_for_shotgun("https://host:8080/") == "host:8080"


def test_normalize_preserves_auth_form() -> None:
    assert normalize_proxy_for_shotgun("user:pass@host:8080") == "user:pass@host:8080"


def test_explicit_wins_over_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "http://wrong:1"},
    )
    r = resolve_shotgun_http_proxy({"http_proxy": "right:2"})
    assert r == "right:2"


def test_system_proxy_when_no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "http://corp.example.com:8080"},
    )
    r = resolve_shotgun_http_proxy({"http_proxy": ""})
    assert r == "corp.example.com:8080"


def test_no_system_when_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BPE_SHOTGRID_NO_SYSTEM_PROXY", "1")
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "http://corp.example.com:8080"},
    )
    assert resolve_shotgun_http_proxy({"http_proxy": ""}) is None


def test_parse_proxy_server_semicolon_prefers_https() -> None:
    assert _parse_proxy_server_value("http=p:80;https=hs:443") == "hs:443"


def test_parse_proxy_server_plain_host() -> None:
    assert _parse_proxy_server_value("proxy1:8080") == "proxy1:8080"


def test_windows_registry_fallback_when_getproxies_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(
        "bpe.core.shotgrid_proxy._windows_inet_settings_proxy_url",
        lambda: "http://regproxy.example.com:9999",
    )
    monkeypatch.setattr("bpe.core.shotgrid_proxy._windows_winhttp_default_proxy_url", lambda: "")
    r = resolve_shotgun_http_proxy({"http_proxy": ""})
    assert r == "regproxy.example.com:9999"


def test_windows_winhttp_fallback_when_inet_and_getproxies_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr("bpe.core.shotgrid_proxy._windows_inet_settings_proxy_url", lambda: "")
    monkeypatch.setattr(
        "bpe.core.shotgrid_proxy._windows_winhttp_default_proxy_url",
        lambda: "http://whproxy.example.com:3128",
    )
    r = resolve_shotgun_http_proxy({"http_proxy": ""})
    assert r == "whproxy.example.com:3128"


def test_shotgrid_http_proxy_diag_getproxies_nonempty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"http": "http://p.example.com:1"},
    )
    d = shotgrid_http_proxy_diag({"http_proxy": ""})
    assert d["getproxies_nonempty"] is True


def test_shotgrid_http_proxy_diag_explicit_len() -> None:
    d = shotgrid_http_proxy_diag({"http_proxy": "  ab  "})
    assert d["explicit_proxy_len"] == 2


def test_shotgrid_http_proxy_diag_pac_only_suspected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "bpe.core.shotgrid_proxy._wininet_proxy_registry_snapshot",
        lambda: {
            "inet_proxy_enable": 1,
            "inet_proxy_server_len": 0,
            "inet_autoconfig_url_len": 12,
        },
    )
    monkeypatch.setattr(
        "bpe.core.shotgrid_proxy._windows_winhttp_default_proxy_url",
        lambda: "",
    )
    d = shotgrid_http_proxy_diag({"http_proxy": ""})
    assert d["pac_only_suspected"] is True


def test_shotgrid_http_proxy_diag_non_windows_no_pac_flag() -> None:
    if sys.platform == "win32":
        pytest.skip("non-Windows branch")
    d = shotgrid_http_proxy_diag({"http_proxy": ""})
    assert d["pac_only_suspected"] is False
    assert d.get("winhttp_named_proxy_nonempty") is False
    assert "inet_proxy_enable" not in d or d.get("inet_proxy_enable") is None
