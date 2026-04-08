"""windows_app_id — HWND 경로가 예외를 내지 않는지(플랫폼별 최소 smoke)."""

from __future__ import annotations

import sys

import pytest

from bpe.core.windows_app_id import apply_app_user_model_id_to_hwnd


def test_apply_app_user_model_id_to_hwnd_zero_never_raises() -> None:
    apply_app_user_model_id_to_hwnd(0)


def test_apply_app_user_model_id_to_hwnd_non_windows_any_hwnd() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows에서는 무효 HWND로 COM을 호출하지 않음")
    apply_app_user_model_id_to_hwnd(0x12345)
