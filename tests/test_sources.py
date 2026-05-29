from __future__ import annotations

import pytest
import requests

from downloader.runtime_config import RuntimeConfig, SourceRuntimeConfig
from downloader.sources import load_source_classes


def test_default_sources_include_cloakbrowser_morui():
    sources = load_source_classes()

    assert 'morui' in sources
    assert sources['morui'].browser_mode == 'cloakbrowser'


def test_deprecated_sources_include_morui_and_deprecated_sources():
    sources = load_source_classes(include_deprecated=True)

    assert 'morui' in sources
    assert 'manhuagui' in sources


def test_runtime_config_overrides_enabled_sources():
    runtime_config = RuntimeConfig(
        sources={
            'boya': SourceRuntimeConfig(enabled=True),
            'morui': SourceRuntimeConfig(enabled=False),
        }
    )

    sources = load_source_classes(runtime_config=runtime_config)

    assert 'boya' in sources
    assert 'morui' not in sources


def test_runtime_config_browser_mode_overrides_site_config(tmp_path):
    runtime_config = RuntimeConfig(
        sources={'morui': SourceRuntimeConfig(browser_mode='requests')}
    )

    sources = load_source_classes(runtime_config=runtime_config)
    source_class = sources['morui']
    source = source_class(str(tmp_path), requests.Session(), None)

    assert source_class.configured_browser_mode() == 'requests'
    assert source.browser_mode == 'requests'


def test_runtime_config_rejects_unknown_sources():
    runtime_config = RuntimeConfig(sources={'unknown': SourceRuntimeConfig(enabled=True)})

    with pytest.raises(ValueError, match='Unknown source'):
        load_source_classes(runtime_config=runtime_config)


def test_runtime_sample_matches_known_sources():
    runtime_config = RuntimeConfig.load('configs/runtime.sample.json')
    sources = load_source_classes(runtime_config=runtime_config, include_deprecated=True)

    assert set(runtime_config.sources) == {
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
    }
    assert set(sources) == {
        source_name
        for source_name, source_config in runtime_config.sources.items()
        if source_config.enabled
    }
