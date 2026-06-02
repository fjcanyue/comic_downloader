---
name: add-comic-source
description: Add a new comic/manga website source to the comic_downloader project. Use when the user asks to add a new comic site, manga source, or downloader for a specific website URL. Covers the full workflow from site exploration to implementation, testing, and registration.
---

# Add Comic Source

Add a new `ComicSource` subclass for a comic/manga website. The project lives in the repo root; sources go in `downloader/` with configs in `configs/`.

## Workflow

1. **Explore the target site** — determine URL patterns and page structure
2. **Choose browser mode** — `requests`, `seleniumbase`, or `cloakbrowser`
3. **Create config and source module** — JSON config + Python class
4. **Register the source** — add to `sources.py`
5. **Lint, format, and test** — ruff + live XPath validation + pytest

## Step 1: Explore the Target Site

Use `curl` (via Bash) and `WebFetch` to analyze three page types:

| Page | What to find |
|------|-------------|
| **Search results** | URL pattern (`/search?q={kw}` etc.), result container CSS class, name/URL extraction |
| **Manga detail** | Name selector (`<h1>`), metadata (author, status, genre), chapter list container and item structure |
| **Chapter/reader** | Image loading mechanism: `<img src>`, `<img data-original>`, JS variables (`chapterImages`, etc.) |

Fetch raw HTML with `curl -s -L -H "User-Agent: Mozilla/5.0 ..." "<url>"` to inspect script tags, CSS classes, and DOM structure that WebFetch may abstract away.

## Step 2: Choose Browser Mode

Decision tree based on site behavior:

- **`REQUESTS_MODE`** (default) — HTML is server-rendered, no JS needed. Fastest. Prefer this.
- **`SELENIUMBASE_MODE`** — Site returns 403/429 to plain requests, or images loaded via JS (e.g., `chapterImages` variable), or lazy-loaded with scroll.
- **`CLOAKBROWSER_MODE`** — Heavy anti-bot protection, Cloudflare challenges, requires full browser fingerprinting.

Set `browser_mode` on the class AND in the config JSON (config overrides class attribute via `_apply_source_config`).

For image parsing (`__parse_imgs__`), if images require JS execution, set `download_requires_driver = True` and use `self.driver.get(url)` + `self.execute_js_safely()`.

## Step 3: Create Config and Source Module

See [references/code-patterns.md](references/code-patterns.md) for templates:
- Config JSON template with XPath expressions
- Source module template with `search()`, `info()`, `__parse_imgs__()`
- `sources.py` registration entry

**Key conventions:**
- Class name: `{SiteName}Comic` (e.g., `TukuComic`)
- Module name: lowercase site name (e.g., `tuku.py`)
- Config file: `{module_name}.json`
- Import from `downloader.browser_modes` for mode constants
- Import from `downloader.comic` for `Comic`, `ComicBook`, `ComicVolume`, `ComicSource`, `logger`
- Use `self.parse_xpath_list(root, xpath, extract_map)` for config-driven list extraction
- Use `self.config['key']` to access XPath expressions from JSON
- Use `''.join(node.itertext())` instead of `node.text_content()` — `lxml.etree._Element` lacks `text_content()`
- URL assembly: handle relative paths with `self.base_url + href if href.startswith('/') else href`

## Step 4: Register the Source

Add a `SourceDefinition` entry to `SOURCE_DEFINITIONS` tuple in `downloader/sources.py`, **and** add `'downloader.{module_name}'` to the `hiddenimports` list in `downloader.spec` (required for PyInstaller to bundle the new source module).

## Step 5: Lint, Format, and Test

Run in project root using `uv run`:

```bash
# Lint and format
uv run python -m ruff check downloader/{module}.py
uv run python -m ruff format downloader/{module}.py

# Import check
uv run python -c "from downloader.sources import load_source_classes; c = load_source_classes(); print(list(c.keys()))"

# Live XPath validation (see references/code-patterns.md for full script)
uv run python -c "..." # test search, info, and image XPaths against live site

# Run existing tests
uv run python -m pytest tests/ -v
```
