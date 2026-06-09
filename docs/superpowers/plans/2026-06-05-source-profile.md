# Source Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Honor the explicit user constraint for this work: do **not** use TDD/red-green-refactor. Add or update regression tests during the relevant implementation slice, then verify them.

**Goal:** Introduce a read-only `SourceProfile` so final source configuration is resolved in one place and runtime browser overrides no longer mutate source classes.

**Architecture:** Add a profile resolver that merges registry defaults, source class defaults, site JSON generic keys, runtime config, and optional session overrides. Shell and shared loading/download code consume profiles through source bindings, while source parsers keep legacy mirrored attributes and `self.config` during this phase.

**Tech Stack:** Python 3.10, dataclasses, requests, SeleniumBase/CloakBrowser adapters, pytest, ruff/pyright.

---

## Constraints

- Do not use a TDD red-green-refactor workflow.
- Keep individual source parser internals mostly unchanged.
- Keep parser-specific JSON keys in `self.config`; do not move them into explicit profile fields.
- Preserve `load_source_classes()` as a compatibility API.
- The current sandbox cannot write `.git/index.lock`, so commit steps require a writable git environment.

## File Structure

- Create `downloader/source_profiles.py`: `SourceProfile`, `SourceBinding`, resolver helpers, site JSON loader, profile value normalization.
- Modify `downloader/sources.py`: add profile-aware discovery APIs and remove runtime class mutation.
- Modify `downloader/comic.py`: accept an optional profile, mirror profile fields for legacy code, and stop using `_runtime_browser_mode_override`.
- Modify `downloader/html_parser.py`: prefer profile values for browser mode, base URL, wait settings, and non-sticky block fallback.
- Modify `downloader/image_downloader.py`: prefer profile values for base image URL, referer, intervals, retry count, and workers.
- Modify `downloader/shell.py`: use source bindings/profiles for source discovery, URL matching, source construction, and driver cache decisions.
- Add `tests/test_source_profiles.py`: resolver regression coverage.
- Modify `tests/test_sources.py`: profile-aware source discovery coverage.
- Modify `tests/test_shell_driver_lifecycle.py`: profile-aware driver lifecycle coverage.
- Modify `tests/test_seleniumbase_html.py`: fallback/profile regression coverage.
- Modify `README.md` and `docs/basic-usage.md`: explain runtime config now resolves through `SourceProfile`.

### Task 1: Add Source Profile Model And Resolver

**Files:**
- Create: `downloader/source_profiles.py`
- Test: `tests/test_source_profiles.py`

- [ ] **Step 1: Create the source profile module**

Add the dataclasses, defaults, config loading, and resolver in `downloader/source_profiles.py`.

```python
from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from downloader.browser_modes import (
    REQUESTS_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
    normalize_browser_mode,
)
from downloader.runtime_config import RuntimeConfig
from downloader.source_config import SOURCE_CONFIG_ATTRIBUTE_KEYS

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
    return Path(__file__).parent.parent


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
    normalized['image_request_interval'] = _optional_float(
        normalized.get('image_request_interval')
    )
    normalized['page_load_wait_seconds'] = _optional_float(
        normalized.get('page_load_wait_seconds')
    )
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
```

- [ ] **Step 2: Add resolver regression tests**

Create `tests/test_source_profiles.py` with coverage for JSON overrides, runtime overrides, parser config retention, and non-mutation.

```python
from __future__ import annotations

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
    from downloader.morui import MoruiComic

    profile = resolve_source_profile(_definition('morui'), MoruiComic)

    assert profile.base_url == 'https://www.morui.com'
    assert profile.base_img_url == 'http://lao.haotu90.top'
    assert profile.browser_mode == 'seleniumbase'
    assert profile.browser_wait_selector == '.page-main'
    assert profile.browser_headless is False


def test_runtime_browser_mode_override_resolves_without_class_mutation():
    from downloader.morui import MoruiComic

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
    from downloader.morui import MoruiComic

    profile = resolve_source_profile(_definition('morui'), MoruiComic)

    assert profile.raw_site_config['search_xpath'] == "//li[contains(@class,'item-lg')]"
    assert profile.raw_site_config['imgs_js'].startswith('return typeof chapterImages')


def test_runtime_enabled_override_controls_profile_enabled():
    from downloader.boya import BoyaComic

    runtime_config = RuntimeConfig(sources={'boya': SourceRuntimeConfig(enabled=True)})

    profile = resolve_source_profile(
        _definition('boya'),
        BoyaComic,
        runtime_config=runtime_config,
    )

    assert profile.enabled is True
```

- [ ] **Step 3: Verify focused tests**

Run:

```powershell
rtk uv run pytest tests/test_source_profiles.py -q
```

Expected: tests pass after implementation. Do not treat these as TDD red tests; they are regression coverage for the implemented resolver.

### Task 2: Add Profile-Aware Source Discovery

**Files:**
- Modify: `downloader/sources.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Replace runtime class mutation with source bindings**

In `downloader/sources.py`, import `SourceBinding`, `resolve_source_profile`, and `source_is_enabled`. Add `load_source_bindings()` and make `load_source_classes()` derive from bindings.

```python
from downloader.source_profiles import SourceBinding, resolve_source_profile, source_is_enabled
```

Replace `load_source_classes()` and `_source_is_enabled()` with this shape:

```python
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
    include_deprecated: bool = False,
    runtime_config: RuntimeConfig | None = None,
) -> dict[str, SourceBinding]:
    validate_runtime_config_sources(runtime_config)
    bindings: dict[str, SourceBinding] = {}
    for definition in SOURCE_DEFINITIONS:
        module = importlib.import_module(f'downloader.{definition.module_name}')
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
```

Delete `_apply_runtime_source_config()`.

- [ ] **Step 2: Update source discovery tests**

In `tests/test_sources.py`, import `load_source_bindings`. Keep compatibility assertions for `load_source_classes()`, and move runtime browser mode assertions to bindings/profiles.

```python
from downloader.sources import load_source_bindings, load_source_classes
```

Replace `test_runtime_config_browser_mode_overrides_site_config()` with:

```python
def test_runtime_config_browser_mode_overrides_profile_without_mutating_class(tmp_path):
    runtime_config = RuntimeConfig(
        sources={'morui': SourceRuntimeConfig(browser_mode='requests')}
    )

    bindings = load_source_bindings(runtime_config=runtime_config)
    binding = bindings['morui']
    source = binding.source_class(
        str(tmp_path),
        requests.Session(),
        None,
        profile=binding.profile,
    )

    assert binding.profile.browser_mode == 'requests'
    assert binding.source_class.configured_browser_mode() == 'seleniumbase'
    assert binding.source_class.browser_mode == 'cloakbrowser'
    assert source.browser_mode == 'requests'
```

Add:

```python
def test_load_source_classes_does_not_leak_runtime_browser_mode():
    runtime_config = RuntimeConfig(
        sources={'morui': SourceRuntimeConfig(browser_mode='requests')}
    )

    load_source_classes(runtime_config=runtime_config)
    default_sources = load_source_classes()

    assert default_sources['morui'].configured_browser_mode() == 'seleniumbase'
```

- [ ] **Step 3: Verify source discovery tests**

Run:

```powershell
rtk uv run pytest tests/test_source_profiles.py tests/test_sources.py -q
```

Expected: both files pass.

### Task 3: Attach Profiles To ComicSource Instances

**Files:**
- Modify: `downloader/comic.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Update `ComicSource.__init__()`**

In `downloader/comic.py`, import profile helpers:

```python
from downloader.source_profiles import (
    PROFILE_MIRROR_ATTRIBUTE_KEYS,
    SourceProfile,
    mutable_site_config,
)
```

Remove the `_runtime_browser_mode_override` class attribute from `ComicSource`.

Change the constructor signature:

```python
def __init__(
    self,
    output_dir: str,
    http: requests.Session,
    driver: Any,
    overwrite: bool = True,
    *,
    profile: SourceProfile | None = None,
) -> None:
```

After assigning runtime fields such as `self.output_dir`, `self.http`, and `self.driver`, set:

```python
self.profile: SourceProfile | None = profile
```

Replace the config-loading branch with:

```python
if profile is not None:
    self.config = mutable_site_config(profile)
    self._apply_source_profile(profile)
elif hasattr(self, 'config_file') and self.config_file:
    self.load_config()
elif hasattr(self, 'config') and self.config:
    pass
else:
    self.config = {}
```

Add:

```python
def _apply_source_profile(self, profile: SourceProfile) -> None:
    for key in PROFILE_MIRROR_ATTRIBUTE_KEYS:
        setattr(self, key, getattr(profile, key))
    self.browser_mode = normalize_browser_mode(profile.browser_mode)
```

Update `_apply_source_config()` to remove runtime override handling:

```python
def _apply_source_config(self) -> None:
    for key in SOURCE_CONFIG_ATTRIBUTE_KEYS:
        if key in self.config:
            setattr(self, key, self.config[key])
    self.browser_mode = normalize_browser_mode(getattr(self, 'browser_mode', REQUESTS_MODE))
```

Keep `configured_browser_mode()` reading class defaults plus site JSON. It should no longer inspect `_runtime_browser_mode_override`.

- [ ] **Step 2: Add compatibility assertions**

In `tests/test_sources.py`, add:

```python
def test_profiled_source_keeps_parser_config_and_mirrors_profile(tmp_path):
    bindings = load_source_bindings()
    binding = bindings['morui']

    source = binding.source_class(
        str(tmp_path),
        requests.Session(),
        None,
        profile=binding.profile,
    )

    assert source.profile is binding.profile
    assert source.browser_mode == binding.profile.browser_mode
    assert source.base_url == binding.profile.base_url
    assert source.config['search_xpath'] == "//li[contains(@class,'item-lg')]"
```

- [ ] **Step 3: Verify source instance tests**

Run:

```powershell
rtk uv run pytest tests/test_sources.py -q
```

Expected: source profile construction and legacy direct construction both pass.

### Task 4: Move Shell And Driver Lifecycle To Profiles

**Files:**
- Modify: `downloader/shell.py`
- Modify: `tests/test_shell_driver_lifecycle.py`

- [ ] **Step 1: Import profile-aware discovery**

In `downloader/shell.py`, change imports:

```python
from downloader.source_profiles import SourceBinding, SourceProfile
from downloader.sources import load_source_bindings, load_source_classes
```

Keep `load_source_classes` only if a compatibility path still needs it; otherwise remove the import after migration.

- [ ] **Step 2: Add profile to `SearchTask`**

Update the dataclass:

```python
@dataclass(frozen=True)
class SearchTask:
    source_name: str
    source_class: type[ComicSource]
    profile: SourceProfile
    search_func: Callable[[str], list]
    uses_driver: bool
    display_name: str
```

- [ ] **Step 3: Discover source bindings in `Shell.__init__()`**

Replace source map setup with binding-aware maps:

```python
self.all_source_bindings = self._discover_source_bindings(include_deprecated=True)
self.source_bindings = self._discover_source_bindings()
self.all_source_map = {
    source_name: binding.source_class
    for source_name, binding in self.all_source_bindings.items()
}
self.source_map = {
    source_name: binding.source_class
    for source_name, binding in self.source_bindings.items()
}
self.source_options = list(self.source_bindings.keys())
```

Add:

```python
def _discover_source_bindings(self, include_deprecated: bool = False):
    try:
        return load_source_bindings(
            include_deprecated=include_deprecated,
            runtime_config=self.runtime_config,
        )
    except Exception as e:
        self.console.print(f'Failed to load comic sources: {e}', style='bold red')
        return {}
```

Leave `_discover_sources()` only if tests or compatibility paths still call it.

- [ ] **Step 4: Use profile base URL for URL matching**

Update `_match_source_for_url()`:

```python
def _match_source_for_url(self, url: str) -> str | None:
    for source_name, binding in self.all_source_bindings.items():
        base_url = binding.profile.base_url
        if base_url and url.startswith(base_url):
            return source_name
    return None
```

- [ ] **Step 5: Pass profile when constructing sources**

Update `__switch_source()`:

```python
binding = self.source_bindings.get(source_name) or self.all_source_bindings[source_name]
source_class = binding.source_class
self.sources[source_name] = source_class(
    self.context.output_path,
    self.context.http,
    self.context.get_driver(binding.profile),
    overwrite=self.overwrite,
    profile=binding.profile,
)
```

Update `_build_search_func()` to accept a binding:

```python
def _build_search_func(
    self, binding: SourceBinding, uses_driver: bool
) -> Callable[[str], list]:
    def _search(keyword: str) -> list:
        driver = None
        if uses_driver:
            if not self.context.ensure_driver(binding.profile):
                raise RuntimeError('Browser driver was not initialized')
            driver = self.context.driver
        http = self.context.create_http_session()
        source = binding.source_class(
            self.context.output_path,
            http,
            driver,
            overwrite=self.overwrite,
            profile=binding.profile,
        )
        return source.search(keyword)

    return _search
```

Update `_build_search_tasks()`:

```python
for source_name in self.source_options:
    binding = self.source_bindings[source_name]
    uses_driver = binding.profile.uses_driver_for_search()
    tasks.append(
        SearchTask(
            source_name=source_name,
            source_class=binding.source_class,
            profile=binding.profile,
            search_func=self._build_search_func(binding, uses_driver),
            uses_driver=uses_driver,
            display_name=getattr(binding.source_class, 'name', source_name),
        )
    )
```

When pre-creating `self.sources[source_name]`, pass `profile=binding.profile`.

- [ ] **Step 6: Make `Context` driver decisions profile-aware**

Update type hints for `ensure_driver()`, `get_driver()`, `init_driver()`, `_driver_cache_key()`, `_driver_mode_for_source()`, `_source_browser_headless()`, `_source_browser_wait_seconds()`, `_source_cloakbrowser_humanize()`, and `_source_cloakbrowser_options()` to accept `SourceProfile`.

Add this helper inside `Context`:

```python
def _profile_for_source(
    self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None
) -> SourceProfile | None:
    if isinstance(source_or_class, SourceProfile):
        return source_or_class
    profile = getattr(source_or_class, 'profile', None)
    return profile if isinstance(profile, SourceProfile) else None
```

Update `_driver_mode_for_source()`:

```python
profile = self._profile_for_source(source_or_class)
if profile is not None:
    browser_mode = profile.browser_mode
elif isinstance(source_or_class, type) and issubclass(source_or_class, ComicSource):
    browser_mode = source_or_class.configured_browser_mode()
elif isinstance(source_or_class, ComicSource):
    browser_mode = source_or_class._source_browser_mode()
else:
    browser_mode = normalize_browser_mode(None)
```

Update `_source_browser_headless()`:

```python
profile = self._profile_for_source(source_or_class)
if profile is not None:
    if profile.browser_headless is not None:
        return bool(profile.browser_headless)
    if profile.seleniumbase_headless is not None:
        return bool(profile.seleniumbase_headless)
    return True
```

Update `_source_browser_wait_seconds()`:

```python
profile = self._profile_for_source(source_or_class)
if profile is not None:
    wait_seconds = profile.browser_wait_seconds
    if wait_seconds is None:
        wait_seconds = profile.seleniumbase_wait_seconds
    return float(30.0 if wait_seconds is None else wait_seconds)
```

Update CloakBrowser helpers similarly:

```python
profile = self._profile_for_source(source_or_class)
if profile is not None:
    return bool(profile.cloakbrowser_humanize)
```

and:

```python
profile = self._profile_for_source(source_or_class)
if profile is not None:
    options = profile.cloakbrowser_options
    return dict(options) if isinstance(options, dict) else None
```

- [ ] **Step 7: Add shell/driver lifecycle regression tests**

In `tests/test_shell_driver_lifecycle.py`, import profile pieces:

```python
from downloader.runtime_config import RuntimeConfig, SourceRuntimeConfig
from downloader.source_profiles import SourceProfile
```

Add:

```python
def test_context_driver_mode_uses_profile_browser_mode(tmp_path):
    profile = SourceProfile(
        source_name='profiled',
        class_name='ProfiledSource',
        enabled=True,
        deprecated=False,
        browser_mode='cloakbrowser',
        browser_headless=False,
    )
    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context._driver_cache_key(profile) == ('cloakbrowser', False)
```

Add a shell construction test using a runtime override:

```python
def test_shell_source_instances_receive_profiles(tmp_path):
    runtime_config = RuntimeConfig(
        sources={'morui': SourceRuntimeConfig(browser_mode='requests')}
    )
    shell = Shell(str(tmp_path), runtime_config=runtime_config)
    try:
        shell._Shell__switch_source('morui')
        source = shell.sources['morui']

        assert source.profile is not None
        assert source.profile.browser_mode == 'requests'
        assert source.browser_mode == 'requests'
    finally:
        shell.context.destroy()
```

- [ ] **Step 8: Verify shell tests**

Run:

```powershell
rtk uv run pytest tests/test_shell_driver_lifecycle.py tests/test_sources.py -q
```

Expected: shell and source discovery tests pass.

### Task 5: Prefer Profiles In Page Loading And Image Downloads

**Files:**
- Modify: `downloader/html_parser.py`
- Modify: `downloader/image_downloader.py`
- Modify: `tests/test_seleniumbase_html.py`

- [ ] **Step 1: Add profile value helpers to `HtmlParsingMixin`**

In `downloader/html_parser.py`, add these methods near `_source_browser_mode()`:

```python
def _source_profile_value(self, key: str, default: Any = None) -> Any:
    profile = getattr(self, 'profile', None)
    if profile is not None:
        return getattr(profile, key)
    return getattr(self, key, default)


def _source_base_url(self) -> str:
    return str(self._source_profile_value('base_url', ''))
```

Update browser helpers:

```python
def _source_browser_mode(self) -> BrowserModeName:
    return normalize_browser_mode(self._source_profile_value('browser_mode', REQUESTS_MODE))


def _browser_wait_selector(self) -> str | None:
    return self._source_profile_value(
        'browser_wait_selector', None
    ) or self._source_profile_value('seleniumbase_wait_selector', None)


def _browser_wait_seconds(self) -> float:
    wait_seconds = self._source_profile_value('browser_wait_seconds', None)
    if wait_seconds is None:
        wait_seconds = self._source_profile_value('seleniumbase_wait_seconds', 0)
    return float(wait_seconds or 0)


def _browser_headless(self, default: bool = True) -> bool:
    browser_headless = self._source_profile_value('browser_headless', None)
    if browser_headless is not None:
        return bool(browser_headless)
    seleniumbase_headless = self._source_profile_value('seleniumbase_headless', None)
    if seleniumbase_headless is not None:
        return bool(seleniumbase_headless)
    return default
```

Update page load request construction:

```python
request = PageLoadRequest(
    url=url,
    base_url=self._source_base_url(),
    browser_mode=options.browser_mode,
    ...
)
```

Update request fallback helper:

```python
def _switch_requests_html_to_seleniumbase(self, url, method, status_code: int):
    logger.warning(
        'Requests mode returned HTTP {}; retrying with temporary SeleniumBase mode: {}',
        status_code,
        url,
    )
    return self._parse_html_with_seleniumbase(url, method)
```

Do not assign `self.browser_mode = SELENIUMBASE_MODE`.

- [ ] **Step 2: Add profile value helpers to `ImageDownloadMixin`**

In `downloader/image_downloader.py`, add:

```python
def _source_profile_value(self, key: str, default=None):
    profile = getattr(self, 'profile', None)
    if profile is not None:
        return getattr(profile, key)
    return getattr(self, key, default)


def _source_base_url(self) -> str:
    return str(self._source_profile_value('base_url', ''))


def _source_base_img_url(self) -> str:
    return str(self._source_profile_value('base_img_url', ''))


def _source_max_download_workers(self) -> int:
    return max(1, int(self._source_profile_value('max_download_workers', 5) or 5))
```

Update download logic:

```python
context = ImageDownloadContext(
    path=path,
    use_base_img_url=bool(self._source_base_img_url()),
    session_factory=self._create_image_http_session,
)
```

Use `_source_max_download_workers()` in `_run_image_downloads()` and `_create_image_http_session()`.

Update `_download_image()`:

```python
retry_count = int(self._source_profile_value('image_retry_count', 1) or 1)
```

Update `_build_image_url()`:

```python
if use_base_img_url and not img_url_part.startswith('http'):
    return urljoin(self._source_base_img_url().rstrip('/') + '/', img_url_part)
```

Update `_request_image()` and browser download:

```python
headers = {'referer': self._source_base_url()}
...
download_to_file(full_img_url, tmp_path, referer=self._source_base_url())
```

Update `_image_request_interval_seconds()`:

```python
configured = self._source_profile_value('image_request_interval', None)
if configured is None:
    configured = self._source_profile_value('download_interval', 0)
return float(configured or 0)
```

- [ ] **Step 3: Add page loading/download profile regression coverage**

In `tests/test_seleniumbase_html.py`, import `SourceProfile`:

```python
from downloader.source_profiles import SourceProfile
```

Add this new test after the existing requests-to-SeleniumBase fallback test:

```python
def test_profiled_parse_html_uses_profile_base_url_and_keeps_fallback_non_sticky(
    monkeypatch, tmp_path
):
    fake_sb = FakeSB('<html><body><main class="page-main"><h1>Fallback</h1></main></body></html>')
    contexts = []

    def fake_context(self):
        context = FakeSBContext(fake_sb)
        contexts.append(context)
        return context

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)

    http = StatusHttp(403)
    profile = SourceProfile(
        source_name='browser-html',
        class_name='BrowserHtmlSource',
        enabled=True,
        deprecated=False,
        base_url='https://profile.example',
        browser_mode=REQUESTS_MODE,
        browser_wait_selector='.page-main',
        browser_wait_seconds=5.0,
    )
    source = BrowserHtmlSource(str(tmp_path), cast(Any, http), None, profile=profile)

    root = source.__parse_html__('https://example.test/search')

    assert http.get_calls == [
        (
            'https://example.test/search',
            {'timeout': 30, 'headers': {'referer': 'https://profile.example'}},
        )
    ]
    assert source.profile is profile
    assert source.profile.browser_mode == REQUESTS_MODE
    assert source.browser_mode == REQUESTS_MODE
    assert source.last_page_load_result.browser_mode == SELENIUMBASE_MODE
    assert fake_sb.cdp.find_calls == [('.page-main', 5.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Fallback'
```

- [ ] **Step 4: Verify page loading and image tests**

Run:

```powershell
rtk uv run pytest tests/test_seleniumbase_html.py tests/test_download_resume.py -q
```

Expected: page loading fallback remains non-sticky and image download behavior remains compatible.

### Task 6: Update Documentation And Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/basic-usage.md`

- [ ] **Step 1: Update runtime config wording**

In `README.md`, update the runtime config section around the `--config` table to state these exact facts in the document's existing Chinese prose style:

- `configs/runtime.sample.json` remains the runtime config example.
- `sources.<source>.enabled` overrides the default enabled state from `downloader/sources.py`.
- `sources.<source>.browser_mode` is resolved into that source's `SourceProfile`.
- Runtime `browser_mode` has higher precedence than site JSON `browser_mode`.
- Runtime `browser_mode` no longer mutates the source class itself.

In `docs/basic-usage.md`, mirror the same explanation near the runtime config example.

- [ ] **Step 2: Run targeted verification**

Run:

```powershell
rtk uv run pytest tests/test_source_profiles.py tests/test_sources.py tests/test_shell_driver_lifecycle.py tests/test_seleniumbase_html.py tests/test_download_resume.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
rtk uv run pytest -q
```

Expected: full test suite passes.

- [ ] **Step 4: Run static checks if available**

Run:

```powershell
rtk uv run ruff check downloader tests
rtk uv run pyright
```

Expected: no new lint/type errors. If existing unrelated failures appear, record them separately and do not expand this refactor to fix unrelated issues.

- [ ] **Step 5: Commit checkpoint when git metadata is writable**

Current sandbox writes project files but cannot write `.git/index.lock`. When git metadata is writable, commit the design and implementation together or as two commits:

```powershell
rtk git add docs/superpowers/specs/2026-06-05-source-profile-design.md docs/superpowers/plans/2026-06-05-source-profile.md downloader tests README.md docs/basic-usage.md
rtk git commit -m "refactor: resolve source configuration through profiles"
```

Expected: commit succeeds only in an environment with write access to `.git`.

## Self-Review

- Spec coverage: The plan covers the approved first phase: profile model, resolver, source discovery, `ComicSource` integration, shell/driver lifecycle, page loading/download consumers, docs, and verification.
- No TDD conflict: The plan explicitly avoids red-green-refactor and uses regression tests during implementation.
- Parser-specific config: `raw_site_config` and `self.config` remain available; parser JSON keys are not moved into profile fields.
- Runtime class mutation: `_apply_runtime_source_config()` is removed, and runtime browser mode assertions move to `SourceProfile`.
- Compatibility: `load_source_classes()` remains, but runtime-config-aware shell behavior moves to `load_source_bindings()`.
