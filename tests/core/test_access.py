"""bpe.core.access — Preset 잠금 비밀번호 검증."""

from __future__ import annotations

from bpe.core.access import verify_preset_password


def test_verify_preset_password_correct() -> None:
    assert verify_preset_password("0401") is True


def test_verify_preset_password_wrong() -> None:
    assert verify_preset_password("0402") is False
    assert verify_preset_password("") is False
