# Volume Download Pipeline Consolidation Design

## Goal

Consolidate the chapter/volume download execution path without changing source adapter responsibilities.

## Scope

This change only moves volume-level orchestration out of `ComicSource.__download_vol__`.
It does not rewrite image workers, HTTP session handling, retry behavior, cancellation behavior,
archive finalization, or site-specific image discovery.

## Current State

`ComicSource.__download_vol__` currently coordinates existing archive checks, image parsing,
parse progress UI, empty parse result handling, image download invocation, success/failure logging,
and exception-to-`VolumeDownloadResult` mapping.

Image worker scheduling and cancellation live in `ImageDownloadMixin`. Archive detection,
partial result calculation, and zip finalization live in `ArchiveMixin`.

The result is a real cross-module download path, but the most risky boundary is site image
discovery. `__parse_imgs__` is the source adapter extension point and should stay source-owned.

## Design

Add a small volume pipeline module that owns volume execution orchestration:

- check whether the target archive already exists;
- show and remove the parse progress task;
- call the source adapter through a narrow `parse_images(url)` method;
- map empty parse results and unexpected exceptions to `VolumeDownloadResult`;
- invoke the existing image download/finalize path;
- keep logging behavior equivalent to the current `ComicSource.__download_vol__`.

`ComicSource` keeps the abstract `__parse_imgs__(url)` hook for existing source classes and adds
`parse_images(url)` as the stable adapter-facing method used by the volume pipeline. This keeps
site-specific image discovery on source implementations while giving the generic pipeline a clear
interface.

`ImageDownloadMixin.__download_vol_images__`, `_run_image_downloads`, `_download_image`, and
`ArchiveMixin` remain behaviorally unchanged in this phase. They are reused by the new pipeline
through the existing source instance methods.

## Compatibility

Existing source classes do not need to change. Existing callers of `ComicSource.__download_vol__`
continue to work because that method delegates to the new pipeline.

Tests may keep using `__download_vol_images__` for image-worker behavior. New tests should target
the volume pipeline boundary rather than worker internals.

## Test Coverage

Add focused tests for the consolidated boundary:

- an existing archive skips parsing and image download;
- an empty image parse result returns a failed `VolumeDownloadResult`;
- a parsing exception returns a failed `VolumeDownloadResult`;
- a successful parse delegates to image download and preserves the returned result;
- `ComicSource.__download_vol__` delegates through the new volume pipeline.

Existing resume, cancellation, SeleniumBase image download, and archive tests remain the regression
signal for the reused lower-level behavior.
