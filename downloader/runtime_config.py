from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from downloader.browser.modes import BrowserModeName, normalize_browser_mode


@dataclass(frozen=True)
class SourceRuntimeConfig:
    enabled: bool | None = None
    browser_mode: BrowserModeName | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    sources: dict[str, SourceRuntimeConfig] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> RuntimeConfig:
        config_path = Path(path)
        with open(config_path, encoding='utf-8-sig') as f:
            raw_config = json.load(f)
        return cls.from_mapping(raw_config, path=config_path)

    @classmethod
    def from_mapping(cls, raw_config: Any, path: Path | None = None) -> RuntimeConfig:
        if raw_config is None:
            return cls(path=path)
        if not isinstance(raw_config, dict):
            raise ValueError('Runtime config must be a JSON object.')

        raw_sources = raw_config.get('sources', {})
        if not isinstance(raw_sources, dict):
            raise ValueError('Runtime config field "sources" must be an object.')

        sources = {
            str(source_name): _parse_source_config(str(source_name), source_config)
            for source_name, source_config in raw_sources.items()
        }
        return cls(sources=sources, path=path)

    def source_config(self, source_name: str) -> SourceRuntimeConfig | None:
        return self.sources.get(source_name)

    def enabled_override(self, source_name: str) -> bool | None:
        source_config = self.source_config(source_name)
        return source_config.enabled if source_config else None

    def browser_mode_override(self, source_name: str) -> BrowserModeName | None:
        source_config = self.source_config(source_name)
        return source_config.browser_mode if source_config else None


def _parse_source_config(source_name: str, raw_config: Any) -> SourceRuntimeConfig:
    if isinstance(raw_config, bool):
        return SourceRuntimeConfig(enabled=raw_config)
    if not isinstance(raw_config, dict):
        raise ValueError(f'Runtime config for source "{source_name}" must be an object or boolean.')

    unknown_keys = set(raw_config) - {'enabled', 'browser_mode'}
    if unknown_keys:
        unknown = ', '.join(sorted(unknown_keys))
        raise ValueError(f'Unknown runtime config key(s) for source "{source_name}": {unknown}.')

    enabled = None
    if 'enabled' in raw_config:
        enabled = _parse_optional_bool(source_name, raw_config['enabled'])

    browser_mode = None
    if raw_config.get('browser_mode') is not None:
        browser_mode = normalize_browser_mode(raw_config['browser_mode'])

    return SourceRuntimeConfig(enabled=enabled, browser_mode=browser_mode)


def _parse_optional_bool(source_name: str, value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f'Runtime config field "sources.{source_name}.enabled" must be a boolean.')
