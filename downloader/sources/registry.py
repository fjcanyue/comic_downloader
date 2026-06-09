from __future__ import annotations

import importlib
from dataclasses import dataclass

from downloader.comic import ComicSource
from downloader.runtime_config import RuntimeConfig
from downloader.sources.profiles import SourceBinding, resolve_source_profile, source_is_enabled


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
        if source_is_enabled(definition, include_deprecated, runtime_config)
    ]


def load_source_bindings(
    include_deprecated: bool = False, runtime_config: RuntimeConfig | None = None
) -> dict[str, SourceBinding]:
    validate_runtime_config_sources(runtime_config)
    bindings: dict[str, SourceBinding] = {}
    for definition in SOURCE_DEFINITIONS:
        module = importlib.import_module(f'downloader.sources.adapters.{definition.module_name}')
        source_class = getattr(module, definition.class_name)
        if not issubclass(source_class, ComicSource):
            raise TypeError(f'{definition.class_name} is not a ComicSource')
        profile = resolve_source_profile(
            definition,
            source_class,
            include_deprecated=include_deprecated,
            runtime_config=runtime_config,
        )
        if not profile.enabled:
            continue
        bindings[definition.module_name] = SourceBinding(
            source_name=definition.module_name,
            source_class=source_class,
            profile=profile,
        )
    return bindings


def load_source_classes(
    include_deprecated: bool = False, runtime_config: RuntimeConfig | None = None
) -> dict[str, type[ComicSource]]:
    return {
        source_name: binding.source_class
        for source_name, binding in load_source_bindings(
            include_deprecated=include_deprecated,
            runtime_config=runtime_config,
        ).items()
    }


def validate_runtime_config_sources(runtime_config: RuntimeConfig | None) -> None:
    if not runtime_config:
        return
    known_sources = {definition.module_name for definition in SOURCE_DEFINITIONS}
    unknown_sources = sorted(set(runtime_config.sources) - known_sources)
    if unknown_sources:
        unknown = ', '.join(unknown_sources)
        raise ValueError(f'Unknown source(s) in runtime config: {unknown}.')
