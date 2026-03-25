# -*- mode: python ; coding: utf-8 -*-
"""
BPE (Beluca Pipeline Engine) PyInstaller spec.
macOS + Windows 공용. 프로젝트 루트에서 실행:
    pyinstaller installer/bpe.spec
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_all

# 프로젝트 루트 (installer/ 상위)
ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

# 데이터 파일
datas = [
    (str(SRC / "bpe"), "bpe"),
    (str(ROOT / "VERSION.txt"), "."),
]

# 템플릿이 있으면 포함
templates_dir = ROOT / "templates"
if templates_dir.exists():
    datas.append((str(templates_dir), "templates"))

binaries = []

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

# PySide6 데이터
datas += collect_data_files("PySide6", include_py_files=False)

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
)

# macOS .app 번들 (Windows에서는 무시됨)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="BPE.app",
        icon=None,
        bundle_identifier="com.beluca.bpe",
    )
