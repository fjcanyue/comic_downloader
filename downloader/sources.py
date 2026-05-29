from __future__ import annotations

import importlib
from dataclasses import dataclass

from downloader.comic import ComicSource
from downloader.runtime_config import RuntimeConfig


@dataclass(frozen=True)
class SourceDefinition:
    module_name: str
    class_name: str
    enabled: bool = True
    deprecated: bool = False


SOURCE_DEFINITIONS = (
    SourceDefinition('boya', 'BoyaComic', enabled=False, deprecated=True),
    SourceDefinition('dmzj', 'DmzjComic', enabled=False, deprecated=True),
    SourceDefinition('dumanwu', 'DumanwuComic'),
    SourceDefinition('manhuafree', 'ManhuafreeComic'),
    SourceDefinition('manhuagui', 'ManhuaguiComic'),
    SourceDefinition('manhuazhan', 'ManhuazhanComic'),
    SourceDefinition('maofly', 'MaoflyComic', enabled=False, deprecated=True),
    SourceDefinition('morui', 'MoruiComic'),
    SourceDefinition('thmh', 'TmhComic'),
    SourceDefinition('tuku', 'TukuComic'),
)


def get_source_definitions(
    include_deprecated: bool = False, runtime_config: RuntimeConfig | None = None
) -> list[SourceDefinition]:
    validate_runtime_config_sources(runtime_config)
    return [
        definition
        for definition in SOURCE_DEFINITIONS
        if _source_is_enabled(definition, include_deprecated, runtime_config)
    ]


def load_source_classes(
    include_deprecated: bool = False, runtime_config: RuntimeConfig | None = None
) -> dict[str, type[ComicSource]]:
    sources: dict[str, type[ComicSource]] = {}
    for definition in get_source_definitions(
        include_deprecated=include_deprecated, runtime_config=runtime_config
    ):
        module = importlib.import_module(f'downloader.{definition.module_name}')
        source_class = getattr(module, definition.class_name)
        if not issubclass(source_class, ComicSource):
            raise TypeError(f'{definition.class_name} is not a ComicSource')
        _apply_runtime_source_config(source_class, definition.module_name, runtime_config)
        sources[definition.module_name] = source_class
    return sources


def _source_is_enabled(
    definition: SourceDefinition,
    include_deprecated: bool,
    runtime_config: RuntimeConfig | None,
) -> bool:
    if runtime_config:
        enabled = runtime_config.enabled_override(definition.module_name)
        if enabled is not None:
            return enabled
    return definition.enabled and (include_deprecated or not definition.deprecated)


def _apply_runtime_source_config(
    source_class: type[ComicSource],
    source_name: str,
    runtime_config: RuntimeConfig | None,
) -> None:
    browser_mode = runtime_config.browser_mode_override(source_name) if runtime_config else None
    source_class._runtime_browser_mode_override = browser_mode


def validate_runtime_config_sources(runtime_config: RuntimeConfig | None) -> None:
    if not runtime_config:
        return
    known_sources = {definition.module_name for definition in SOURCE_DEFINITIONS}
    unknown_sources = sorted(set(runtime_config.sources) - known_sources)
    if unknown_sources:
        unknown = ', '.join(unknown_sources)
        raise ValueError(f'Unknown source(s) in runtime config: {unknown}.')
