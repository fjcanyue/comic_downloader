# Download Progress Adapter Design

## Goal

Extract download progress presentation from the download pipeline so the core
orchestration emits progress operations through a small adapter instead of
directly depending on Rich `Progress` or bare `print()`.

## Scope

This iteration only introduces the progress seam. It does not change:

- image download concurrency;
- retry behavior;
- resume behavior;
- archive creation;
- failed or partial download accounting;
- source parsing behavior;
- shell command semantics.

## Current State

`ComicSource.download_full()` and `ComicSource.download_vols()` directly create
Rich `Progress` instances. `download_volume()` calls `print()` when no parent
progress object is supplied. `ImageDownloadMixin._run_image_downloads()` also
operates on Rich task methods directly.

That exposes presentation details to the download pipeline. Tests and future TUI
work have to know about `Progress.add_task()`, `advance()`, `update()`, and
`remove_task()` even when the pipeline only needs a narrow download progress
interface.

## Design

Add `downloader/download/progress.py` with:

- `DownloadProgress`: a small protocol for the operations used by downloads.
- `NoopDownloadProgress`: a silent adapter for tests and no-output contexts.
- `RichDownloadProgress`: the current Rich progress bar adapter.
- `ensure_download_progress(progress=None)`: normalizes `None`, old Rich-like
  progress objects, and new adapters into the same interface.

`ComicSource.download_full()` and `ComicSource.download_vols()` obtain progress
through `self.create_download_progress()`, which returns `RichDownloadProgress`
by default.

`download_volume()` accepts the progress adapter. It no longer calls `print()`.
Its image parsing task is created and removed through the adapter.

`ImageDownloadMixin._run_image_downloads()` accepts the same adapter. Image task
creation, advancement, and removal all go through that interface.

For compatibility, `__download_vol__(..., parent_progress=None)` keeps the
existing parameter name. Existing callers can still pass a Rich-like object, and
new callers can pass a `DownloadProgress` adapter.

## Interface

The download pipeline depends on only these operations:

- `add_task(description, total=None) -> task_id`
- `advance(task_id, amount=1)`
- `update(task_id, description=None, total=None)`
- `remove_task(task_id)`
- context manager support with `with progress:`

This is not a general-purpose progress framework. It only covers the operations
the download pipeline currently uses.

## Tests

Focused tests cover:

- `NoopDownloadProgress` methods are safe and silent.
- `ensure_download_progress(None)` returns `NoopDownloadProgress`.
- `RichDownloadProgress` delegates to a Rich-like object.
- `download_volume()` no longer calls `print()` when no external progress is
  supplied.
- `download_volume()` uses a progress adapter for parse task add/remove events.
- `ComicSource.download_vols()` uses `create_download_progress()`.
- Existing volume pipeline, resume, and SeleniumBase image download tests still
  pass.

## Non-Goals

This iteration does not:

- redesign the visual layout of download progress;
- add JSON output;
- add a quiet CLI flag;
- remove the Rich dependency;
- change image worker scheduling;
- remove the old `parent_progress` parameter name.
