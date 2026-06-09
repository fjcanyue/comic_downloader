# Downloader Package Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the crowded `downloader/` flat module layout into focused `browser`, `download`, `sources`, and `sources.adapters` subpackages without preserving old top-level source adapter imports.

**Architecture:** Source registry and profile resolution move under `downloader.sources`, concrete site adapters move under `downloader.sources.adapters`, browser/page-loading helpers move under `downloader.browser`, and archive/image/volume download helpers move under `downloader.download`. `downloader.sources` remains the package-level registry API through explicit re-exports, while concrete adapters are only imported from `downloader.sources.adapters.<source_name>`.

**Tech Stack:** Python 3.10, pytest, Ruff, setuptools package discovery, PyInstaller.

---

### Task 1: Add Package Structure Characterization Tests

**Files:**
- Create: `tests/test_package_structure.py`

- [ ] **Step 1: Write tests for the target import contract**

```python
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import toml


SOURCE_ADAPTER_MODULES = (
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
)


@pytest.mark.parametrize('module_name', SOURCE_ADAPTER_MODULES)
def test_source_adapters_import_from_nested_package(module_name):
    module = importlib.import_module(f'downloader.sources.adapters.{module_name}')

    assert module.__name__ == f'downloader.sources.adapters.{module_name}'


@pytest.mark.parametrize('module_name', SOURCE_ADAPTER_MODULES)
def test_top_level_source_adapter_imports_are_removed(module_name):
    full_name = f'downloader.{module_name}'
    sys.modules.pop(full_name, None)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(full_name)


def test_sources_package_exposes_registry_api():
    sources = importlib.import_module('downloader.sources')

    assert hasattr(sources, 'SOURCE_DEFINITIONS')
    assert hasattr(sources, 'SourceDefinition')
    assert hasattr(sources, 'get_source_definitions')
    assert hasattr(sources, 'load_source_bindings')
    assert hasattr(sources, 'load_source_classes')
    assert hasattr(sources, 'validate_runtime_config_sources')


def test_setuptools_discovers_downloader_subpackages():
    pyproject = toml.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    assert pyproject['tool']['setuptools']['packages']['find']['include'] == [
        'downloader*'
    ]
```

- [ ] **Step 2: Run the new tests to verify they fail before migration**

Run: `rtk uv run pytest tests/test_package_structure.py -q`

Expected: FAIL because `downloader.sources.adapters.*` does not exist yet, old top-level source adapter modules still exist, and `pyproject.toml` still uses `packages = ["downloader"]`.

- [ ] **Step 3: Commit if repository metadata is writable**

Run: `rtk git add tests/test_package_structure.py`

Run: `rtk git commit -m "test: characterize downloader package structure"`

Expected in a normal checkout: commit succeeds. Expected in the current sandbox: commit is blocked because `.git/index.lock` cannot be created with the active permissions.

### Task 2: Create Subpackages And Move Files

**Files:**
- Create: `downloader/browser/__init__.py`
- Create: `downloader/download/__init__.py`
- Create: `downloader/sources/__init__.py`
- Create: `downloader/sources/adapters/__init__.py`
- Move: `downloader/archive.py` -> `downloader/download/archive.py`
- Move: `downloader/image_downloader.py` -> `downloader/download/images.py`
- Move: `downloader/volume_downloader.py` -> `downloader/download/volume.py`
- Move: `downloader/browser_drivers.py` -> `downloader/browser/drivers.py`
- Move: `downloader/browser_modes.py` -> `downloader/browser/modes.py`
- Move: `downloader/html_parser.py` -> `downloader/browser/html_parser.py`
- Move: `downloader/page_loading.py` -> `downloader/browser/page_loading.py`
- Move: `downloader/scroll_loader.py` -> `downloader/browser/scroll_loader.py`
- Move: `downloader/sources.py` -> `downloader/sources/registry.py`
- Move: `downloader/source_profiles.py` -> `downloader/sources/profiles.py`
- Move: `downloader/source_config.py` -> `downloader/sources/config_keys.py`
- Move: `downloader/source_templates.py` -> `downloader/sources/templates.py`
- Move: `downloader/boya.py` -> `downloader/sources/adapters/boya.py`
- Move: `downloader/dmzj.py` -> `downloader/sources/adapters/dmzj.py`
- Move: `downloader/dumanwu.py` -> `downloader/sources/adapters/dumanwu.py`
- Move: `downloader/manhuafree.py` -> `downloader/sources/adapters/manhuafree.py`
- Move: `downloader/manhuagui.py` -> `downloader/sources/adapters/manhuagui.py`
- Move: `downloader/manhuazhan.py` -> `downloader/sources/adapters/manhuazhan.py`
- Move: `downloader/maofly.py` -> `downloader/sources/adapters/maofly.py`
- Move: `downloader/morui.py` -> `downloader/sources/adapters/morui.py`
- Move: `downloader/thmh.py` -> `downloader/sources/adapters/thmh.py`
- Move: `downloader/tuku.py` -> `downloader/sources/adapters/tuku.py`

- [ ] **Step 1: Verify all move targets resolve inside the workspace**

Run:

```powershell
rtk powershell -NoProfile -Command '$root = (Resolve-Path .).Path; $targets = @("downloader/browser","downloader/download","downloader/sources","downloader/sources/adapters"); foreach ($target in $targets) { $full = Join-Path $root $target; if (-not $full.StartsWith($root)) { throw "Unsafe target: $full" }; Write-Output $full }'
```

Expected: prints four paths under `C:\projects\comic_downloader`.

- [ ] **Step 2: Create package directories**

Run:

```powershell
rtk powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path downloader/browser,downloader/download,downloader/sources,downloader/sources/adapters | Out-Null"
```

Expected: directories exist under `downloader/`.

- [ ] **Step 3: Add package initializer files**

Add `downloader/browser/__init__.py`:

```python
"""Browser and page loading runtime helpers."""
```

Add `downloader/download/__init__.py`:

```python
"""Download pipeline helpers."""
```

Add `downloader/sources/adapters/__init__.py`:

```python
"""Concrete comic source adapters."""
```

Add `downloader/sources/__init__.py`:

```python
from downloader.sources.registry import (
    SOURCE_DEFINITIONS,
    SourceDefinition,
    get_source_definitions,
    load_source_bindings,
    load_source_classes,
    validate_runtime_config_sources,
)

__all__ = [
    'SOURCE_DEFINITIONS',
    'SourceDefinition',
    'get_source_definitions',
    'load_source_bindings',
    'load_source_classes',
    'validate_runtime_config_sources',
]
```

- [ ] **Step 4: Move browser and download modules**

Run:

```powershell
rtk powershell -NoProfile -Command "Move-Item -LiteralPath downloader/browser_drivers.py -Destination downloader/browser/drivers.py; Move-Item -LiteralPath downloader/browser_modes.py -Destination downloader/browser/modes.py; Move-Item -LiteralPath downloader/html_parser.py -Destination downloader/browser/html_parser.py; Move-Item -LiteralPath downloader/page_loading.py -Destination downloader/browser/page_loading.py; Move-Item -LiteralPath downloader/scroll_loader.py -Destination downloader/browser/scroll_loader.py; Move-Item -LiteralPath downloader/archive.py -Destination downloader/download/archive.py; Move-Item -LiteralPath downloader/image_downloader.py -Destination downloader/download/images.py; Move-Item -LiteralPath downloader/volume_downloader.py -Destination downloader/download/volume.py"
```

Expected: old files are removed from `downloader/`, and new files exist in `downloader/browser/` and `downloader/download/`.

- [ ] **Step 5: Move source registry/profile/template modules and adapters**

Run:

```powershell
rtk powershell -NoProfile -Command "Move-Item -LiteralPath downloader/sources.py -Destination downloader/sources/registry.py; Move-Item -LiteralPath downloader/source_profiles.py -Destination downloader/sources/profiles.py; Move-Item -LiteralPath downloader/source_config.py -Destination downloader/sources/config_keys.py; Move-Item -LiteralPath downloader/source_templates.py -Destination downloader/sources/templates.py; Move-Item -LiteralPath downloader/boya.py -Destination downloader/sources/adapters/boya.py; Move-Item -LiteralPath downloader/dmzj.py -Destination downloader/sources/adapters/dmzj.py; Move-Item -LiteralPath downloader/dumanwu.py -Destination downloader/sources/adapters/dumanwu.py; Move-Item -LiteralPath downloader/manhuafree.py -Destination downloader/sources/adapters/manhuafree.py; Move-Item -LiteralPath downloader/manhuagui.py -Destination downloader/sources/adapters/manhuagui.py; Move-Item -LiteralPath downloader/manhuazhan.py -Destination downloader/sources/adapters/manhuazhan.py; Move-Item -LiteralPath downloader/maofly.py -Destination downloader/sources/adapters/maofly.py; Move-Item -LiteralPath downloader/morui.py -Destination downloader/sources/adapters/morui.py; Move-Item -LiteralPath downloader/thmh.py -Destination downloader/sources/adapters/thmh.py; Move-Item -LiteralPath downloader/tuku.py -Destination downloader/sources/adapters/tuku.py"
```

Expected: old top-level source files are removed, and new files exist under `downloader/sources/`.

- [ ] **Step 6: Inspect moved file set**

Run: `rtk rg --files downloader`

Expected: output includes `downloader/browser/...`, `downloader/download/...`, `downloader/sources/registry.py`, `downloader/sources/profiles.py`, and all `downloader/sources/adapters/*.py`. Output does not include old files such as `downloader/morui.py`, `downloader/browser_modes.py`, `downloader/html_parser.py`, or `downloader/volume_downloader.py`.

### Task 3: Update Browser And Download Imports

**Files:**
- Modify: `downloader/comic.py`
- Modify: `downloader/download/archive.py`
- Modify: `downloader/download/images.py`
- Modify: `downloader/download/volume.py`
- Modify: `downloader/browser/html_parser.py`
- Modify: `downloader/browser/page_loading.py`
- Modify: `downloader/models.py`
- Modify: `downloader/runtime_config.py`
- Modify: `downloader/shell.py`
- Modify: `tests/test_download_resume.py`
- Modify: `tests/test_page_loading.py`
- Modify: `tests/test_seleniumbase_html.py`
- Modify: `tests/test_volume_downloader.py`

- [ ] **Step 1: Update imports in `downloader/comic.py`**

Replace:

```python
from downloader.archive import ArchiveMixin
from downloader.browser_modes import (
    REQUESTS_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
    normalize_browser_mode,
)
from downloader.html_parser import HtmlParsingMixin
from downloader.image_downloader import ImageDownloadMixin
from downloader.source_config import SOURCE_CONFIG_ATTRIBUTE_KEYS
from downloader.source_profiles import (
    PROFILE_MIRROR_ATTRIBUTE_KEYS,
    SourceProfile,
    mutable_site_config,
)
from downloader.volume_downloader import download_volume
```

with:

```python
from downloader.browser.modes import (
    REQUESTS_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
    normalize_browser_mode,
)
from downloader.browser.html_parser import HtmlParsingMixin
from downloader.download.archive import ArchiveMixin
from downloader.download.images import ImageDownloadMixin
from downloader.download.volume import download_volume
from downloader.sources.config_keys import SOURCE_CONFIG_ATTRIBUTE_KEYS
from downloader.sources.profiles import (
    PROFILE_MIRROR_ATTRIBUTE_KEYS,
    SourceProfile,
    mutable_site_config,
)
```

- [ ] **Step 2: Update imports in moved browser/download modules**

In `downloader/browser/page_loading.py`, replace:

```python
from downloader.browser_modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, BrowserModeName
```

with:

```python
from downloader.browser.modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, BrowserModeName
```

In `downloader/browser/html_parser.py`, replace:

```python
from downloader.browser_drivers import configure_seleniumbase_driver_cache
from downloader.browser_modes import (
    CLOAKBROWSER_MODE,
    REQUESTS_MODE,
    SELENIUMBASE_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
)
from downloader.page_loading import PageLoadAdapters, PageLoader, PageLoadRequest, PageLoadResult
```

with:

```python
from downloader.browser.drivers import configure_seleniumbase_driver_cache
from downloader.browser.modes import (
    CLOAKBROWSER_MODE,
    REQUESTS_MODE,
    SELENIUMBASE_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
)
from downloader.browser.page_loading import (
    PageLoadAdapters,
    PageLoader,
    PageLoadRequest,
    PageLoadResult,
)
```

In `downloader/download/images.py`, replace:

```python
from downloader.browser_modes import SELENIUMBASE_MODE
```

with:

```python
from downloader.browser.modes import SELENIUMBASE_MODE
```

In `downloader/download/archive.py`, keep model imports as:

```python
from downloader.models import (
    VolumeFileState,
    filter_dir_name,
)
```

In `downloader/download/volume.py`, keep model imports as:

```python
from downloader.models import VolumeDownloadResult, filter_dir_name
```

- [ ] **Step 3: Update root runtime imports**

In `downloader/models.py`, replace:

```python
from downloader.browser_modes import BrowserModeName
```

with:

```python
from downloader.browser.modes import BrowserModeName
```

In `downloader/runtime_config.py`, replace:

```python
from downloader.browser_modes import BrowserModeName, normalize_browser_mode
```

with:

```python
from downloader.browser.modes import BrowserModeName, normalize_browser_mode
```

In `downloader/shell.py`, replace:

```python
from downloader.browser_drivers import CloakBrowserDriver, SeleniumBaseDriver
from downloader.browser_modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, normalize_browser_mode
from downloader.source_profiles import SourceBinding, SourceProfile
```

with:

```python
from downloader.browser.drivers import CloakBrowserDriver, SeleniumBaseDriver
from downloader.browser.modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, normalize_browser_mode
from downloader.sources.profiles import SourceBinding, SourceProfile
```

- [ ] **Step 4: Update test imports for browser/download modules**

In `tests/test_page_loading.py`, replace:

```python
from downloader.browser_modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
from downloader.page_loading import PageLoadAdapters, PageLoader, PageLoadRequest
```

with:

```python
from downloader.browser.modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
from downloader.browser.page_loading import PageLoadAdapters, PageLoader, PageLoadRequest
```

In `tests/test_seleniumbase_html.py`, replace:

```python
from downloader.browser_modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
```

with:

```python
from downloader.browser.modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
```

In `tests/test_volume_downloader.py`, replace:

```python
from downloader.volume_downloader import download_volume
```

with:

```python
from downloader.download.volume import download_volume
```

- [ ] **Step 5: Run import scan for old browser/download paths**

Run:

```powershell
rtk rg -n "downloader\.(archive|browser_drivers|browser_modes|html_parser|image_downloader|page_loading|scroll_loader|volume_downloader)" downloader tests main.py
```

Expected: no matches.

### Task 4: Update Source Package Imports And Registry

**Files:**
- Modify: `downloader/sources/registry.py`
- Modify: `downloader/sources/profiles.py`
- Modify: `downloader/sources/adapters/boya.py`
- Modify: `downloader/sources/adapters/dmzj.py`
- Modify: `downloader/sources/adapters/dumanwu.py`
- Modify: `downloader/sources/adapters/manhuafree.py`
- Modify: `downloader/sources/adapters/manhuagui.py`
- Modify: `downloader/sources/adapters/manhuazhan.py`
- Modify: `downloader/sources/adapters/maofly.py`
- Modify: `downloader/sources/adapters/morui.py`
- Modify: `downloader/sources/adapters/thmh.py`
- Modify: `downloader/sources/adapters/tuku.py`
- Modify: `tests/test_source_profiles.py`
- Modify: `tests/test_seleniumbase_html.py`
- Modify: `tests/test_shell_driver_lifecycle.py`

- [ ] **Step 1: Update source registry imports and dynamic adapter loading**

In `downloader/sources/registry.py`, replace:

```python
from downloader.source_profiles import SourceBinding, resolve_source_profile, source_is_enabled
```

with:

```python
from downloader.sources.profiles import SourceBinding, resolve_source_profile, source_is_enabled
```

Replace:

```python
module = importlib.import_module(f'downloader.{definition.module_name}')
```

with:

```python
module = importlib.import_module(f'downloader.sources.adapters.{definition.module_name}')
```

- [ ] **Step 2: Update source profile imports**

In `downloader/sources/profiles.py`, replace:

```python
from downloader.browser_modes import (
    REQUESTS_MODE,
    BrowserModeName,
    normalize_browser_mode,
)
from downloader.source_config import SOURCE_CONFIG_ATTRIBUTE_KEYS
```

with:

```python
from downloader.browser.modes import (
    REQUESTS_MODE,
    BrowserModeName,
    normalize_browser_mode,
)
from downloader.sources.config_keys import SOURCE_CONFIG_ATTRIBUTE_KEYS
```

- [ ] **Step 3: Update source adapter imports that use browser modes**

In `downloader/sources/adapters/manhuafree.py`, replace:

```python
from downloader.browser_modes import REQUESTS_MODE
```

with:

```python
from downloader.browser.modes import REQUESTS_MODE
```

In `downloader/sources/adapters/morui.py`, replace:

```python
from downloader.browser_modes import CLOAKBROWSER_MODE
```

with:

```python
from downloader.browser.modes import CLOAKBROWSER_MODE
```

In `downloader/sources/adapters/tuku.py`, replace:

```python
from downloader.browser_modes import REQUESTS_MODE
```

with:

```python
from downloader.browser.modes import REQUESTS_MODE
```

- [ ] **Step 4: Update source adapter imports that use templates**

Replace every adapter import from:

```python
from downloader.source_templates import (
```

with:

```python
from downloader.sources.templates import (
```

For the single-line import in `downloader/sources/adapters/manhuazhan.py`, replace:

```python
from downloader.source_templates import GroupedChapterInfoMixin, JsDictImageSourceMixin
```

with:

```python
from downloader.sources.templates import GroupedChapterInfoMixin, JsDictImageSourceMixin
```

- [ ] **Step 5: Update concrete adapter imports in tests**

In `tests/test_source_profiles.py`, replace:

```python
from downloader.boya import BoyaComic
from downloader.morui import MoruiComic
from downloader.source_profiles import resolve_source_profile
```

with:

```python
from downloader.sources.adapters.boya import BoyaComic
from downloader.sources.adapters.morui import MoruiComic
from downloader.sources.profiles import resolve_source_profile
```

In `tests/test_seleniumbase_html.py`, replace:

```python
from downloader.morui import MoruiComic
from downloader.source_profiles import SourceProfile
```

with:

```python
from downloader.sources.adapters.morui import MoruiComic
from downloader.sources.profiles import SourceProfile
```

In `tests/test_shell_driver_lifecycle.py`, replace:

```python
from downloader.source_profiles import SourceProfile
```

with:

```python
from downloader.sources.profiles import SourceProfile
```

- [ ] **Step 6: Run import scan for old source paths**

Run:

```powershell
rtk rg -n "downloader\.(boya|dmzj|dumanwu|manhuafree|manhuagui|manhuazhan|maofly|morui|thmh|tuku|source_config|source_profiles|source_templates)" downloader tests main.py
```

Expected: no matches.

### Task 5: Update Packaging Configuration

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace explicit single-package config with package discovery**

Replace:

```toml
[tool.setuptools]
packages = ["downloader"]
```

with:

```toml
[tool.setuptools.packages.find]
include = ["downloader*"]
```

- [ ] **Step 2: Run the package structure test**

Run: `rtk uv run pytest tests/test_package_structure.py -q`

Expected: PASS.

- [ ] **Step 3: Inspect package discovery metadata**

Run: `rtk uv run python -c "from setuptools import find_packages; print(sorted(p for p in find_packages(include=['downloader*']) if p.startswith('downloader')))"`

Expected: output includes `downloader`, `downloader.browser`, `downloader.download`, `downloader.sources`, and `downloader.sources.adapters`.

### Task 6: Format And Run Focused Tests

**Files:**
- Formatting/test only.

- [ ] **Step 1: Format changed Python files**

Run:

```powershell
rtk uv run ruff format downloader tests/test_package_structure.py tests/test_page_loading.py tests/test_seleniumbase_html.py tests/test_shell_driver_lifecycle.py tests/test_source_profiles.py tests/test_volume_downloader.py
```

Expected: Ruff formats moved and changed Python files.

- [ ] **Step 2: Run source package tests**

Run:

```powershell
rtk uv run pytest tests/test_package_structure.py tests/test_sources.py tests/test_source_profiles.py -q
```

Expected: PASS.

- [ ] **Step 3: Run browser and page loading tests**

Run:

```powershell
rtk uv run pytest tests/test_page_loading.py tests/test_seleniumbase_html.py tests/test_shell_driver_lifecycle.py -q
```

Expected: PASS. If SeleniumBase-dependent tests fail due local browser or driver availability, record the exact failure and continue only after confirming the failure is environmental.

- [ ] **Step 4: Run download pipeline tests**

Run:

```powershell
rtk uv run pytest tests/test_volume_downloader.py tests/test_download_resume.py -q
```

Expected: PASS.

### Task 7: Run Full Verification And Build Check

**Files:**
- Test/build only.

- [ ] **Step 1: Run full test suite**

Run: `rtk uv run pytest -q`

Expected: PASS.

- [ ] **Step 2: Run Ruff check**

Run: `rtk uv run ruff check downloader tests main.py`

Expected: PASS.

- [ ] **Step 3: Run PyInstaller spec test**

Run: `rtk uv run pytest tests/test_downloader_spec.py -q`

Expected: PASS.

- [ ] **Step 4: Run PyInstaller build**

Run: `rtk uv run pyinstaller downloader.spec`

Expected: build succeeds and includes the moved `downloader.browser`, `downloader.download`, `downloader.sources`, and `downloader.sources.adapters` modules. If the build reports missing modules, update `downloader.spec` with the missing subpackage hidden imports and rerun this step.

- [ ] **Step 5: Scan for stale top-level files and imports**

Run:

```powershell
rtk rg --files downloader
```

Expected: no old top-level files remain for moved modules.

Run:

```powershell
rtk rg -n "downloader\.(archive|browser_drivers|browser_modes|boya|dmzj|dumanwu|html_parser|image_downloader|manhuafree|manhuagui|manhuazhan|maofly|morui|page_loading|scroll_loader|source_config|source_profiles|source_templates|thmh|tuku|volume_downloader)" downloader tests main.py
```

Expected: no matches.

- [ ] **Step 6: Commit if repository metadata is writable**

Run:

```powershell
rtk git add downloader tests pyproject.toml docs/superpowers/specs/2026-06-09-downloader-package-structure-design.md docs/superpowers/plans/2026-06-09-downloader-package-structure.md
```

Run:

```powershell
rtk git commit -m "refactor: organize downloader package structure"
```

Expected in a normal checkout: commit succeeds. Expected in the current sandbox: commit is blocked because `.git/index.lock` cannot be created with the active permissions.

---

## Self-Review

- Spec coverage: This plan covers the approved package layout, removed top-level source adapter paths, source registry dynamic import changes, internal import updates, packaging discovery, tests, Ruff, and PyInstaller verification.
- Placeholder scan: No TBD/TODO placeholders or deferred implementation steps remain.
- Type consistency: Module names are consistent across the target structure, import replacements, package structure tests, and verification scans.
