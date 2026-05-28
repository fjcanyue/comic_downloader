# -*- mode: python ; coding: utf-8 -*-

import site
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


def collect_mypyc_support_modules():
    modules = set()
    for site_package_dir in site.getsitepackages():
        site_package_path = Path(site_package_dir)
        for suffix in EXTENSION_SUFFIXES:
            for module_path in site_package_path.glob(f'*__mypyc{suffix}'):
                modules.add(module_path.name.removesuffix(suffix))
    return sorted(modules)


block_cipher = None
runtime_hiddenimports = (
    collect_submodules('rich._unicode_data')
    + collect_submodules('charset_normalizer')
    + collect_mypyc_support_modules()
)


a = Analysis(
    ['main.py'],
    pathex=['downloader'],
    binaries=[],
    datas=[('configs', 'configs')],
    hiddenimports=[
        'downloader.boya',
        'downloader.dmzj',
        'downloader.dumanwu',
        'downloader.manhuafree',
        'downloader.manhuagui',
        'downloader.manhuazhan',
        'downloader.maofly',
        'downloader.morui',
        'downloader.thmh',
        'downloader.tuku'
    ] + runtime_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='comic_downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico'
)
