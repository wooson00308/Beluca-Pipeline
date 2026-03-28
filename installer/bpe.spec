# -*- mode: python ; coding: utf-8 -*-
"""
BPE (Beluca Pipeline Engine) PyInstaller spec.
macOS + Windows 공용. 프로젝트 루트에서 실행:
    pyinstaller installer/bpe.spec
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# 프로젝트 루트 (installer/ 상위)
ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

# VERSION.txt에서 버전 읽기
_ver = (ROOT / "VERSION.txt").read_text().strip()
_ver_tuple = tuple(int(x) for x in _ver.split(".")) + (0,) * (4 - len(_ver.split(".")))

# Windows 버전 정보 (파일 속성에 Python 대신 BPE로 표시)
_win_version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32 import versioninfo as vi

    _win_version_info = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(
            filevers=_ver_tuple,
            prodvers=_ver_tuple,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
        ),
        kids=[
            vi.StringFileInfo([
                vi.StringTable("040904B0", [
                    vi.StringStruct("CompanyName", "BELUCA"),
                    vi.StringStruct("FileDescription", "Beluca Pipeline Engine"),
                    vi.StringStruct("FileVersion", _ver),
                    vi.StringStruct("InternalName", "BPE"),
                    vi.StringStruct("OriginalFilename", "BPE.exe"),
                    vi.StringStruct("ProductName", "Beluca Pipeline Engine"),
                    vi.StringStruct("ProductVersion", _ver),
                ]),
            ]),
            vi.VarFileInfo([vi.VarStruct("Translation", [1033, 1200])]),
        ],
    )

# 데이터 파일
datas = [
    (str(SRC / "bpe"), "bpe"),
    (str(ROOT / "VERSION.txt"), "."),
    (str(ROOT / "installer" / "icon.png"), "."),
]

# 템플릿이 있으면 포함
templates_dir = ROOT / "templates"
if templates_dir.exists():
    datas.append((str(templates_dir), "templates"))

binaries = []

# PySide6 — 바이너리·플러그인·데이터 전부 (미설치 시 빌드는 의미 없는 얇은 exe만 나옴)
try:
    _ps6_datas, _ps6_binaries, _ps6_hidden = collect_all("PySide6")
except Exception as exc:
    raise RuntimeError(
        "PyInstaller: PySide6가 필요합니다. "
        "pip install -e . 또는 pip install PySide6 후 다시 빌드하세요."
    ) from exc
datas += _ps6_datas
binaries += _ps6_binaries

hiddenimports = [
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "shotgun_api3",
    "shotgun_api3.lib.httplib2",
    "shotgun_api3.lib.sgtimezone",
    "certifi",
    "six",
    "urllib3",
    "PIL",
    "bpe.core",
    "bpe.core.config",
    "bpe.core.presets",
    "bpe.core.settings",
    "bpe.core.cache",
    "bpe.core.atomic_io",
    "bpe.gui",
    "bpe.shotgrid",
]
hiddenimports += list(_ps6_hidden)

a = Analysis(
    [str(SRC / "bpe" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Nuke 전용 모듈은 데스크톱 빌드에서 제외
        "nuke",
        "nukescripts",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BPE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "installer" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
    version=_win_version_info,
)

# macOS .app 번들 (Windows에서는 무시됨)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="BPE.app",
        icon=str(ROOT / "installer" / "icon.icns"),
        bundle_identifier="com.beluca.bpe",
    )
