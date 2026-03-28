"""Preset Manager 등 접근 제어용 해시·검증 (평문 비밀번호는 코드에 두지 않음)."""

from __future__ import annotations

import hashlib

# sha256("0401".encode("utf-8")).hexdigest()
PRESET_PW_HASH = "12b408838e33f12bf8886792e6d44de0d9623e2bbf833b70f9f2e13fdf802706"


def verify_preset_password(password: str) -> bool:
    """Preset Manager 잠금 해제용 비밀번호 검증."""
    if not password:
        return False
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return digest == PRESET_PW_HASH
