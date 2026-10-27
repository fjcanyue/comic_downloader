from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest
import requests

from downloader.browser.manager import DriverManager
from downloader.comic import ComicSource
from downloader.models import Comic
from downloader.search_browser.loader import DetailLoader, PreviewCancelledError, PreviewWorker
from downloader.search_browser.state import SearchItem
from downloader.sources.profiles import SourceBinding, SourceProfile


class PreviewSource(ComicSource):
    def search(self, keyword):
        return []

    def info(self, url):
        root = self.__parse_html__(url)
        if root is None:
            return None
        comic = Comic()
        comic.name = root.xpath('string(//h1)')
        return comic

    def __parse_imgs__(self, url):
        return []


@pytest.mark.parametrize(
    'mode,status',
    [
        ('requests', 200),
        ('requests', 403),
        ('requests', 429),
        ('seleniumbase', 200),
        ('cloakbrowser', 200),
    ],
)
def test_preview_owns_session_driver_and_http_fallback_on_one_worker_thread(
    monkeypatch, tmp_path, mode, status
):
    events = []

    def record(name):
        events.append((name, threading.get_ident()))

    class Session(requests.Session):
        def __init__(self):
            super().__init__()
            record('session-created')

        def request(self, *args, **kwargs):
            record('http-request')
            response = requests.Response()
            response.status_code = status
            response._content = b'<html><h1>local preview</h1></html>'
            response._content_consumed = True
            response.encoding = 'utf-8'
            return response

        def close(self):
            record('session-closed')
            super().close()

    class Driver:
        is_seleniumbase_driver = mode == 'seleniumbase'

        def __init__(self):
            record('driver-created')

        def activate_cdp_mode(self, url):
            record('driver-get')

        def get(self, url):
            record('driver-get')

        def sleep(self, seconds):
            pass

        @property
        def page_source(self):
            record('driver-read')
            return '<html><h1>local preview</h1></html>'

        def get_page_source(self):
            return self.page_source

        def quit(self):
            record('driver-closed')

    def init_driver(manager, profile):
        manager.current_driver = Driver()
        return True

    @contextmanager
    def fallback(source):
        driver = Driver()
        try:
            yield driver
        finally:
            driver.quit()

    monkeypatch.setattr(DriverManager, 'init_driver', init_driver)
    monkeypatch.setattr(PreviewSource, '_seleniumbase_context', fallback)
    binding = SourceBinding(
        'fixture',
        PreviewSource,
        SourceProfile(
            'fixture',
            'PreviewSource',
            True,
            False,
            browser_mode=mode,
            base_url='https://example.test',
            seleniumbase_wait_seconds=0,
        ),
    )
    loader = DetailLoader({'fixture': binding}, str(tmp_path), Session)
    worker = PreviewWorker(loader)
    item = SearchItem(0, 'fixture', 'https://example.test/comic', '漫画', '')
    try:
        worker.submit(item)
        result = worker.results.get(timeout=5)
        assert not result.error
        assert result.comic is not None and result.comic.name == 'local preview'
    finally:
        worker.stop()
        worker.join()
    owner_threads = {ident for _, ident in events}
    assert len(owner_threads) == 1
    assert threading.get_ident() not in owner_threads
    names = [name for name, _ in events]
    assert 'session-closed' in names
    if mode != 'requests' or status != 200:
        assert names.count('driver-created') == names.count('driver-closed') == 1
        assert 'driver-get' in names and 'driver-read' in names
    else:
        assert 'driver-created' not in names
    assert not worker.alive


@pytest.mark.parametrize('failure', ['source', 'driver', 'none'])
def test_preview_errors_close_resources_without_touching_shell_context(
    monkeypatch, tmp_path, failure
):
    closed = []

    class Session(requests.Session):
        def close(self):
            closed.append('http')
            super().close()

    class Driver:
        def quit(self):
            closed.append('driver')

    def init_driver(manager, profile):
        if failure == 'driver':
            return False
        manager.current_driver = Driver()
        return True

    def info(source, url):
        if failure == 'source':
            raise ValueError('parser failed')

    monkeypatch.setattr(DriverManager, 'init_driver', init_driver)
    monkeypatch.setattr(PreviewSource, 'info', info)
    binding = SourceBinding(
        'fixture',
        PreviewSource,
        SourceProfile('fixture', 'PreviewSource', True, False, browser_mode='cloakbrowser'),
    )
    worker = PreviewWorker(DetailLoader({'fixture': binding}, str(tmp_path), Session))
    try:
        worker.submit(SearchItem(0, 'fixture', 'https://example.test/comic', '漫画', ''))
        result = worker.results.get(timeout=5)
        assert result.error and result.comic is None
    finally:
        worker.stop()
        worker.join()
    assert closed.count('http') == 1
    assert closed.count('driver') == (0 if failure == 'driver' else 1)


def test_stopped_loader_does_not_initialize_any_resources(tmp_path):
    binding = SourceBinding(
        'fixture', PreviewSource, SourceProfile('fixture', 'PreviewSource', True, False)
    )

    def factory():
        pytest.fail('cancelled preview must not initialize a session')

    stop = threading.Event()
    stop.set()
    with pytest.raises(PreviewCancelledError):
        DetailLoader({'fixture': binding}, str(tmp_path), factory)(
            SearchItem(0, 'fixture', 'https://example.test/comic', '漫画', ''), stop
        )


def test_pending_preview_is_replaceable_and_repeated_request_is_deduplicated():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def load(item, stop):
        calls.append(item.index)
        started.set()
        assert release.wait(3)
        return Comic()

    worker = PreviewWorker(load)
    all_items = [
        SearchItem(i, 'fixture', f'https://example.test/{i}', str(i), '') for i in range(4)
    ]
    try:
        first = worker.submit(all_items[0])
        assert started.wait(2)
        assert worker.submit(all_items[0]) == first
        second = worker.submit(all_items[1])
        assert worker.submit(all_items[1]) == second
        worker.submit(all_items[2])
        dropped = worker.results.get(timeout=2)
        assert dropped.cancelled and dropped.token == second
        release.set()
        assert worker.results.get(timeout=2).item.index == 0
        assert worker.results.get(timeout=2).item.index == 2
    finally:
        release.set()
        worker.stop()
        worker.join()
    assert calls == [0, 2]
    with pytest.raises(RuntimeError, match='已关闭'):
        worker.submit(all_items[3])


def test_cancellation_after_http_response_prevents_starting_fallback_browser(monkeypatch, tmp_path):
    stopped = threading.Event()

    class Session(requests.Session):
        def request(self, *args, **kwargs):
            stopped.set()
            response = requests.Response()
            response.status_code = 403
            response._content = b'blocked'
            response._content_consumed = True
            return response

    def forbidden(source):
        pytest.fail('must not start a fallback browser after stop')

    monkeypatch.setattr(PreviewSource, '_seleniumbase_context', forbidden)
    binding = SourceBinding(
        'fixture', PreviewSource, SourceProfile('fixture', 'PreviewSource', True, False)
    )
    with pytest.raises(PreviewCancelledError):
        DetailLoader({'fixture': binding}, str(tmp_path), Session)(
            SearchItem(0, 'fixture', 'https://example.test/comic', '漫画', ''), stopped
        )
