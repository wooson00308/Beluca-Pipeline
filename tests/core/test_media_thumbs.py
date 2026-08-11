"""썸네일 캐시 — 캐시 키/실패 표시/LRU 정리 테스트.

CI 러너에는 ffmpeg 가 없으므로 실제 ffmpeg 는 절대 호출하지 않고 전부 모킹한다
(``test_ai_qc.py`` 와 같은 방식).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

from bpe.core import media_thumbs as mt


def _fake_ok(out_index: int = -1):
    """ffmpeg 성공을 흉내내는 subprocess.run 대역 — 출력 파일을 실제로 만든다."""

    def _run(cmd: List[str], **_kwargs: Any) -> MagicMock:
        out = cmd[out_index]
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"jpegdata")
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    return _run


def _fake_fail(cmd: List[str], **_kwargs: Any) -> MagicMock:
    return MagicMock(returncode=1, stdout=b"", stderr=b"boom")


def test_make_key_is_stable_and_path_case_insensitive():
    a = mt.make_key("W:/lib/a.exr", 10, 1.0)
    b = mt.make_key("w:\\lib\\a.exr".replace("\\", "/"), 10, 1.0)
    assert a == b
    assert a != mt.make_key("W:/lib/a.exr", 11, 1.0)
    assert a != mt.make_key("W:/lib/a.exr", 10, 2.0)
    assert a != mt.make_key("W:/lib/a.exr", 10, 1.0, tag="preview")


def test_cache_dir_follows_config(tmp_app_dir: Path):
    assert mt.cache_dir() == tmp_app_dir / "cache" / "media_thumbs"


def test_thumb_paths_are_sharded(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.exr", 1, 1.0)
    assert mt.thumb_file(key).parent.name == key[:2]
    assert mt.thumb_file(key).name == key + ".jpg"


def test_scale_filter_escapes_comma():
    # 콤마를 이스케이프하지 않으면 ffmpeg 가 필터 구분자로 오해한다.
    assert mt._scale_filter(256) == "scale=w=min(256\\,iw):h=-2"


def test_ensure_still_thumbnail_creates_and_reuses(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.exr", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_ok()) as run:
            out = mt.ensure_still_thumbnail("W:/lib/a.exr", key)
            assert out is not None and out.is_file()
            assert run.call_count == 1
        # 두 번째 호출은 캐시를 쓰고 ffmpeg 를 부르지 않는다.
        with patch("subprocess.run", side_effect=_fake_ok()) as run2:
            again = mt.ensure_still_thumbnail("W:/lib/a.exr", key)
            assert again == out
            assert run2.call_count == 0


def test_exr_retries_without_decoder_args_then_marks_failed(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.exr", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_fail) as run:
            assert mt.ensure_still_thumbnail("W:/lib/a.exr", key) is None
            # EXR 은 디코더 옵션(-apply_trc) 포함 1회 + 옵션 없이 1회 재시도
            assert run.call_count == 2
    assert mt.is_failed(key) is True
    # 실패로 표시된 뒤에는 ffmpeg 를 다시 부르지 않는다 (스크롤 시 폭주 방지).
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_fail) as run2:
            assert mt.ensure_still_thumbnail("W:/lib/a.exr", key) is None
            assert run2.call_count == 0


def test_non_exr_still_does_not_retry(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.dpx", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_fail) as run:
            assert mt.ensure_still_thumbnail("W:/lib/a.dpx", key) is None
            assert run.call_count == 1


def test_exr_decoder_args_are_passed(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.exr", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_ok()) as run:
            mt.ensure_still_thumbnail("W:/lib/a.exr", key)
    cmd = run.call_args[0][0]
    assert "-apply_trc" in cmd
    assert cmd[cmd.index("-apply_trc") + 1] == "iec61966_2_1"


def test_ensure_movie_thumbnail_uses_fast_seek(tmp_app_dir: Path):
    """thumbnail=100 필터가 아니라 -ss 빠른 탐색으로 한 장만 뽑는다."""
    key = mt.make_key("W:/lib/a.mov", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_fake_ok()) as run:
            out = mt.ensure_movie_thumbnail("W:/lib/a.mov", key)
    assert out is not None and out.is_file()
    cmd = run.call_args[0][0]
    assert "-ss" in cmd
    assert cmd[cmd.index("-ss") + 1] == "2"
    assert not any(str(a).startswith("thumbnail=") for a in cmd)
    assert "-an" in cmd
    assert "-sn" in cmd


def test_movie_thumbnail_falls_back_to_zero_seek(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.mov", 1, 1.0)
    calls = {"n": 0}

    def _first_fails(cmd: List[str], **kwargs: Any) -> MagicMock:
        calls["n"] += 1
        if calls["n"] == 1:
            return MagicMock(returncode=1, stdout=b"", stderr=b"seek past end")
        return _fake_ok()(cmd, **kwargs)

    with patch.object(mt, "resolve_ffmpeg", return_value="ffmpeg"):
        with patch("subprocess.run", side_effect=_first_fails) as run:
            out = mt.ensure_movie_thumbnail("W:/lib/a.mov", key)
    assert out is not None and out.is_file()
    assert calls["n"] == 2
    second = run.call_args_list[1][0][0]
    assert second[second.index("-ss") + 1] == "0"


def test_no_ffmpeg_returns_none_without_crashing(tmp_app_dir: Path):
    key = mt.make_key("W:/lib/a.exr", 1, 1.0)
    with patch.object(mt, "resolve_ffmpeg", return_value=None):
        assert mt.ensure_still_thumbnail("W:/lib/a.exr", key) is None


def test_enforce_cache_limit_removes_oldest_first(tmp_app_dir: Path):
    root = mt.cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        p = root / "f{}.jpg".format(i)
        p.write_bytes(b"x" * 1000)
        os.utime(str(p), (1000 + i, 1000 + i))

    assert mt.cache_size_bytes() == 4000
    freed = mt.enforce_cache_limit(2500)
    assert freed >= 1500
    remaining = sorted(p.name for p in root.glob("*.jpg"))
    # 오래된 f0, f1 이 먼저 지워지고 최근 파일이 남는다.
    assert remaining == ["f2.jpg", "f3.jpg"]


def test_enforce_cache_limit_noop_when_under_limit(tmp_app_dir: Path):
    root = mt.cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.jpg").write_bytes(b"x" * 100)
    assert mt.enforce_cache_limit(10_000) == 0
    assert (root / "a.jpg").is_file()


def test_enforce_cache_limit_handles_missing_dir(tmp_app_dir: Path):
    assert mt.enforce_cache_limit(1000) == 0
    assert mt.cache_size_bytes() == 0


def test_clear_cache(tmp_app_dir: Path):
    root = mt.cache_dir()
    (root / "ab").mkdir(parents=True, exist_ok=True)
    (root / "ab" / "x.jpg").write_bytes(b"x")
    mt.clear_cache()
    assert not root.exists()
