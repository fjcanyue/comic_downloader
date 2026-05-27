from __future__ import annotations

from downloader.sources import load_source_classes


def test_default_sources_include_cloakbrowser_morui():
    sources = load_source_classes()

    assert 'morui' in sources
    assert sources['morui'].browser_mode == 'cloakbrowser'


def test_deprecated_sources_include_morui_and_deprecated_sources():
    sources = load_source_classes(include_deprecated=True)

    assert 'morui' in sources
    assert 'manhuagui' in sources
