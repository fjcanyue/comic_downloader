from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import toml

SOURCE_ADAPTER_MODULES = (
    'boya',
    'dmzj',
    'dumanwu',
    'manhuafree',
    'manhuagui',
    'manhuazhan',
    'maofly',
    'morui',
    'thmh',
    'tuku',
)


@pytest.mark.parametrize('module_name', SOURCE_ADAPTER_MODULES)
def test_source_adapters_import_from_nested_package(module_name):
    module = importlib.import_module(f'downloader.sources.adapters.{module_name}')

    assert module.__name__ == f'downloader.sources.adapters.{module_name}'


@pytest.mark.parametrize('module_name', SOURCE_ADAPTER_MODULES)
def test_top_level_source_adapter_imports_are_removed(module_name):
    full_name = f'downloader.{module_name}'
    sys.modules.pop(full_name, None)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(full_name)


def test_sources_package_exposes_registry_api():
    sources = importlib.import_module('downloader.sources')

    assert hasattr(sources, 'SOURCE_DEFINITIONS')
    assert hasattr(sources, 'SourceDefinition')
    assert hasattr(sources, 'get_source_definitions')
    assert hasattr(sources, 'load_source_bindings')
    assert hasattr(sources, 'load_source_classes')
    assert hasattr(sources, 'validate_runtime_config_sources')


def test_setuptools_discovers_downloader_subpackages():
    pyproject = toml.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    assert pyproject['tool']['setuptools']['packages']['find']['include'] == ['downloader*']
