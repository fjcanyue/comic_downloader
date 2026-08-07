from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, ClassVar, cast
from zipfile import ZipFile

import pytest

from downloader import comic as comic_module
from downloader.comic import ComicSource, ImageDownloadCancelledError, ImageDownloadContext
from downloader.download.tasks import DownloadTaskStore

VALID_JPEG = b'\xff\xd8\xff\xe0' + (b'\x00' * 12) + b'\xff\xd9'


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


class RecoverableSource(ResumeSource):
    def __parse_imgs__(self, url):
        return ['https://example.test/0001.jpg']


def test_existing_images_are_reused_when_overwrite_is_disabled(tmp_path):
    image_dir = tmp_path / 'chapter'
    image_dir.mkdir()
    existing_image = image_dir / '0001.jpg'
    existing_image.write_bytes(VALID_JPEG)

    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)

    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://example.test/0001.jpg'],
    )

    assert result.status == 'downloaded'
    assert result.downloaded_count == 1
    assert existing_image.read_bytes() == VALID_JPEG
    assert result.archive_path is not None
    assert Path(result.archive_path).exists()


class FakeImageResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.url = 'https://example.test/0001.jpg'

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self.content

    def close(self) -> None:
        return None


class FakeImageSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}

    def get(self, *args, **kwargs):
        return FakeImageResponse(self.content)

    def close(self) -> None:
        return None


def test_corrupt_existing_image_is_redownloaded_before_reuse(monkeypatch, tmp_path):
    image_dir = tmp_path / 'chapter'
    image_dir.mkdir()
    existing_image = image_dir / '0001.jpg'
    existing_image.write_bytes(b'<html>blocked</html>')
    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)
    monkeypatch.setattr(source, '_create_image_http_session', lambda: FakeImageSession(VALID_JPEG))

    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://example.test/0001.jpg'],
    )

    assert result.status == 'downloaded'
    assert existing_image.read_bytes() == VALID_JPEG


def test_html_response_is_rejected_as_failed_image(monkeypatch, tmp_path):
    image_dir = tmp_path / 'chapter'
    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)
    monkeypatch.setattr(
        source,
        '_create_image_http_session',
        lambda: FakeImageSession(b'<html>blocked</html>'),
    )

    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://example.test/0001.jpg'],
    )

    assert result.status == 'failed'
    assert result.failed_images
    assert '不是完整图片' in result.failed_images[0].error
    assert not (image_dir / '0001.jpg').exists()


def test_failed_volume_is_persisted_and_can_be_retried_after_restart(monkeypatch, tmp_path):
    first_source = RecoverableSource(
        str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False
    )
    monkeypatch.setattr(
        first_source,
        '_create_image_http_session',
        lambda: FakeImageSession(b'<html>blocked</html>'),
    )

    first_result = first_source.__download_vol__(
        str(tmp_path / 'comic' / 'book'),
        'chapter',
        'https://example.test/chapter',
    )

    assert first_result.status == 'failed'
    pending = DownloadTaskStore(tmp_path).list_pending()
    assert len(pending) == 1
    assert pending[0].source_name == 'RecoverableSource'
    assert pending[0].image_urls == ('https://example.test/0001.jpg',)

    restarted_source = RecoverableSource(
        str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False
    )
    monkeypatch.setattr(
        restarted_source,
        '_create_image_http_session',
        lambda: FakeImageSession(VALID_JPEG),
    )

    retry_result = restarted_source.retry_download_task(pending[0])

    assert retry_result.status == 'downloaded'
    assert DownloadTaskStore(tmp_path).list_pending() == []
    completed = DownloadTaskStore(tmp_path).get(pending[0].task_id)
    assert completed is not None
    assert completed.status == 'completed'
    assert completed.attempts == 2


def test_existing_archive_is_reused_only_after_integrity_check(tmp_path):
    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)
    valid_archive = tmp_path / 'valid.zip'
    with ZipFile(valid_archive, 'w') as archive:
        archive.writestr('0001.jpg', VALID_JPEG)
    invalid_archive = tmp_path / 'invalid.zip'
    invalid_archive.write_bytes(b'not-a-zip')

    assert source._find_existing_archive(str(tmp_path), 'valid') == str(valid_archive)
    assert source._find_existing_archive(str(tmp_path), 'invalid') is None


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
