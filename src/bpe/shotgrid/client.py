"""ShotGrid connection helpers — thread-safe, TLS-cached Shotgun instances."""

from __future__ import annotations

import os
import threading
from typing import Any, Optional

from bpe.core.logging import get_logger
from bpe.core.shotgrid_settings import get_shotgrid_settings
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.client")

try:
    from shotgun_api3 import Shotgun
except ImportError as _e:
    Shotgun = None  # type: ignore[assignment,misc]
    _SHOTGUN_IMPORT_ERROR = _e
else:
    _SHOTGUN_IMPORT_ERROR = None

_TLS_SG = threading.local()


def _require_shotgun() -> type:
    if Shotgun is None:
        raise ShotGridError(
            "shotgun_api3 패키지가 없습니다. pip install shotgun_api3 후 다시 실행하세요."
        ) from _SHOTGUN_IMPORT_ERROR
    return Shotgun


# ── connections ──────────────────────────────────────────────────────


def get_default_sg() -> Any:
    """Return a TLS-cached Shotgun instance using merged settings."""
    sg = getattr(_TLS_SG, "client", None)
    if sg is None:
        s = get_shotgrid_settings()
        sg = connect_from_settings(
            s["base_url"],
            s["script_name"],
            s["script_key"],
        )
        _TLS_SG.client = sg
    return sg


def reset_default_sg() -> None:
    """Clear the current thread's cached Shotgun instance."""
    if hasattr(_TLS_SG, "client"):
        try:
            delattr(_TLS_SG, "client")
        except Exception:
            _TLS_SG.client = None  # type: ignore[attr-defined]


def connect_from_settings(
    base_url: str,
    script_name: str,
    script_key: str,
    *,
    sudo_as_login: Optional[str] = None,
) -> Any:
    """Create a Shotgun instance.  Empty values fall back to merged settings."""
    SG = _require_shotgun()
    s = get_shotgrid_settings()
    base_url = (base_url or s["base_url"]).strip().rstrip("/")
    script_name = (script_name or s["script_name"]).strip()
    script_key = (script_key or s["script_key"]).strip()
    sudo_login = (sudo_as_login or "").strip() or None

    if not base_url:
        raise ShotGridError("ShotGrid 사이트 URL이 비어 있습니다.")
    if not script_name or not script_key:
        raise ShotGridError("Script 이름 또는 Script Key가 비어 있습니다.")

    sg = SG(
        base_url,
        script_name=script_name,
        api_key=script_key,
        sudo_as_login=sudo_login,
    )

    # timeout — BPE_SG_PUT_TIMEOUT_SECS env (min 60, default 720)
    _put_timeout_env = (os.environ.get("BPE_SG_PUT_TIMEOUT_SECS") or "").strip()
    _put_timeout = 720.0
    if _put_timeout_env:
        try:
            _put_timeout = max(60.0, float(_put_timeout_env))
        except (ValueError, TypeError):
            pass
    try:
        sg.config.timeout_secs = _put_timeout
    except Exception:
        pass

    return sg


def get_shotgun_for_version_mutation(sudo_login: Optional[str]) -> Any:
    """Shotgun instance for Version create / upload.

    If *sudo_login* is given, a fresh connection with sudo_as_login is created.
    Otherwise the default cached connection is returned.
    """
    sl = (sudo_login or "").strip() or None
    if not sl:
        return get_default_sg()
    s = get_shotgrid_settings()
    sg = connect_from_settings(
        s["base_url"],
        s["script_name"],
        s["script_key"],
        sudo_as_login=sl,
    )
    logger.debug("using sudo_as_login for version mutation")
    return sg


def resolve_sudo_login(
    sg: Any,
    human_user_id: int,
    *,
    fallback_login: Optional[str] = None,
) -> Optional[str]:
    """Resolve a sudo_as_login string from a HumanUser record."""
    uid = int(human_user_id)
    u = sg.find_one(
        "HumanUser",
        [["id", "is", uid]],
        ["id", "name", "login", "email"],
    )
    if not u:
        fb = (fallback_login or "").strip()
        return fb or None
    login = (u.get("login") or "").strip()
    if login:
        return login
    email = (u.get("email") or "").strip()
    if email:
        return email
    fb = (fallback_login or "").strip()
    return fb or None


def test_connection(sg: Any) -> str:
    """Smoke-test a Shotgun connection by fetching one Project."""
    one = sg.find_one("Project", [], ["id", "name"])
    if one is None:
        return "연결 성공 (프로젝트 0개 또는 조회 제한)."
    return f"연결 성공 — 프로젝트 예시: {one.get('name', '')} (id={one.get('id')})"
