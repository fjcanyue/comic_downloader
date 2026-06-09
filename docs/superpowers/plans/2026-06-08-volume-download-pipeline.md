# Volume Download Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move volume-level download orchestration into a focused module while keeping source-specific image parsing on `ComicSource` adapters.

**Architecture:** Add `downloader/volume_downloader.py` with a `download_volume(...)` function that coordinates archive skip, parse progress, source image discovery, image download, and `VolumeDownloadResult` mapping. `ComicSource.__download_vol__` remains as a compatibility wrapper and delegates to the new function; `ComicSource.parse_images(url)` delegates to the existing abstract `__parse_imgs__(url)` hook.

**Tech Stack:** Python 3.10, pytest, rich `Progress`, existing downloader models/mixins.

---

### Task 1: Add Failing Volume Pipeline Tests

**Files:**
- Create: `tests/test_volume_downloader.py`

- [ ] **Step 1: Add tests for the new pipeline boundary**

```python
from __future__ import annotations

import os
from typing import Any, cast

from downloader import comic as comic_module
from downloader.comic import ComicSource
from downloader.models import VolumeDownloadResult
from downloader.volume_downloader import download_volume


class PipelineSource:
    def __init__(self) -> None:
        self.existing_archive: str | None = None
        self.images: list[str] = []
        self.parse_error: Exception | None = None
        self.parse_calls: list[str] = []
        self.download_calls: list[tuple[str, str, str, list[str], Any]] = []
        self.download_result = VolumeDownloadResult(
            name='chapter',
            url='https://example.test/chapter',
            status='downloaded',
            image_count=2,
            downloaded_count=2,
            archive_path='chapter.zip',
        )

    def _find_existing_archive(self, path: str, vol_name: str) -> str | None:
        return self.existing_archive

    def _remove_progress_task(self, progress, task_id) -> None:
        if progress is not None and task_id is not None:
            progress.remove_task(task_id)

    def parse_images(self, url: str) -> list[str]:
        self.parse_calls.append(url)
        if self.parse_error is not None:
            raise self.parse_error
        return self.images

    def __download_vol_images__(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        imgs: list[str],
        progress=None,
    ) -> VolumeDownloadResult:
        self.download_calls.append((path, vol_name, source_url, imgs, progress))
        return self.download_result


def test_existing_archive_skips_parse_and_download(tmp_path):
    source = PipelineSource()
    source.existing_archive = str(tmp_path / 'chapter.zip')

    result = download_volume(
        source,
        str(tmp_path),
        'chapter',
        'https://example.test/chapter',
    )

    assert result.status == 'skipped'
    assert result.archive_path == source.existing_archive
    assert result.message == '文件已存在'
    assert source.parse_calls == []
    assert source.download_calls == []


def test_empty_image_parse_returns_failed_result(tmp_path):
    source = PipelineSource()

    result = download_volume(
        source,
        str(tmp_path),
        'chapter',
        'https://example.test/chapter',
    )

    assert result.status == 'failed'
    assert result.name == 'chapter'
    assert result.url == 'https://example.test/chapter'
    assert result.message == '未解析到任何图片'
    assert source.parse_calls == ['https://example.test/chapter']
    assert source.download_calls == []


def test_parse_exception_returns_failed_result(tmp_path):
    source = PipelineSource()
    source.parse_error = RuntimeError('parse exploded')

    result = download_volume(
        source,
        str(tmp_path),
        'chapter',
        'https://example.test/chapter',
    )

    assert result.status == 'failed'
    assert result.name == 'chapter'
    assert result.url == 'https://example.test/chapter'
    assert result.message == 'parse exploded'
    assert source.download_calls == []


def test_successful_parse_delegates_to_image_download(tmp_path):
    source = PipelineSource()
    source.images = ['0001.jpg', '0002.jpg']

    result = download_volume(
        source,
        str(tmp_path),
        'chapter',
        'https://example.test/chapter',
    )

    assert result is source.download_result
    assert source.download_calls == [
        (
            os.path.join(str(tmp_path), 'chapter'),
            'chapter',
            'https://example.test/chapter',
            ['0001.jpg', '0002.jpg'],
            None,
        )
    ]


class ParseDelegatingSource(ComicSource):
    name = 'parse-delegating-source'

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.parse_urls: list[str] = []

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        self.parse_urls.append(url)
        return ['0001.jpg']


def test_comic_source_parse_images_keeps_legacy_parse_hook(tmp_path):
    source = ParseDelegatingSource(str(tmp_path), cast(Any, object()), None)

    assert source.parse_images('https://example.test/chapter') == ['0001.jpg']
    assert source.parse_urls == ['https://example.test/chapter']


def test_comic_source_download_vol_delegates_to_volume_pipeline(monkeypatch, tmp_path):
    source = ParseDelegatingSource(str(tmp_path), cast(Any, object()), None)
    expected = VolumeDownloadResult(
        name='chapter',
        url='https://example.test/chapter',
        status='downloaded',
    )
    calls = []

    def fake_download_volume(source_arg, path, vol_name, url, parent_progress=None):
        calls.append((source_arg, path, vol_name, url, parent_progress))
        return expected

    monkeypatch.setattr(comic_module, 'download_volume', fake_download_volume)

    result = source.__download_vol__(
        str(tmp_path),
        'chapter',
        'https://example.test/chapter',
    )

    assert result is expected
    assert calls == [
        (
            source,
            str(tmp_path),
            'chapter',
            'https://example.test/chapter',
            None,
        )
    ]
```

- [ ] **Step 2: Run tests and verify they fail because the module/method does not exist**

Run: `rtk uv run pytest tests/test_volume_downloader.py -q`

Expected: FAIL during import with `ModuleNotFoundError: No module named 'downloader.volume_downloader'`.

### Task 2: Add the Volume Pipeline Module

**Files:**
- Create: `downloader/volume_downloader.py`

- [ ] **Step 1: Implement the consolidated volume function**

```python
from __future__ import annotations

import os
from typing import Any

from loguru import logger
from rich.progress import Progress

from downloader.models import VolumeDownloadResult, filter_dir_name


def download_volume(
    source: Any,
    path: str,
    vol_name: str,
    url: str,
    parent_progress: Progress | None = None,
) -> VolumeDownloadResult:
    logger.info('开始下载卷/话: {} 从 {}', vol_name, url)

    existing_archive_path = source._find_existing_archive(path, vol_name)
    if existing_archive_path:
        logger.info('文件已存在，跳过: {}', existing_archive_path)
        return VolumeDownloadResult(
            name=vol_name,
            url=url,
            status='skipped',
            archive_path=existing_archive_path,
            message='文件已存在',
        )

    parse_task_id = None
    if parent_progress:
        parse_task_id = parent_progress.add_task(
            description=f'[yellow]正在解析 {vol_name} 图片...',
            total=None,
        )
    else:
        print(f'正在解析 {vol_name} 图片...')

    try:
        imgs = source.parse_images(url)
        source._remove_progress_task(parent_progress, parse_task_id)
        parse_task_id = None

        if not imgs:
            logger.warning('未解析到任何图片: {} ({})', vol_name, url)
            return VolumeDownloadResult(
                name=vol_name,
                url=url,
                status='failed',
                message='未解析到任何图片',
            )

        target_path = os.path.join(path, filter_dir_name(vol_name))
        result = source.__download_vol_images__(
            target_path,
            vol_name,
            url,
            imgs,
            parent_progress,
        )
        if result.ok:
            logger.info('卷/话 {} 下载完成.', vol_name)
        else:
            logger.warning(
                '卷/话 {} 下载未完全成功: 状态={}, 成功图片={}/{}',
                vol_name,
                result.status,
                result.downloaded_count,
                result.image_count,
            )
        return result
    except Exception as e:
        source._remove_progress_task(parent_progress, parse_task_id)
        logger.error('处理卷/话失败: {} ({}), 错误: {}', vol_name, url, e, exc_info=True)
        return VolumeDownloadResult(name=vol_name, url=url, status='failed', message=str(e))
```

- [ ] **Step 2: Run the new tests**

Run: `rtk uv run pytest tests/test_volume_downloader.py -q`

Expected: FAIL because `ComicSource.parse_images` and the `download_volume` import in `downloader.comic` are not wired yet.

### Task 3: Wire ComicSource To The Pipeline

**Files:**
- Modify: `downloader/comic.py`

- [ ] **Step 1: Import the new pipeline function**

Add this import near the existing downloader imports:

```python
from downloader.volume_downloader import download_volume
```

- [ ] **Step 2: Add the stable source image-discovery method**

Add this method directly below `__parse_imgs__`:

```python
    def parse_images(self, url: str) -> list[str]:
        return self.__parse_imgs__(url)
```

- [ ] **Step 3: Replace `ComicSource.__download_vol__` body with delegation**

```python
    def __download_vol__(
        self, path: str, vol_name: str, url: str, parent_progress: Progress | None = None
    ) -> VolumeDownloadResult:
        """下载动漫卷/话

        Args:
            path: 下载路径
            vol_name: 动漫卷/话名称
            url: 动漫卷/话URL地址
            parent_progress: 父级进度条对象，用于嵌套显示图片下载进度
        """
        return download_volume(self, path, vol_name, url, parent_progress)
```

- [ ] **Step 4: Run the new tests**

Run: `rtk uv run pytest tests/test_volume_downloader.py -q`

Expected: PASS.

### Task 4: Run Focused Regression Tests

**Files:**
- Test only.

- [ ] **Step 1: Run volume and image download regression tests**

Run: `rtk uv run pytest tests/test_volume_downloader.py tests/test_download_resume.py tests/test_seleniumbase_html.py -q`

Expected: PASS. If SeleniumBase-dependent tests are skipped or fail due local browser availability, record the exact result.

- [ ] **Step 2: Run the broader source/browser lifecycle regression set**

Run: `rtk uv run pytest tests/test_volume_downloader.py tests/test_source_profiles.py tests/test_sources.py tests/test_shell_driver_lifecycle.py tests/test_page_loading.py -q`

Expected: PASS.

- [ ] **Step 3: Format and lint changed files**

Run: `rtk uv run ruff format downloader/volume_downloader.py downloader/comic.py tests/test_volume_downloader.py`

Expected: changed files are formatted.

Run: `rtk uv run ruff check downloader/volume_downloader.py downloader/comic.py tests/test_volume_downloader.py`

Expected: PASS.

- [ ] **Step 4: Commit if repository metadata is writable**

Run: `rtk git add downloader/volume_downloader.py downloader/comic.py tests/test_volume_downloader.py docs/superpowers/specs/2026-06-08-volume-download-pipeline-design.md docs/superpowers/plans/2026-06-08-volume-download-pipeline.md`

Run: `rtk git commit -m "refactor: consolidate volume download pipeline"`

Expected in a normal checkout: commit succeeds. Expected in the current sandbox: commit is blocked because `.git/index.lock` cannot be created with the active permissions.

---

## Self-Review

- Spec coverage: The plan covers the approved narrow consolidation, preserves source parsing, leaves worker/archive internals intact, and adds tests for the new boundary.
- Placeholder scan: No deferred implementation placeholders are present.
- Type consistency: The plan consistently uses `download_volume`, `parse_images`, `__parse_imgs__`, `__download_vol__`, and `VolumeDownloadResult`.
