"""ShotGrid Shotgun client — resolve HTTP proxy (explicit settings or system)."""

from __future__ import annotations

import os
import sys
import urllib.request
from typing import Any, Dict, Optional


def _wininet_proxy_registry_snapshot() -> Dict[str, Any]:
    """
    HKCU Internet Settings — lengths only (no hostnames) for diagnostics.
    """
    out: Dict[str, Any] = {
        "inet_proxy_enable": None,
        "inet_proxy_server_len": 0,
        "inet_autoconfig_url_len": 0,
    }
    if sys.platform != "win32":
        return out
    try:
        import winreg
    except ImportError:
        return out
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
    except OSError:
        return out
    try:
        try:
            enable_raw, _ = winreg.QueryValueEx(key, "ProxyEnable")
            try:
                out["inet_proxy_enable"] = int(enable_raw)
            except (TypeError, ValueError):
                out["inet_proxy_enable"] = 0
        except FileNotFoundError:
            pass
        try:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if isinstance(server, str) and server.strip():
                out["inet_proxy_server_len"] = len(server.strip())
        except FileNotFoundError:
            pass
        try:
            ac, _ = winreg.QueryValueEx(key, "AutoConfigURL")
            if isinstance(ac, str) and ac.strip():
                out["inet_autoconfig_url_len"] = len(ac.strip())
        except FileNotFoundError:
            pass
    finally:
        try:
            winreg.CloseKey(key)
        except OSError:
            pass
    return out


def shotgrid_http_proxy_diag(merged_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safe proxy resolution hints for feedback logs (no secrets, no proxy host strings).
    Helps distinguish: explicit settings vs getproxies vs WinINET static vs PAC-only.
    """
    explicit = str(merged_settings.get("http_proxy") or "").strip()
    out: Dict[str, Any] = {
        "explicit_proxy_len": len(explicit),
        "no_system_proxy": (os.environ.get("BPE_SHOTGRID_NO_SYSTEM_PROXY") or "").strip().lower()
        in ("1", "true", "yes", "on"),
    }
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    gp_vals = [(proxies.get(k) or "").strip() for k in ("https", "http", "all")]
    out["getproxies_nonempty"] = any(
        v and v.lower() not in ("direct://", "direct") for v in gp_vals
    )
    if sys.platform == "win32":
        snap = _wininet_proxy_registry_snapshot()
        out.update(snap)
        en = snap.get("inet_proxy_enable")
        sl = int(snap.get("inet_proxy_server_len") or 0)
        acl = int(snap.get("inet_autoconfig_url_len") or 0)
        out["pac_only_suspected"] = bool(en == 1 and sl == 0 and acl > 0)
        out["winhttp_named_proxy_nonempty"] = bool(_windows_winhttp_default_proxy_url())
    else:
        out["pac_only_suspected"] = False
        out["winhttp_named_proxy_nonempty"] = False
    return out


def normalize_proxy_for_shotgun(proxy_url: str) -> str:
    """Strip scheme; shotgun_api3 expects host:port or user:pass@host:port (no http://)."""
    p = (proxy_url or "").strip()
    if not p:
        return ""
    low = p.lower()
    if low.startswith("http://"):
        p = p[7:]
    elif low.startswith("https://"):
        p = p[8:]
    return p.rstrip("/").strip()


def _parse_proxy_server_value(proxy_server: str) -> str:
    """
    HKCU Internet Settings ProxyServer string formats:
      host:port
      http=host:port;https=host:port;ftp=...
    Prefer https= then http= for ShotGrid (HTTPS).
    """
    s = (proxy_server or "").strip()
    if not s:
        return ""
    if "=" not in s:
        return s
    parts = [p.strip() for p in s.split(";") if p.strip()]
    for prefix in ("https=", "http="):
        pl = prefix.lower()
        for p in parts:
            low = p.lower()
            if low.startswith(pl):
                return p.split("=", 1)[1].strip()
    return ""


def _windows_winhttp_default_proxy_url() -> str:
    """
    WinHTTP default proxy (often `netsh winhttp set proxy ...`), separate from HKCU WinINET.
    If IT only configures WinHTTP, urllib/getproxies and IE registry can all be empty.
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return ""
    try:
        winhttp = ctypes.WinDLL("winhttp.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    except OSError:
        return ""

    class WINHTTP_PROXY_INFO(ctypes.Structure):
        _fields_ = [
            ("dwAccessType", wintypes.DWORD),
            ("lpszProxy", wintypes.LPWSTR),
            ("lpszProxyBypass", wintypes.LPWSTR),
        ]

    WINHTTP_ACCESS_TYPE_NAMED_PROXY = 3

    WinHttpGetDefaultProxyConfiguration = winhttp.WinHttpGetDefaultProxyConfiguration
    WinHttpGetDefaultProxyConfiguration.argtypes = [ctypes.POINTER(WINHTTP_PROXY_INFO)]
    WinHttpGetDefaultProxyConfiguration.restype = wintypes.BOOL

    GlobalFree = kernel32.GlobalFree
    GlobalFree.argtypes = [wintypes.HGLOBAL]
    GlobalFree.restype = wintypes.HGLOBAL

    info = WINHTTP_PROXY_INFO()
    if not WinHttpGetDefaultProxyConfiguration(ctypes.byref(info)):
        return ""

    proxy_raw = ""
    try:
        if info.dwAccessType == WINHTTP_ACCESS_TYPE_NAMED_PROXY and info.lpszProxy:
            proxy_raw = ctypes.wstring_at(info.lpszProxy)
    finally:
        if info.lpszProxy:
            GlobalFree(info.lpszProxy)
        if info.lpszProxyBypass:
            GlobalFree(info.lpszProxyBypass)

    if not proxy_raw or not str(proxy_raw).strip():
        return ""
    picked = _parse_proxy_server_value(str(proxy_raw).strip())
    if not picked:
        return ""
    if "://" not in picked:
        return f"http://{picked}"
    return picked


def _windows_inet_settings_proxy_url() -> str:
    """
    When urllib.request.getproxies() is empty, WinINET / IE proxy may still be set
    in HKCU (same UI as 'Internet Options' — often what browsers follow).
    PAC-only (AutoConfigURL) with no ProxyServer is not resolved here.
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
    except OSError:
        return ""
    try:
        try:
            enable_raw, _ = winreg.QueryValueEx(key, "ProxyEnable")
        except FileNotFoundError:
            return ""
        try:
            enable = int(enable_raw)
        except (TypeError, ValueError):
            enable = 0
        if enable != 1:
            return ""
        try:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        except FileNotFoundError:
            return ""
        if not isinstance(server, str) or not server.strip():
            return ""
        picked = _parse_proxy_server_value(server.strip())
        if not picked:
            return ""
        if "://" not in picked:
            return f"http://{picked}"
        return picked
    finally:
        try:
            winreg.CloseKey(key)
        except OSError:
            pass


def _system_proxy_url() -> str:
    """urllib env + WinINET HKCU + WinHTTP default (Windows)."""
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    for key in ("https", "http", "all"):
        val = (proxies.get(key) or "").strip()
        if not val:
            continue
        if val.lower() in ("direct://", "direct"):
            continue
        return val
    reg = _windows_inet_settings_proxy_url()
    if reg:
        return reg
    return _windows_winhttp_default_proxy_url()


def resolve_shotgun_http_proxy(merged_settings: Dict[str, Any]) -> Optional[str]:
    """
    Proxy for shotgun_api3 Shotgun(http_proxy=...).

    Priority:
      1) merged_settings['http_proxy'] (settings.json / studio / BPE_SHOTGRID_HTTP_PROXY)
      2) System proxy: urllib.request.getproxies, then Windows HKCU WinINET, then WinHTTP
         default unless BPE_SHOTGRID_NO_SYSTEM_PROXY is set
    """
    explicit = normalize_proxy_for_shotgun(str(merged_settings.get("http_proxy") or ""))
    if explicit:
        return explicit

    flag = (os.environ.get("BPE_SHOTGRID_NO_SYSTEM_PROXY") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return None

    sys_p = normalize_proxy_for_shotgun(_system_proxy_url())
    return sys_p or None
