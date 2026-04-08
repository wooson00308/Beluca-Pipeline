"""Windows shell AppUserModelID — must run before any PySide6 import (see bpe.__main__)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from bpe.core.logging import get_logger

# 릴리즈 버전을 넣지 말 것 — 바꾸면 작업 표시줄 고정과 실행 중 아이콘이 어긋날 수 있음
BPE_APP_USER_MODEL_ID = "Beluca.BPE"

# PKEY_AppUserModel_ID — https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-id
# IID IPropertyStore — https://learn.microsoft.com/en-us/windows/win32/api/propsys/nn-propsys-ipropertystore
_VT_LPWSTR = 0x001F


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", _GUID),
        ("pid", wintypes.DWORD),
    ]


class _PROPVARIANT_U(ctypes.Union):
    _fields_ = [
        ("pwszVal", ctypes.c_void_p),
        ("ullVal", ctypes.c_ulonglong),
    ]


class _PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("u", _PROPVARIANT_U),
    ]


def _pkey_app_user_model_id() -> _PROPERTYKEY:
    pk = _PROPERTYKEY()
    pk.fmtid.Data1 = 0x9F4C2855
    pk.fmtid.Data2 = 0x9F79
    pk.fmtid.Data3 = 0x4B39
    pk.fmtid.Data4 = (wintypes.BYTE * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3)
    pk.pid = 5
    return pk


def _iid_property_store() -> _GUID:
    g = _GUID()
    g.Data1 = 0x886D8EEB
    g.Data2 = 0x8CF2
    g.Data3 = 0x4446
    g.Data4 = (wintypes.BYTE * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99)
    return g


def apply_explicit_app_user_model_id() -> None:
    """SetCurrentProcessExplicitAppUserModelID — 작업 표시줄 고정·점프 목록용."""
    if sys.platform != "win32":
        return
    logger = get_logger("app")
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = (ctypes.c_wchar_p,)
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        hr = int(shell32.SetCurrentProcessExplicitAppUserModelID(BPE_APP_USER_MODEL_ID))
        if hr != 0:
            logger.warning(
                "SetCurrentProcessExplicitAppUserModelID 실패: HRESULT=0x%x",
                hr & 0xFFFFFFFF,
            )
    except Exception:
        logger.warning("SetCurrentProcessExplicitAppUserModelID 예외", exc_info=True)


def apply_app_user_model_id_to_hwnd(hwnd: int) -> None:
    """HWND에 PKEY_AppUserModel_ID 설정(SHGetPropertyStoreForWindow). Qt winId() 직후 호출.

    실패해도 예외를 내지 않는다 — UI·다른 기능 회귀 방지.
    """
    if sys.platform != "win32" or not hwnd:
        return
    logger = get_logger("app")
    try:
        ole32 = ctypes.OleDLL("ole32")
        shell32 = ctypes.windll.shell32

        PropVariantInit = ole32.PropVariantInit
        PropVariantInit.argtypes = [ctypes.POINTER(_PROPVARIANT)]
        PropVariantInit.restype = None

        PropVariantClear = ole32.PropVariantClear
        PropVariantClear.argtypes = [ctypes.POINTER(_PROPVARIANT)]
        PropVariantClear.restype = ctypes.c_long

        shell32.SHGetPropertyStoreForWindow.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long

        iid_store = _iid_property_store()
        ppstore = ctypes.c_void_p()
        hr_g = int(
            shell32.SHGetPropertyStoreForWindow(
                wintypes.HWND(int(hwnd)),
                ctypes.byref(iid_store),
                ctypes.byref(ppstore),
            )
        )
        if hr_g != 0:
            logger.warning(
                "SHGetPropertyStoreForWindow 실패: HRESULT=0x%x",
                hr_g & 0xFFFFFFFF,
            )
            return

        this = ppstore.value
        if not this:
            return

        vtbl = ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))[0]
        fns = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p * 16)).contents

        SetValue = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(_PROPERTYKEY),
            ctypes.POINTER(_PROPVARIANT),
        )(fns[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(fns[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)(fns[2])

        CoTaskMemAlloc = ole32.CoTaskMemAlloc
        CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
        CoTaskMemAlloc.restype = ctypes.c_void_p

        pkey = _pkey_app_user_model_id()
        # VT_LPWSTR는 PropVariantClear가 CoTaskMemFree로 해제 — 스택 버퍼 금지
        raw_utf16 = BPE_APP_USER_MODEL_ID.encode("utf-16-le") + b"\x00\x00"
        n_bytes = len(raw_utf16)
        mem_ptr = int(CoTaskMemAlloc(n_bytes) or 0)
        if not mem_ptr:
            logger.warning("CoTaskMemAlloc 실패(AppUserModel_ID 문자열)")
            Release(this)
            return
        ctypes.memmove(mem_ptr, raw_utf16, n_bytes)

        pv = _PROPVARIANT()
        PropVariantInit(ctypes.byref(pv))
        try:
            try:
                pv.vt = _VT_LPWSTR
                pv.pwszVal = mem_ptr
                hr_sv = int(SetValue(this, ctypes.byref(pkey), ctypes.byref(pv)))
                if hr_sv != 0:
                    logger.warning(
                        "IPropertyStore::SetValue(AppUserModel_ID) 실패: HRESULT=0x%x",
                        hr_sv & 0xFFFFFFFF,
                    )
                hr_c = int(Commit(this))
                if hr_c != 0:
                    logger.warning(
                        "IPropertyStore::Commit 실패: HRESULT=0x%x",
                        hr_c & 0xFFFFFFFF,
                    )
            finally:
                PropVariantClear(ctypes.byref(pv))
        finally:
            Release(this)
    except Exception:
        logger.warning("apply_app_user_model_id_to_hwnd 예외", exc_info=True)
