"""Tests for bpe.core.shotgrid_browser — URL build and Chrome launch helpers."""

from __future__ import annotations

from unittest import mock

import pytest

from bpe.core.shotgrid_browser import (
    build_project_overview_url,
    build_shot_canvas_url,
    resolve_chrome_executable,
    try_launch_chrome_app_url,
)


class TestBuildProjectOverviewUrl:
    def test_basic(self) -> None:
        u = build_project_overview_url("https://beluca.shotgrid.autodesk.com", 584)
        assert u == "https://beluca.shotgrid.autodesk.com/page/project_overview?project_id=584"

    def test_strips_trailing_slash_on_base(self) -> None:
        u = build_project_overview_url("https://example.shotgrid.autodesk.com/", 1904)
        assert u == "https://example.shotgrid.autodesk.com/page/project_overview?project_id=1904"

    def test_rejects_http(self) -> None:
        with pytest.raises(ValueError, match="https"):
            build_project_overview_url("http://evil.example", 1)

    def test_rejects_invalid_project_id(self) -> None:
        with pytest.raises(ValueError):
            build_project_overview_url("https://a.b", 0)

    def test_rejects_negative_project_id(self) -> None:
        with pytest.raises(ValueError):
            build_project_overview_url("https://a.b", -1)

    def test_rejects_empty_base(self) -> None:
        with pytest.raises(ValueError):
            build_project_overview_url("", 1)

    def test_rejects_hostless(self) -> None:
        with pytest.raises(ValueError, match="host"):
            build_project_overview_url("https://", 1)


class TestBuildShotCanvasUrl:
    def test_basic(self) -> None:
        u = build_shot_canvas_url("https://beluca.shotgrid.autodesk.com", 14100, 2860442)
        assert u == "https://beluca.shotgrid.autodesk.com/page/14100#Shot_2860442"

    def test_strips_trailing_slash_on_base(self) -> None:
        u = build_shot_canvas_url("https://example.shotgrid.autodesk.com/", "99", 1)
        assert u == "https://example.shotgrid.autodesk.com/page/99#Shot_1"

    def test_rejects_http(self) -> None:
        with pytest.raises(ValueError, match="https"):
            build_shot_canvas_url("http://evil.example/page", 1, 1)

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            build_shot_canvas_url("", 1, 1)
        with pytest.raises(ValueError):
            build_shot_canvas_url("https://a.b", "", 1)
        with pytest.raises(ValueError):
            build_shot_canvas_url("https://a.b", 1, 0)

    def test_rejects_hostless(self) -> None:
        with pytest.raises(ValueError, match="host"):
            build_shot_canvas_url("https://", 1, 1)


class TestTryLaunchChromeAppUrl:
    def test_returns_false_when_no_chrome(self) -> None:
        with mock.patch("bpe.core.shotgrid_browser.resolve_chrome_executable", return_value=None):
            assert not try_launch_chrome_app_url("https://a.b/page/1#Shot_2")

    def test_returns_false_for_non_https(self) -> None:
        fake = mock.Mock()
        fake.is_file.return_value = True
        with mock.patch("bpe.core.shotgrid_browser.resolve_chrome_executable", return_value=fake):
            assert not try_launch_chrome_app_url("http://a.b/")

    def test_popen_called_with_app_flag(self, tmp_path) -> None:
        chrome = tmp_path / "chrome.bin"
        chrome.write_bytes(b"")
        url = "https://x.com/page/1#Shot_9"
        with mock.patch("bpe.core.shotgrid_browser.resolve_chrome_executable", return_value=chrome):
            with mock.patch("bpe.core.shotgrid_browser.subprocess.Popen") as popen:
                assert try_launch_chrome_app_url(url, chrome_executable="")
        popen.assert_called_once()
        args, kwargs = popen.call_args
        assert kwargs.get("shell") is False
        assert args[0][0] == str(chrome)
        assert args[0][1] == f"--app={url}"


class TestResolveChromeExecutable:
    def test_explicit_path(self, tmp_path) -> None:
        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        assert resolve_chrome_executable(str(exe)) == exe
