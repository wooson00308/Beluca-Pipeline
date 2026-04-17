"""Tests for bpe.core.shotgrid_settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bpe.core.settings import save_settings
from bpe.core.shotgrid_settings import (
    get_shotgrid_settings,
    save_shotgrid_settings,
)


def test_defaults(tmp_app_dir: Path) -> None:
    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://beluca.shotgrid.autodesk.com"
    assert sg["script_name"] == "belucaAPI"
    assert sg["task_content"] == "comp"
    assert sg.get("shot_browser_page_id") == 14100
    assert sg.get("chrome_executable") == ""
    assert sg.get("http_proxy") == ""
    assert sg.get("ca_certs") == ""


def test_studio_json_override(tmp_app_dir: Path) -> None:
    studio_path = tmp_app_dir / "shotgrid_studio.json"
    studio_path.write_text(
        json.dumps(
            {
                "base_url": "https://custom.shotgrid.autodesk.com",
                "script_name": "customAPI",
                "script_key": "customkey123",
            }
        )
    )
    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://custom.shotgrid.autodesk.com"
    assert sg["script_name"] == "customAPI"


def test_settings_json_override(tmp_app_dir: Path) -> None:
    save_settings(
        {
            "shotgrid": {
                "base_url": "https://from-settings.shotgrid.autodesk.com",
            }
        }
    )
    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://from-settings.shotgrid.autodesk.com"
    # Other defaults preserved
    assert sg["task_content"] == "comp"


def test_env_var_override(tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BPE_SHOTGRID_BASE_URL", "https://env.shotgrid.autodesk.com")
    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://env.shotgrid.autodesk.com"


def test_http_proxy_settings_json(tmp_app_dir: Path) -> None:
    save_settings({"shotgrid": {"http_proxy": "proxy.example.com:8080"}})
    sg = get_shotgrid_settings()
    assert sg["http_proxy"] == "proxy.example.com:8080"


def test_http_proxy_env_overrides_settings(
    tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_settings({"shotgrid": {"http_proxy": "https://settings-proxy:8080"}})
    monkeypatch.setenv("BPE_SHOTGRID_HTTP_PROXY", "https://env-proxy:9090")
    sg = get_shotgrid_settings()
    assert sg["http_proxy"] == "https://env-proxy:9090"


def test_ca_certs_env_override(tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BPE_SHOTGRID_CACERTS", "W:\\fake\\merged.pem")
    sg = get_shotgrid_settings()
    assert sg["ca_certs"] == "W:\\fake\\merged.pem"


def test_empty_script_key_ignored(tmp_app_dir: Path) -> None:
    save_settings({"shotgrid": {"script_key": ""}})
    sg = get_shotgrid_settings()
    # Empty string should NOT override the default
    assert sg["script_key"] == "dnolt2flVfbdoehoknpfp)bbc"


def test_save_shotgrid_settings(tmp_app_dir: Path) -> None:
    save_shotgrid_settings({"base_url": "https://saved.shotgrid.autodesk.com"})
    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://saved.shotgrid.autodesk.com"


def test_merge_priority(tmp_app_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env > settings.json > studio.json > defaults."""
    # Studio
    studio_path = tmp_app_dir / "shotgrid_studio.json"
    studio_path.write_text(json.dumps({"base_url": "https://studio.sg.com"}))

    # Settings
    save_settings({"shotgrid": {"base_url": "https://settings.sg.com"}})

    # Env
    monkeypatch.setenv("BPE_SHOTGRID_BASE_URL", "https://env.sg.com")

    sg = get_shotgrid_settings()
    assert sg["base_url"] == "https://env.sg.com"

    # Without env, settings wins
    monkeypatch.delenv("BPE_SHOTGRID_BASE_URL")
    sg2 = get_shotgrid_settings()
    assert sg2["base_url"] == "https://settings.sg.com"
