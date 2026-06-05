from __future__ import annotations

import runpy
import site
from importlib import machinery
from pathlib import Path
from typing import Any, ClassVar

from PyInstaller.utils import hooks


def test_pyinstaller_spec_collects_dynamic_runtime_dependencies(monkeypatch, tmp_path):
    mypyc_module = '81d243bd2c585b0f4821__mypyc'
    (tmp_path / f'{mypyc_module}.cp314-win_amd64.pyd').touch()
    collected_modules = {
        'rich._unicode_data': ['rich._unicode_data.unicode17-0-0'],
        'charset_normalizer': ['charset_normalizer', 'charset_normalizer.md'],
    }
    collect_calls: list[str] = []
    analysis_kwargs: dict[str, Any] = {}

    def fake_collect_submodules(package: str) -> list[str]:
        collect_calls.append(package)
        return collected_modules.get(package, [])

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

    assert 'rich._unicode_data' in collect_calls
    assert 'charset_normalizer' in collect_calls
    assert 'rich._unicode_data.unicode17-0-0' in analysis_kwargs['hiddenimports']
    assert 'charset_normalizer.md' in analysis_kwargs['hiddenimports']
    assert mypyc_module in analysis_kwargs['hiddenimports']
