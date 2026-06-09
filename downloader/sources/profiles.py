from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from downloader.browser.modes import (
    REQUESTS_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
    normalize_browser_mode,
)
from downloader.runtime_config import RuntimeConfig
from downloader.sources.config_keys import SOURCE_CONFIG_ATTRIBUTE_KEYS

PROFILE_ATTRIBUTE_DEFAULTS: dict[str, Any] = {
    'base_url': '',
    'base_img_url': '',
    'browser_mode': REQUESTS_MODE,
    'download_interval': 0,
    'image_request_interval': None,
    'page_load_wait_seconds': None,
    'scroll_wait_seconds': None,
    'max_scroll_attempts': None,
    'download_requires_driver': False,
    'search_requires_driver': False,
    'image_retry_count': 1,
    'max_download_workers': 5,
    'browser_wait_selector': None,
    'browser_wait_seconds': None,
    'browser_headless': None,
    'seleniumbase_wait_selector': None,
    'seleniumbase_wait_seconds': 20.0,
    'seleniumbase_headless': None,
    'cloakbrowser_humanize': True,
    'cloakbrowser_options': None,
}

PROFILE_MIRROR_ATTRIBUTE_KEYS = tuple(PROFILE_ATTRIBUTE_DEFAULTS)


@dataclass(frozen=True)
class SourceProfile:
    source_name: str
    class_name: str
    enabled: bool
    deprecated: bool
    base_url: str = ''
    base_img_url: str = ''
    browser_mode: BrowserModeName = REQUESTS_MODE
    download_interval: float = 0
    image_request_interval: float | None = None
    page_load_wait_seconds: float | None = None
    scroll_wait_seconds: float | None = None
    max_scroll_attempts: int | None = None
    download_requires_driver: bool = False
    search_requires_driver: bool = False
    image_retry_count: int = 1
    max_download_workers: int = 5
    browser_wait_selector: str | None = None
    browser_wait_seconds: float | None = None
    browser_headless: bool | None = None
    seleniumbase_wait_selector: str | None = None
    seleniumbase_wait_seconds: float = 20.0
    seleniumbase_headless: bool | None = None
    cloakbrowser_humanize: bool = True
    cloakbrowser_options: dict[str, Any] | None = None
    raw_site_config: Mapping[str, Any] = field(default_factory=dict)

    def browser_mode_uses_driver(self) -> bool:
        return is_driver_backed_browser_mode(self.browser_mode)

    def uses_driver_for_search(self) -> bool:
        return self.search_requires_driver or self.browser_mode_uses_driver()

    def uses_driver_for_download(self) -> bool:
        return self.download_requires_driver or self.browser_mode_uses_driver()


@dataclass(frozen=True)
class SourceBinding:
    source_name: str
    source_class: type[Any]
    profile: SourceProfile


def resolve_source_profile(
    definition: Any,
    source_class: type[Any],
    *,
    include_deprecated: bool = False,
    runtime_config: RuntimeConfig | None = None,
    session_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> SourceProfile:
    raw_site_config = load_site_config(source_class)
    values = _class_profile_values(source_class)
    values.update(_site_profile_values(raw_site_config))

    runtime_source_config = (
        runtime_config.source_config(definition.module_name) if runtime_config else None
    )
    if runtime_source_config and runtime_source_config.browser_mode is not None:
        values['browser_mode'] = runtime_source_config.browser_mode

    source_session_overrides = (
        session_overrides.get(definition.module_name, {}) if session_overrides else {}
    )
    values.update(_known_profile_values(source_session_overrides))

    values = _normalize_profile_values(values)
    return SourceProfile(
        source_name=definition.module_name,
        class_name=definition.class_name,
        enabled=source_is_enabled(definition, include_deprecated, runtime_config),
        deprecated=bool(definition.deprecated),
        raw_site_config=_freeze_mapping(raw_site_config),
        **values,
    )


def source_is_enabled(
    definition: Any,
    include_deprecated: bool,
    runtime_config: RuntimeConfig | None,
) -> bool:
    if runtime_config:
        enabled = runtime_config.enabled_override(definition.module_name)
        if enabled is not None:
            return enabled
    return bool(definition.enabled) and (include_deprecated or not definition.deprecated)


def load_site_config(source_class: type[Any]) -> dict[str, Any]:
    config_file = getattr(source_class, 'config_file', None)
    if not config_file:
        return {}
    config_path = source_config_base_path() / 'configs' / str(config_file)
    try:
        with open(config_path, encoding='utf-8') as f:
            raw_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_config, dict):
        return {}
    return raw_config


def source_config_base_path() -> Path:
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parents[2]


def mutable_site_config(profile: SourceProfile) -> dict[str, Any]:
    return copy.deepcopy(dict(profile.raw_site_config))


def _class_profile_values(source_class: type[Any]) -> dict[str, Any]:
    values = copy.deepcopy(PROFILE_ATTRIBUTE_DEFAULTS)
    for key in PROFILE_ATTRIBUTE_DEFAULTS:
        if hasattr(source_class, key):
            values[key] = copy.deepcopy(getattr(source_class, key))
    return values


def _site_profile_values(raw_site_config: Mapping[str, Any]) -> dict[str, Any]:
    return _known_profile_values(
        {
            key: raw_site_config[key]
            for key in SOURCE_CONFIG_ATTRIBUTE_KEYS
            if key in raw_site_config
        }
    )


def _known_profile_values(raw_values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in raw_values.items()
        if key in PROFILE_ATTRIBUTE_DEFAULTS
    }


def _normalize_profile_values(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    normalized['browser_mode'] = normalize_browser_mode(normalized.get('browser_mode'))
    normalized['download_interval'] = float(normalized.get('download_interval') or 0)
    normalized['image_request_interval'] = _optional_float(normalized.get('image_request_interval'))
    normalized['page_load_wait_seconds'] = _optional_float(normalized.get('page_load_wait_seconds'))
    normalized['scroll_wait_seconds'] = _optional_float(normalized.get('scroll_wait_seconds'))
    normalized['max_scroll_attempts'] = _optional_int(normalized.get('max_scroll_attempts'))
    normalized['image_retry_count'] = int(normalized.get('image_retry_count') or 1)
    normalized['max_download_workers'] = max(1, int(normalized.get('max_download_workers') or 5))
    normalized['browser_wait_seconds'] = _optional_float(normalized.get('browser_wait_seconds'))
    normalized['seleniumbase_wait_seconds'] = float(
        normalized.get('seleniumbase_wait_seconds') or 0
    )
    options = normalized.get('cloakbrowser_options')
    normalized['cloakbrowser_options'] = dict(options) if isinstance(options, dict) else None
    return normalized


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _freeze_mapping(raw_config: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(copy.deepcopy(dict(raw_config)))
