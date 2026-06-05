from __future__ import annotations

from downloader.boya import BoyaComic
from downloader.morui import MoruiComic
from downloader.runtime_config import RuntimeConfig, SourceRuntimeConfig
from downloader.source_profiles import resolve_source_profile
from downloader.sources import SOURCE_DEFINITIONS


def _definition(source_name: str):
    return next(
        definition
        for definition in SOURCE_DEFINITIONS
        if definition.module_name == source_name
    )


def test_site_json_generic_keys_override_class_defaults():
    profile = resolve_source_profile(_definition('morui'), MoruiComic)

    assert profile.base_url == 'https://www.morui.com'
    assert profile.base_img_url == 'http://lao.haotu90.top'
    assert profile.browser_mode == 'seleniumbase'
    assert profile.browser_wait_selector == '.page-main'
    assert profile.browser_headless is False


def test_runtime_browser_mode_override_resolves_without_class_mutation():
    runtime_config = RuntimeConfig(
        sources={'morui': SourceRuntimeConfig(browser_mode='requests')}
    )

    profile = resolve_source_profile(
        _definition('morui'),
        MoruiComic,
        runtime_config=runtime_config,
    )

    assert profile.browser_mode == 'requests'
    assert MoruiComic.browser_mode == 'cloakbrowser'


def test_parser_specific_site_config_remains_available():
    profile = resolve_source_profile(_definition('morui'), MoruiComic)

    assert profile.raw_site_config['search_xpath'] == "//li[contains(@class,'item-lg')]"
    assert profile.raw_site_config['imgs_js'].startswith('return typeof chapterImages')


def test_runtime_enabled_override_controls_profile_enabled():
    runtime_config = RuntimeConfig(sources={'boya': SourceRuntimeConfig(enabled=True)})

    profile = resolve_source_profile(
        _definition('boya'),
        BoyaComic,
        runtime_config=runtime_config,
    )

    assert profile.enabled is True
