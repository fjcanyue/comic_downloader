import importlib

__all__ = [
    'SOURCE_DEFINITIONS',
    'SourceDefinition',
    'get_source_definitions',
    'load_source_bindings',
    'load_source_classes',
    'validate_runtime_config_sources',
]


def __getattr__(name: str):
    if name in __all__:
        registry = importlib.import_module('downloader.sources.registry')
        value = getattr(registry, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'downloader.sources' has no attribute {name!r}")
