from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest

from downloader import comic as comic_module
from downloader.comic import ComicSource, ImageDownloadCancelledError, ImageDownloadContext


class NoNetworkHttp:
    headers: ClassVar[dict[str, str]] = {}

    def get(self, *args, **kwargs):
        raise AssertionError('existing image should be reused without a network request')


class ClosableNoNetworkHttp(NoNetworkHttp):
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class ResumeSource(ComicSource):
    name = 'resume-source'
    base_url = 'https://example.test'
    max_download_workers = 4

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_existing_images_are_reused_when_overwrite_is_disabled(tmp_path):
    image_dir = tmp_path / 'chapter'
    image_dir.mkdir()
    existing_image = image_dir / '0001.jpg'
    existing_image.write_bytes(b'existing')

    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)

    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://example.test/0001.jpg'],
    )

    assert result.status == 'downloaded'
    assert result.downloaded_count == 1
    assert existing_image.read_bytes() == b'existing'
    assert result.archive_path is not None
    assert Path(result.archive_path).exists()


def test_keyboard_interrupt_cancels_running_image_download(monkeypatch, tmp_path):
    http = ClosableNoNetworkHttp()
    source = ResumeSource(str(tmp_path), cast(Any, http), None)
    source.max_download_workers = 1
    image_dir = tmp_path / 'chapter'
    entered_download = threading.Event()
    released_download = threading.Event()
    contexts: list[ImageDownloadContext] = []

    def blocking_download(context, index, img_url_part):
        contexts.append(context)
        entered_download.set()
        context.cancel_event.wait(5)
        released_download.set()
        raise ImageDownloadCancelledError('cancelled')

    def interrupting_as_completed(futures):
        assert entered_download.wait(1)
        raise KeyboardInterrupt

    monkeypatch.setattr(source, '_download_image', blocking_download)
    monkeypatch.setattr(comic_module.concurrent.futures, 'as_completed', interrupting_as_completed)

    with pytest.raises(KeyboardInterrupt):
        source.__download_vol_images__(
            str(image_dir),
            'chapter',
            'https://example.test/chapter',
            ['https://example.test/0001.jpg'],
        )

    assert contexts[0].cancel_event.is_set()
    assert released_download.wait(1)
    assert http.closed is True


def test_download_rate_wait_is_cancelled_promptly(tmp_path):
    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None)
    source.download_interval = 30
    context = ImageDownloadContext(path=str(tmp_path), use_base_img_url=False)
    context.last_request_at[0] = time.monotonic()
    entered_wait = threading.Event()
    exited_wait = threading.Event()

    def wait_for_slot():
        entered_wait.set()
        with pytest.raises(ImageDownloadCancelledError):
            source._wait_for_download_slot(context)
        exited_wait.set()

    worker = threading.Thread(target=wait_for_slot)
    worker.start()
    assert entered_wait.wait(1)

    context.cancel_event.set()
    worker.join(1)

    assert exited_wait.is_set()
    assert worker.is_alive() is False
