# Downloader Package Structure Design

## Goal

Reorganize the crowded `downloader/` package into focused subpackages so source
adapters, browser/page-loading runtime code, download orchestration, source profile
resolution, and CLI shell code have clear ownership boundaries.

## Scope

This refactor is a pure package-structure migration. It should not change supported
comic sources, search behavior, page loading behavior, download behavior, retry
behavior, runtime configuration semantics, or shell commands.

The migration does not preserve old source adapter module paths such as
`downloader.morui` or `downloader.boya`. All internal imports and tests should move
to the new paths in the same change.

## Current State

`downloader/` currently contains every major concern at one level:

- source adapters: `boya.py`, `dmzj.py`, `dumanwu.py`, `manhuafree.py`,
  `manhuagui.py`, `manhuazhan.py`, `maofly.py`, `morui.py`, `thmh.py`, `tuku.py`;
- source registry/profile code: `sources.py`, `source_profiles.py`,
  `source_config.py`, `source_templates.py`;
- browser and page loading code: `browser_modes.py`, `browser_drivers.py`,
  `page_loading.py`, `scroll_loader.py`;
- download pipeline code: `archive.py`, `image_downloader.py`,
  `volume_downloader.py`;
- core model/source code: `comic.py`, `models.py`;
- runtime entry code: `shell.py`, `runtime_config.py`.

`downloader.sources.load_source_bindings()` dynamically imports source adapters with
`importlib.import_module(f'downloader.{definition.module_name}')`. Tests also import
some adapters directly through old top-level paths.

`pyproject.toml` currently declares only `packages = ["downloader"]`, so any new
subpackage layout requires a packaging update.

## Target Structure

Use subpackages that match the project concepts in `CONTEXT.md`:

```text
downloader/
  __init__.py
  comic.py
  models.py
  runtime_config.py
  shell.py
  browser/
    __init__.py
    drivers.py
    html_parser.py
    modes.py
    page_loading.py
    scroll_loader.py
  download/
    __init__.py
    archive.py
    images.py
    volume.py
  sources/
    __init__.py
    config_keys.py
    profiles.py
    registry.py
    templates.py
    adapters/
      __init__.py
      boya.py
      dmzj.py
      dumanwu.py
      manhuafree.py
      manhuagui.py
      manhuazhan.py
      maofly.py
      morui.py
      thmh.py
      tuku.py
```

`comic.py`, `models.py`, `runtime_config.py`, and `shell.py` stay at the package root
because they are broad entry points used across the runtime. Splitting those files by
behavior is outside this package layout refactor.

## Module Mapping

Move modules as follows:

```text
downloader/archive.py             -> downloader/download/archive.py
downloader/image_downloader.py    -> downloader/download/images.py
downloader/volume_downloader.py   -> downloader/download/volume.py

downloader/browser_drivers.py     -> downloader/browser/drivers.py
downloader/browser_modes.py       -> downloader/browser/modes.py
downloader/html_parser.py         -> downloader/browser/html_parser.py
downloader/page_loading.py        -> downloader/browser/page_loading.py
downloader/scroll_loader.py       -> downloader/browser/scroll_loader.py

downloader/sources.py             -> downloader/sources/registry.py
downloader/source_profiles.py     -> downloader/sources/profiles.py
downloader/source_config.py       -> downloader/sources/config_keys.py
downloader/source_templates.py    -> downloader/sources/templates.py

downloader/boya.py                -> downloader/sources/adapters/boya.py
downloader/dmzj.py                -> downloader/sources/adapters/dmzj.py
downloader/dumanwu.py             -> downloader/sources/adapters/dumanwu.py
downloader/manhuafree.py          -> downloader/sources/adapters/manhuafree.py
downloader/manhuagui.py           -> downloader/sources/adapters/manhuagui.py
downloader/manhuazhan.py          -> downloader/sources/adapters/manhuazhan.py
downloader/maofly.py              -> downloader/sources/adapters/maofly.py
downloader/morui.py               -> downloader/sources/adapters/morui.py
downloader/thmh.py                -> downloader/sources/adapters/thmh.py
downloader/tuku.py                -> downloader/sources/adapters/tuku.py
```

## Public Package Entrypoints

Keep source discovery available through the package-level `downloader.sources`
namespace by re-exporting the registry API from `downloader/sources/__init__.py`:

```python
from downloader.sources.registry import (
    SOURCE_DEFINITIONS,
    SourceDefinition,
    get_source_definitions,
    load_source_bindings,
    load_source_classes,
    validate_runtime_config_sources,
)
```

This keeps the logical `downloader.sources` entrypoint while dropping the old
adapter module paths.

Do not add compatibility shims for removed modules such as `downloader/morui.py`.
Tests and project imports should use `downloader.sources.adapters.morui` when they
need a concrete adapter class.

## Dynamic Source Loading

Update source registry dynamic imports to load adapter modules from the new
subpackage:

```python
module = importlib.import_module(
    f'downloader.sources.adapters.{definition.module_name}'
)
```

`SourceDefinition.module_name` remains the source business identifier, such as
`morui`, `dumanwu`, or `tuku`. Runtime config files and user-facing source names do
not change.

## Internal Imports

Update internal imports to match the new ownership boundaries:

- browser modes, drivers, HTML parsing, and page loading should import from
  `downloader.browser.*`;
- archive, image download, and volume download orchestration should import from
  `downloader.download.*`;
- source profiles, source config keys, templates, and registry APIs should import
  from `downloader.sources.*`;
- source adapters should import shared source templates from
  `downloader.sources.templates`;
- tests that need concrete adapter classes should import from
  `downloader.sources.adapters.<name>`.

`ComicSource` remains importable from `downloader.comic`, and model dataclasses remain
importable from `downloader.models`.

## Packaging

Change setuptools package discovery so subpackages are included in editable installs,
wheel builds, and packaged binaries:

```toml
[tool.setuptools.packages.find]
include = ["downloader*"]
```

Remove the old explicit single-package declaration:

```toml
[tool.setuptools]
packages = ["downloader"]
```

Verify `downloader.spec` after migration by running the configured PyInstaller build
command. If the build misses moved modules, add the new subpackage paths explicitly
to the spec before completing the refactor.

## Tests And Verification

Update import paths in tests and run focused checks before the full suite:

```powershell
rtk uv run pytest tests/test_sources.py tests/test_source_profiles.py tests/test_seleniumbase_html.py -q
rtk uv run pytest -q
rtk uv run ruff check downloader tests main.py
rtk uv run pyinstaller downloader.spec
```

The key regression signals are:

- `load_source_classes()` still returns the same enabled source keys by default;
- runtime config source names still match `configs/runtime.sample.json`;
- source profile resolution still applies JSON and runtime overrides;
- SeleniumBase/CloakBrowser page loading imports resolve from the browser package;
- download resume and volume pipeline tests still pass with the new download package;
- no test imports any removed top-level adapter module path.

## Non-Goals

This refactor does not:

- rename source business identifiers in configs or runtime config files;
- redesign source parser APIs;
- split `ComicSource` into smaller classes;
- rewrite shell command behavior;
- change the page loading fallback policy;
- change image download worker behavior;
- preserve removed adapter import paths.

## Rollout

Implement the migration in one focused phase:

1. Create `browser`, `download`, `sources`, and `sources.adapters` packages.
2. Move files according to the module mapping.
3. Update all imports in `downloader/`, `tests/`, and `main.py`.
4. Update source registry dynamic imports.
5. Re-export the registry API from `downloader.sources`.
6. Update setuptools package discovery.
7. Run targeted tests, full tests, and Ruff.
8. Remove any empty old files left behind by the move.

The change should be reviewed as a structural refactor. Any behavior change found
during implementation should either be fixed back to existing behavior or documented
as a separate follow-up before being implemented.
