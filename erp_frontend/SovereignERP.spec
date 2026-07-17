# -*- mode: python ; coding: utf-8 -*-
"""
SovereignERP.spec
===================
File konfigurasi PyInstaller untuk build aplikasi jadi 1 folder standalone
(SovereignERP.exe + dependencies), bisa dijalankan tanpa install Python.

CARA PAKAI:
    pip install pyinstaller
    pyinstaller SovereignERP.spec

Hasil build ada di dist/SovereignERP/SovereignERP.exe
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'requests',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SovereignERP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # ganti True sementara kalau perlu lihat error saat debug build
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,       # taruh path .ico di sini kalau punya logo perusahaan
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SovereignERP',
)
