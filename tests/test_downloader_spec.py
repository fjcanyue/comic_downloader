from __future__ import annotations

import runpy
import site
from importlib import machinery
from pathlib import Path
from typing import Any, ClassVar

from PyInstaller.utils import hooks

from downloader.sources.registry import SOURCE_DEFINITIONS


def test_pyinstaller_spec_collects_dynamic_runtime_dependencies(monkeypatch, tmp_path):  # noqa: PLR0915
    mypyc_module = '81d243bd2c585b0f4821__mypyc'
    (tmp_path / f'{mypyc_module}.cp314-win_amd64.pyd').touch()
    collected_modules = {
        'downloader.sources': [
            'downloader.sources.profiles',
        ],
        'rich._unicode_data': ['rich._unicode_data.unicode17-0-0'],
        'seleniumbase.undetected': [
            'seleniumbase.undetected',
            'seleniumbase.undetected.cdp_driver',
        ],
    }
    collect_calls: list[str] = []
    analysis_kwargs: dict[str, Any] = {}

    def fake_collect_submodules(package: str) -> list[str]:
        collect_calls.append(package)
        return collected_modules.get(package, [])

    def fake_collect_data_files(package: str) -> list[tuple[str, str]]:
        collect_calls.append(f'data:{package}')
        if package == 'seleniumbase':
            return [('site-packages/seleniumbase/extensions/sbase_ext.zip', 'seleniumbase/extensions')]
        return []

    class FakeAnalysis:
        pure: ClassVar[list[Any]] = []
        zipped_data: ClassVar[list[Any]] = []
        scripts: ClassVar[list[Any]] = []
        binaries: ClassVar[list[Any]] = []
        zipfiles: ClassVar[list[Any]] = []
        datas: ClassVar[list[Any]] = []

    def fake_analysis(*args, **kwargs):
        analysis_kwargs.update(kwargs)
        return FakeAnalysis()

    def fake_pyz(*args, **kwargs):
        return object()

    def fake_exe(*args, **kwargs):
        return object()

    monkeypatch.setattr(hooks, 'collect_submodules', fake_collect_submodules)
    monkeypatch.setattr(hooks, 'collect_data_files', fake_collect_data_files)
    monkeypatch.setattr(site, 'getsitepackages', lambda: [str(tmp_path)])
    monkeypatch.setattr(machinery, 'EXTENSION_SUFFIXES', ['.cp314-win_amd64.pyd'])

    runpy.run_path(
        str(Path(__file__).parents[1] / 'downloader.spec'),
        init_globals={
            'Analysis': fake_analysis,
            'PYZ': fake_pyz,
            'EXE': fake_exe,
        },
    )

    assert 'downloader.sources' in collect_calls
    assert 'rich._unicode_data' in collect_calls
    assert 'charset_normalizer' not in collect_calls

    # These modules are reached through package-level lazy imports, so keep an
    # explicit fallback even when collect_submodules misses them in PyInstaller.
    assert 'downloader.sources.registry' in analysis_kwargs['hiddenimports']
    assert 'downloader.sources.templates' in analysis_kwargs['hiddenimports']
    expected_source_adapters = (
        'downloader.sources.adapters',
        *(f'downloader.sources.adapters.{definition.module_name}' for definition in SOURCE_DEFINITIONS),
    )
    for adapter_module in expected_source_adapters:
        assert adapter_module in analysis_kwargs['hiddenimports']
    assert 'downloader.' + 'morui' not in analysis_kwargs['hiddenimports']
    assert 'rich._unicode_data.unicode17-0-0' in analysis_kwargs['hiddenimports']
    assert 'charset_normalizer.md' in analysis_kwargs['hiddenimports']
    assert 'charset_normalizer.cli' not in analysis_kwargs['hiddenimports']
    assert mypyc_module in analysis_kwargs['hiddenimports']

    # Dependencies with known dynamic edges should be precise instead of
    # collecting whole third-party packages with large optional test/CLI trees.
    assert 'lxml' not in collect_calls
    assert 'selenium' not in collect_calls
    assert 'seleniumbase' not in collect_calls
    assert 'urllib3' not in collect_calls
    assert 'cloakbrowser' not in collect_calls
    assert 'seleniumbase.undetected' in collect_calls

    hidden = analysis_kwargs['hiddenimports']
    assert 'lxml.etree' in hidden
    assert 'lxml._elementpath' in hidden
    assert 'selenium.webdriver' in hidden
    assert 'selenium.webdriver.chrome.webdriver' in hidden
    assert 'selenium.webdriver.edge.webdriver' in hidden
    assert 'selenium.webdriver.firefox.webdriver' in hidden
    assert 'seleniumbase.core.browser_launcher' in hidden
    assert 'seleniumbase.undetected.cdp_driver' in hidden
    assert 'cloakbrowser.human' in hidden
    assert 'cloakbrowser.__main__' not in hidden
    assert 'urllib3.util.retry' in hidden

    assert 'data:seleniumbase' in collect_calls
    datas = analysis_kwargs.get('datas', [])
    assert any('configs' in str(d) for d in datas), f'configs not in datas: {datas}'
    assert any('sbase_ext.zip' in str(d) for d in datas), f'sbase_ext.zip not in datas: {datas}'
