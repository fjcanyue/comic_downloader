# ruff: noqa: F821

import site
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def collect_mypyc_support_modules():
    modules = set()
    for site_package_dir in site.getsitepackages():
        site_package_path = Path(site_package_dir)
        for suffix in EXTENSION_SUFFIXES:
            for module_path in site_package_path.glob(f'*__mypyc{suffix}'):
                modules.add(module_path.name.removesuffix(suffix))
    return sorted(modules)


def unique_imports(*groups):
    imports = []
    seen = set()
    for group in groups:
        for module in group:
            if module not in seen:
                imports.append(module)
                seen.add(module)
    return imports


block_cipher = None
runtime_hiddenimports = unique_imports(
    collect_submodules('rich._unicode_data'),
    ('charset_normalizer.md',),
    collect_mypyc_support_modules(),
)
source_adapter_hiddenimports = (
    'downloader.sources.adapters',
    'downloader.sources.adapters.boya',
    'downloader.sources.adapters.dmzj',
    'downloader.sources.adapters.dumanwu',
    'downloader.sources.adapters.manhuafree',
    'downloader.sources.adapters.manhuagui',
    'downloader.sources.adapters.manhuazhan',
    'downloader.sources.adapters.maofly',
    'downloader.sources.adapters.morui',
    'downloader.sources.adapters.thmh',
    'downloader.sources.adapters.tuku',
)
source_hiddenimports = unique_imports(
    (
        'downloader.sources.registry',
        'downloader.sources.templates',
        *source_adapter_hiddenimports,
    ),
    collect_submodules('downloader.sources'),
)

# Core dependency edges that PyInstaller may miss during automatic analysis.
# Keep this targeted: collecting whole packages such as seleniumbase also pulls
# in large optional test/CLI trees that are not part of the downloader runtime.
dependency_hiddenimports = unique_imports(
    (
        'lxml.etree',
        'lxml._elementpath',
        'selenium.webdriver',
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.edge.webdriver',
        'selenium.webdriver.edge.options',
        'selenium.webdriver.firefox.webdriver',
        'selenium.webdriver.firefox.options',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support.ui',
        'seleniumbase',
        'seleniumbase.core.browser_launcher',
        'cloakbrowser.human',
        'urllib3.util.retry',
    ),
    collect_submodules('seleniumbase.undetected'),
)
dependency_datas = collect_data_files('seleniumbase')

a = Analysis(
    ['main.py'],
    pathex=['downloader'],
    binaries=[],
    datas=[('configs', 'configs'), *dependency_datas],
    hiddenimports=[*source_hiddenimports, *runtime_hiddenimports, *dependency_hiddenimports],
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
