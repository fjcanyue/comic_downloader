from __future__ import annotations

import importlib
from dataclasses import dataclass

from downloader.comic import ComicSource


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
    SourceDefinition('manhuagui', 'ManhuaguiComic', deprecated=True),
    SourceDefinition('manhuazhan', 'ManhuazhanComic', deprecated=True),
    SourceDefinition('maofly', 'MaoflyComic', enabled=False, deprecated=True),
    SourceDefinition('morui', 'MoruiComic'),
    SourceDefinition('thmh', 'TmhComic', deprecated=True),
)


def get_source_definitions(include_deprecated: bool = False) -> list[SourceDefinition]:
    return [
        definition
        for definition in SOURCE_DEFINITIONS
        if definition.enabled and (include_deprecated or not definition.deprecated)
    ]


def load_source_classes(include_deprecated: bool = False) -> dict[str, type[ComicSource]]:
    sources: dict[str, type[ComicSource]] = {}
    for definition in get_source_definitions(include_deprecated=include_deprecated):
        module = importlib.import_module(f'downloader.{definition.module_name}')
        source_class = getattr(module, definition.class_name)
        if not issubclass(source_class, ComicSource):
            raise TypeError(f'{definition.class_name} is not a ComicSource')
        sources[definition.module_name] = source_class
    return sources
