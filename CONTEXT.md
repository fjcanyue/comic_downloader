# Comic Downloader Context

This context names the project-specific concepts used to search, parse, and download comics across multiple source websites.

## Language

**Comic source**:
A supported website adapter that can search comics, read comic details, and expose chapter image URLs.
_Avoid_: Site service, provider component

**Page loading**:
The project concept for obtaining a parseable source page, whether by HTTP requests or a browser-backed mode. Normal fetch, render, and fallback failures are represented as structured non-raising results. It consumes already-created adapters and does not own browser adapter creation or lifecycle. It owns diagnostics file writing, using a diagnostics directory supplied by the outer runtime. It owns only the wait strategy needed for a page to reach a parseable state; lazy image discovery such as scroll waits stays with source parsing.
_Avoid_: HTML helper, fetch wrapper

**Source profile**:
The resolved fact set for a comic source, including enablement, browser mode, waits, intervals, and runtime overrides.
_Avoid_: Config blob, settings bag

**Browser mode**:
The source page loading strategy selected for a comic source, currently requests, SeleniumBase, or CloakBrowser.
_Avoid_: Driver type, render option

**Block fallback**:
The fallback from requests page loading to browser-backed page loading when a source page returns a block status such as 403 or 429. By default it applies only to GET page loading requests, only to the current attempt, and targets SeleniumBase. Sticky fallback, non-GET fallback, alternate browser targets, and disabled fallback are explicit source profile policies. If the required browser adapter is unavailable, page loading returns a recoverable failure so the outer runtime can create the adapter and retry.
_Avoid_: Retry hack, anti-block workaround
