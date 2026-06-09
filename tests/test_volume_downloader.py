from __future__ import annotations

import os
from typing import Any, cast

from downloader import comic as comic_module
from downloader.comic import ComicSource
from downloader.download.volume import download_volume
from downloader.models import VolumeDownloadResult


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
