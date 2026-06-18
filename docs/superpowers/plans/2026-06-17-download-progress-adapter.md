# Download Progress Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a download progress adapter so download orchestration no longer directly depends on Rich `Progress` or bare `print()`.

**Architecture:** `downloader.download.progress` owns the progress interface and adapters. `ComicSource`, `download_volume()`, and `ImageDownloadMixin` use that interface while keeping existing download behaviour unchanged.

**Tech Stack:** Python 3.10, Rich, pytest, Ruff.

---

## File Structure

- Create `downloader/download/progress.py`: `DownloadProgress`, `NoopDownloadProgress`, `RichDownloadProgress`, and `ensure_download_progress`.
- Modify `downloader/comic.py`: replace direct Rich `Progress` creation with `create_download_progress()`.
- Modify `downloader/download/volume.py`: replace direct Rich/print handling with progress adapter.
- Modify `downloader/download/images.py`: replace direct Rich task calls with progress adapter.
- Add `tests/test_download_progress.py`: focused progress adapter tests.
- Modify `tests/test_volume_downloader.py`: assert no bare print and progress adapter events.

## Task 1: Progress Adapter Module

**Files:**
- Create: `downloader/download/progress.py`
- Test: `tests/test_download_progress.py`

- [x] **Step 1: Write failing progress adapter tests**

Create tests for `NoopDownloadProgress`, `ensure_download_progress(None)`, and `RichDownloadProgress` delegation to a fake Rich-like object.

- [x] **Step 2: Run tests to verify they fail**

Run: `rtk uv run pytest tests/test_download_progress.py -q`

Expected: FAIL because `downloader.download.progress` does not exist.

- [x] **Step 3: Implement progress adapters**

Implement `DownloadProgress`, `NoopDownloadProgress`, `RichDownloadProgress`, and `ensure_download_progress`.

- [x] **Step 4: Run tests to verify they pass**

Run: `rtk uv run pytest tests/test_download_progress.py -q`

Expected: PASS.

## Task 2: Volume Pipeline Progress Events

**Files:**
- Modify: `downloader/download/volume.py`
- Modify: `tests/test_volume_downloader.py`

- [x] **Step 1: Write failing volume progress tests**

Add tests that patch `builtins.print` to fail when `download_volume(..., progress=None)` is called, and add a recording progress adapter to assert parse task add/remove events.

- [x] **Step 2: Run focused test to verify failure**

Run: `rtk uv run pytest tests/test_volume_downloader.py -q`

Expected: FAIL because `download_volume()` still calls `print()` when no progress is supplied.

- [x] **Step 3: Update `download_volume()`**

Normalize `parent_progress` through `ensure_download_progress()`, create parse tasks through adapter, pass adapter to image download, and remove the bare `print()`.

- [x] **Step 4: Run tests to verify pass**

Run: `rtk uv run pytest tests/test_volume_downloader.py tests/test_download_progress.py -q`

Expected: PASS.

## Task 3: ComicSource And Image Download Integration

**Files:**
- Modify: `downloader/comic.py`
- Modify: `downloader/download/images.py`
- Test: existing download tests and any focused additions needed in `tests/test_volume_downloader.py`

- [x] **Step 1: Write failing integration test**

Add a test source whose `create_download_progress()` returns a recording adapter, then call `download_vols()` and assert book task add/advance events happen through that adapter.

- [x] **Step 2: Run focused test to verify failure**

Run: `rtk uv run pytest tests/test_volume_downloader.py::test_comic_source_download_vols_uses_download_progress_adapter -q`

Expected: FAIL because `ComicSource.download_vols()` creates Rich `Progress` directly.

- [x] **Step 3: Update integration code**

Add `ComicSource.create_download_progress()`. Update `download_full()` and `download_vols()` to use it. Update `__download_vol__()` and `ImageDownloadMixin._run_image_downloads()` to operate on progress adapters.

- [x] **Step 4: Run focused integration tests**

Run: `rtk uv run pytest tests/test_volume_downloader.py tests/test_download_resume.py tests/test_seleniumbase_html.py -q`

Expected: PASS.

## Task 4: Verification

**Files:**
- Existing project files only.

- [x] **Step 1: Run focused download tests**

Run: `rtk uv run pytest tests/test_download_progress.py tests/test_volume_downloader.py tests/test_download_resume.py tests/test_seleniumbase_html.py -q`

Expected: PASS.

- [x] **Step 2: Run full test suite**

Run: `rtk uv run pytest -q`

Expected: PASS.

- [x] **Step 3: Run lint**

Run: `rtk uv run ruff check downloader tests main.py`

Expected: PASS.

## Self-Review

Spec coverage: The plan creates the progress adapter seam, removes bare print from `download_volume()`, routes `ComicSource` and image downloads through the adapter, and preserves existing behaviour.

Placeholder scan: No placeholder steps remain.

Type consistency: `DownloadProgress`, `NoopDownloadProgress`, `RichDownloadProgress`, `ensure_download_progress`, and `create_download_progress()` are used consistently.
