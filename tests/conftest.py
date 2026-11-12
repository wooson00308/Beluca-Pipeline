"""Shared fixtures for all BPE tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ── 수집(임포트) 시점 방어 ────────────────────────────────────────────
# ``bpe/__init__.py`` 가 패키지 import 순간 prepend_studio_shotgun_api...() 를
# 호출하고, 그 안의 get_logger() 가 APP_DIR 에 bpe.log 를 mode="w" 로 연다.
# 즉 "bpe 를 import 하는 행위 자체"가 실사용자 ~/.setup_pro/bpe.log 를
# truncate 한다(2026-08-18 실측 — fixture/사후 패치로는 못 막음, 이미 열린 뒤).
# conftest 는 테스트 모듈보다 먼저 import 되므로, 여기서 bpe 최초 import 를
# 가짜 홈(USERPROFILE) 아래에서 수행해 로그 파일이 세션 임시 폴더에 생기게 한다.
_SESSION_HOME = Path(tempfile.mkdtemp(prefix="bpe_test_session_home_"))
_SESSION_APP_DIR = _SESSION_HOME / ".setup_pro"
_orig_userprofile = os.environ.get("USERPROFILE")
os.environ["USERPROFILE"] = str(_SESSION_HOME)
try:
    import bpe.core.config as _cfg  # noqa: E402  (bpe/__init__ 부작용도 가짜 홈으로)
finally:
    if _orig_userprofile is not None:
        os.environ["USERPROFILE"] = _orig_userprofile
    else:
        os.environ.pop("USERPROFILE", None)

# import 이후에도 기본 경로는 세션 임시 폴더 유지 (개별 fixture 가 다시 덮는다)
_cfg.APP_DIR = _SESSION_APP_DIR
_cfg.CACHE_DIR = _SESSION_APP_DIR / "cache"


@pytest.fixture()
def tmp_app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated APP_DIR — patches bpe.core.config so every module sees tmp paths."""
    app_dir = tmp_path / ".setup_pro"
    app_dir.mkdir()
    cache_dir = app_dir / "cache"
    cache_dir.mkdir()

    import bpe.core.config as cfg

    monkeypatch.setattr(cfg, "APP_DIR", app_dir)
    monkeypatch.setattr(cfg, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(cfg, "SETTINGS_FILE", app_dir / "settings.json")
    monkeypatch.setattr(cfg, "SHOT_BUILDER_FILE", app_dir / "shot_builder.json")
    monkeypatch.setattr(cfg, "FORMAT_CACHE_FILE", cache_dir / "nuke_formats.json")
    monkeypatch.setattr(cfg, "COLORSPACE_CACHE_FILE", cache_dir / "nuke_colorspaces.json")
    monkeypatch.setattr(cfg, "DATATYPE_CACHE_FILE", cache_dir / "nuke_write_datatypes.json")
    monkeypatch.setattr(cfg, "OCIO_CONFIG_CACHE_FILE", cache_dir / "ocio_configs.json")
    monkeypatch.setattr(cfg, "SOURCE_LIBRARY_INDEX_FILE", cache_dir / "source_library.sqlite")
    monkeypatch.setattr(cfg, "MEDIA_THUMBS_DIR", cache_dir / "media_thumbs")

    # Presets default dir must stay under isolated APP_DIR (not team W: drive).
    import bpe.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_DEFAULT_PRESETS_DIR", app_dir)

    return app_dir


@pytest.fixture(autouse=True)
def _block_real_user_and_team_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """격리를 깜빡한 테스트가 실사용자/팀 경로를 건드리지 못하게 하는 기본 방어선.

    2026-08-13 사고: 격리 없는 테스트가 실제 팀 공유 library.json(W:\\...)을
    덮어써 데이터가 유실됐다. 2026-08-15 추가 점검에서 같은 유형의 구멍이 더
    발견됨 — 테스트가 실사용자 ``~/.setup_pro/bpe.log`` 를 truncate 하고, 저장소
    루트에 피드백 로그를 수백 KB 쌓고 있었다. 개별 테스트가 자체 monkeypatch 로
    다시 지정하는 건 안전하다(나중 호출이 이 기본값을 덮어씀).
    """
    # 1) 공유 library.json 경로 — fail-loud: 격리 없이 호출되면 즉시 실패시켜
    #    새 테스트의 격리 누락이 "조용히 tmp에 쓰고 통과"가 아니라 작성 시점에 잡히게.
    import bpe.core.source_library_config as libcfg

    def _config_dir_blocked() -> Path:
        raise AssertionError(
            "테스트가 격리 없이 source_library_config.config_dir() 를 호출했습니다. "
            'monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared") 필요.'
        )

    monkeypatch.setattr(libcfg, "config_dir", _config_dir_blocked)

    # 1-b) 사용자 홈 ~/.setup_pro 기본값 — tmp_app_dir 를 안 받는 테스트가
    #      get_logger() 만 불러도 실사용자 bpe.log 가 truncate 되던 구멍을 막는다.
    #      (tmp_app_dir 를 받는 테스트는 그 fixture 가 나중에 다시 덮어쓴다)
    import bpe.core.config as cfg

    default_app = tmp_path / "_default_setup_pro"
    monkeypatch.setattr(cfg, "APP_DIR", default_app)
    monkeypatch.setattr(cfg, "CACHE_DIR", default_app / "cache")

    # 2) 팀 프리셋 W: 기본 경로 (tmp_app_dir 를 안 받는 테스트도 커버)
    import bpe.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_DEFAULT_PRESETS_DIR", tmp_path / "_presets_default")

    # 3) 피드백/업로드 트레이스 로그 — cwd(저장소 루트) 대신 tmp
    monkeypatch.setenv("BPE_FEEDBACK_LOG_DIR", str(tmp_path / "_feedback_logs"))

    # 4) 실제 ~/.nuke — ensure/remove_nuke_plugin 의 기본 대상
    import bpe.core.nuke_plugin_install as npi

    monkeypatch.setattr(npi, "nuke_home", lambda: tmp_path / "_nuke_home")

    # 5) 실제 ShotGrid 연결 — 격리를 깜빡한 테스트가 실서버에 노트·상태를 쓰지 못하게
    #    연결 생성 자체를 fail-loud 로 막는다. MockShotgun 을 직접 넘기는 테스트는
    #    영향이 없고, Shotgun 을 자체 monkeypatch 하는 테스트는 그쪽이 나중에 덮어쓴다.
    import bpe.shotgrid.client as sg_client

    def _real_shotgun_blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "테스트가 실제 ShotGrid 에 연결하려 했습니다. "
            "MockShotgun 을 넘기거나 bpe.shotgrid.client.Shotgun 을 monkeypatch 하세요."
        )

    monkeypatch.setattr(sg_client, "Shotgun", _real_shotgun_blocked)
