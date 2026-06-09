# Source Profile Design

## Goal

Introduce a read-only `SourceProfile` that represents the resolved source facts used by shell, driver lifecycle, page loading, and downloads. The first implementation phase removes runtime browser overrides from source class state while preserving existing source parser behavior.

## Current Problem

Source configuration is assembled across several places:

- `ComicSource` class attributes provide defaults for base URLs, browser mode, waits, scroll settings, intervals, SeleniumBase options, and CloakBrowser options.
- `configs/*.json` files can override generic source attributes and also contain parser-specific settings such as XPath, JavaScript snippets, API base URLs, and image host settings.
- `RuntimeConfig` supports enabled overrides and browser mode overrides.
- `sources.py` applies browser mode overrides by mutating `source_class._runtime_browser_mode_override`.
- `ComicSource.load_config()` applies JSON profile keys by mutating source instance attributes.
- `shell.py`, `html_parser.py`, and `image_downloader.py` read final behavior from a mix of source classes and source instances.

That makes the effective source configuration hard to inspect, and the class-state runtime override is weak for tests and concurrent sessions.

## Non-Goals

- Do not rewrite every site parser in the first phase.
- Do not move parser-specific JSON keys into `SourceProfile`.
- Do not remove `self.config`; template and site-specific parsers still read raw JSON parser configuration.
- Do not adopt a TDD red-green-refactor workflow for this change. Verification will use focused characterization/regression tests added alongside the refactor.

## SourceProfile

Add a frozen dataclass in the new module `downloader/source_profiles.py`.

`SourceProfile` should contain the resolved generic source facts:

- `source_name: str`
- `class_name: str`
- `enabled: bool`
- `deprecated: bool`
- `base_url: str`
- `base_img_url: str`
- `browser_mode: BrowserModeName`
- `download_interval: float`
- `image_request_interval: float | None`
- `page_load_wait_seconds: float | None`
- `scroll_wait_seconds: float | None`
- `max_scroll_attempts: int | None`
- `download_requires_driver: bool`
- `search_requires_driver: bool`
- `image_retry_count: int`
- `max_download_workers: int`
- `browser_wait_selector: str | None`
- `browser_wait_seconds: float | None`
- `browser_headless: bool | None`
- `seleniumbase_wait_selector: str | None`
- `seleniumbase_wait_seconds: float`
- `seleniumbase_headless: bool | None`
- `cloakbrowser_humanize: bool`
- `cloakbrowser_options: dict[str, Any] | None`
- `raw_site_config: Mapping[str, Any]`

`raw_site_config` is included for visibility and compatibility, but generic consumers should use explicit profile fields. Existing source parsers may continue using `self.config`.

## Resolver

Add a resolver that builds profiles from:

1. Static `SourceDefinition` registry values.
2. `ComicSource` class defaults.
3. Generic keys from the source JSON config file.
4. Runtime config overrides.
5. Optional session/CLI overrides reserved as an explicit argument for future use.

The effective merge order is:

`registry -> class defaults -> site JSON profile keys -> runtime config -> session override`

Only keys listed by `SOURCE_CONFIG_ATTRIBUTE_KEYS` should be copied from site JSON into profile fields. Other JSON keys remain in `raw_site_config` / `self.config` for parser logic.

Browser modes must be normalized through `normalize_browser_mode()` during resolution. The resolver must not mutate source classes.

## Compatibility Shape

Keep `load_source_classes()` available so existing shell and tests do not need a broad API rewrite in the same commit.

Add these explicit APIs:

- `load_source_profiles(include_deprecated=False, runtime_config=None, session_overrides=None) -> dict[str, SourceProfile]`
- `load_source_bindings(...) -> dict[str, SourceBinding]`

`SourceBinding` pairs `source_name`, `source_class`, and `profile` so shell has access to both class and profile without asking the class for runtime-mutated state.

## ComicSource Integration

Extend `ComicSource.__init__()` with an optional keyword-only profile parameter:

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

When a profile is supplied:

- Set `self.profile = profile`.
- Set `self.config` from `profile.raw_site_config`.
- Mirror profile fields onto legacy instance attributes for current parser compatibility.
- Do not call `load_config()` again.

When no profile is supplied:

- Preserve existing behavior for tests and direct source instantiation.
- Build a local default profile from class defaults and site JSON without runtime overrides, or continue legacy loading as a transitional path.

Class methods such as `configured_browser_mode()`, `uses_driver_for_search()`, and `uses_driver_for_download()` should use a class-default profile path only when no runtime profile is available. They must not depend on `_runtime_browser_mode_override`.

## Shell And Driver Lifecycle

Move shell discovery toward profile-aware bindings:

- The shell should discover enabled profiles using runtime config.
- URL matching should use `profile.base_url`.
- Source display names can still use `source_class.name`.
- Source construction should pass `profile=profile`.
- Driver mode, headless settings, wait seconds, CloakBrowser humanize, and CloakBrowser launch options should read profile values.
- Driver cache keys should include browser mode and headless state derived from profile, not class attributes mutated by runtime config.

This removes cross-session leakage where one runtime config changes class-level browser behavior for later loads.

## Page Loading And Downloads

For shared logic, prefer profile reads:

- `_source_browser_mode()` returns `self.profile.browser_mode` when present.
- Browser wait selector and seconds use `self.profile`.
- Page load request base URL uses `self.profile.base_url`.
- Image URL base and referer use `self.profile.base_img_url` and `self.profile.base_url`.
- Image retry count, max download workers, and interval helpers use `self.profile`.

The legacy mirrored attributes remain available so site parsers do not need an immediate sweep.

The existing requests-to-SeleniumBase block fallback should not mutate `self.browser_mode`. It should keep fallback mode local to the current page load request/result. This matches the `Block fallback` language in `CONTEXT.md`.

## Tests And Verification

Because the user explicitly requested not to use TDD, implementation should not follow a red-green-refactor workflow. It should still add focused regression tests:

- Runtime browser mode override resolves in `SourceProfile` and is passed to source instances.
- Loading profiles with one runtime config does not mutate source class state for another runtime config.
- Site JSON generic keys override class defaults in the resolved profile.
- Parser-specific JSON keys remain available in `source.config`.
- Shell driver cache mode/headless decisions use profile values.
- Requests block fallback does not mutate source browser mode.

Run targeted tests first, then the full suite:

```powershell
rtk uv run pytest tests/test_sources.py tests/test_shell_driver_lifecycle.py tests/test_seleniumbase_html.py -q
rtk uv run pytest -q
```

## Rollout

Implement this in one focused phase:

1. Add profile dataclasses and resolver.
2. Update source discovery to expose profiles without class mutation.
3. Update `ComicSource` construction to accept and mirror a profile.
4. Update shell and shared loader/download helpers to prefer profile reads.
5. Remove runtime override class mutation.
6. Update docs that describe runtime config overriding site JSON browser mode.

This phase should leave individual source parser internals mostly unchanged. A later phase can migrate source implementations away from legacy mirrored attributes when there is a clearer parser abstraction.
