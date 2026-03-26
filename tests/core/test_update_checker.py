"""Tests for bpe.core.update_checker."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from bpe.core.update_checker import (
    UpdateInfo,
    check_latest_release,
    compare_versions,
    download_release_asset,
)

# ── compare_versions ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "current, latest, expected",
    [
        ("0.4.0", "0.5.0", True),
        ("0.4.0", "0.4.1", True),
        ("0.4.0", "1.0.0", True),
        ("0.4.0", "0.4.0", False),
        ("0.5.0", "0.4.0", False),
        ("1.0.0", "0.9.9", False),
        ("0.4.2", "0.4.3", True),
        ("0.4.3", "0.4.3", False),
    ],
)
def test_compare_versions(current: str, latest: str, expected: bool) -> None:
    assert compare_versions(current, latest) is expected


# ── check_latest_release ─────────────────────────────────────────


def _make_github_response(
    tag: str,
    assets: Optional[List[Dict[str, Any]]] = None,
    body: str = "release notes",
    html_url: str = "https://github.com/example/releases/v1",
) -> bytes:
    payload: Dict[str, Any] = {
        "tag_name": tag,
        "body": body,
        "html_url": html_url,
        "assets": assets or [],
    }
    return json.dumps(payload).encode("utf-8")


class _FakeResponse:
    """urllib.request.urlopen 대용 가짜 응답."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def test_check_new_version_available(monkeypatch: pytest.MonkeyPatch) -> None:
    assets = [
        {
            "name": "BPE-macOS.dmg",
            "browser_download_url": "https://example.com/BPE-macOS.dmg",
        },
    ]
    data = _make_github_response("v1.0.0", assets=assets)

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(data),
    )
    monkeypatch.setattr("bpe.core.update_checker.sys.platform", "darwin")

    result = check_latest_release("0.4.0")

    assert result is not None
    assert isinstance(result, UpdateInfo)
    assert result.latest_version == "1.0.0"
    assert result.download_url == "https://example.com/BPE-macOS.dmg"
    assert result.release_notes == "release notes"


def test_check_already_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _make_github_response("v0.4.0")

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(data),
    )

    assert check_latest_release("0.4.0") is None


def test_check_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: Any, **kw: Any) -> None:
        raise OSError("no network")

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        _raise,
    )

    assert check_latest_release("0.4.0") is None


def test_check_windows_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    assets = [
        {
            "name": "BPE-Windows.zip",
            "browser_download_url": "https://example.com/BPE-Windows.zip",
        },
    ]
    data = _make_github_response("v2.0.0", assets=assets)

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeResponse(data),
    )
    monkeypatch.setattr("bpe.core.update_checker.sys.platform", "win32")

    result = check_latest_release("0.4.0")

    assert result is not None
    assert result.download_url == "https://example.com/BPE-Windows.zip"


# ── download_release_asset ───────────────────────────────────────


class _FakeDownloadResponse:
    """다운로드용 가짜 응답 (Content-Length 포함)."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def __enter__(self) -> "_FakeDownloadResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def test_download_creates_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = b"fake-binary-data" * 100

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeDownloadResponse(content),
    )

    dest = tmp_path / "download" / "BPE-macOS.dmg"
    result = download_release_asset("https://example.com/asset", dest)

    assert result == dest
    assert dest.read_bytes() == content


def test_download_progress_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = b"x" * 1024

    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeDownloadResponse(content),
    )

    progress_values: List[float] = []
    dest = tmp_path / "asset.zip"
    download_release_asset(
        "https://example.com/asset",
        dest,
        progress_cb=progress_values.append,
    )

    assert len(progress_values) > 0
    assert progress_values[-1] == pytest.approx(1.0)


def test_download_overwrites_existing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dest = tmp_path / "existing.zip"
    dest.write_bytes(b"old-content")

    new_content = b"new-content"
    monkeypatch.setattr(
        "bpe.core.update_checker.urllib.request.urlopen",
        lambda *a, **kw: _FakeDownloadResponse(new_content),
    )

    download_release_asset("https://example.com/asset", dest)
    assert dest.read_bytes() == new_content
