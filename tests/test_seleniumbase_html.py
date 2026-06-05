from __future__ import annotations

import json
import os
import sys
from io import StringIO
from typing import Any, cast

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from seleniumbase.core import browser_launcher

from downloader import (
    browser_drivers,
    html_parser as html_parser_module,
    page_loading as page_loading_module,
)
from downloader.browser_modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
from downloader.comic import ComicSource
from downloader.morui import MoruiComic
from downloader.source_profiles import SourceProfile


class DummyHttp:
    pass


def seleniumbase_settings():
    return cast(Any, browser_launcher.sb_config).settings


class FakeResponse:
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class StatusHttp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeResponse(self.status_code, '<html><body>blocked</body></html>')


class BrowserHtmlSource(ComicSource):
    name = 'browser-html-source'
    base_url = 'https://example.test'

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


class FakeCdp:
    def __init__(self, html):
        self.html = html
        self.find_calls = []

    def find(self, selector, timeout=None):
        self.find_calls.append((selector, timeout))

    def sleep(self, seconds):
        raise AssertionError(f'unexpected sleep: {seconds}')

    def get_page_source(self):
        return self.html


class FakeSeleniumBase:
    def __init__(self, html):
        self.cdp = FakeCdp(html)
        self.activated_url = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def activate_cdp_mode(self, url):
        self.activated_url = url

    def sleep(self, seconds):
        pass

    def solve_captcha(self):
        pass


class FakePersistentSeleniumBase(FakeSeleniumBase):
    is_seleniumbase_driver = True


def test_seleniumbase_driver_navigates_active_cdp_page(monkeypatch):
    created_kwargs = []

    class FakeActiveCdp:
        def __init__(self):
            self.get_calls = []

        def get(self, url):
            self.get_calls.append(url)

    class FakeSb:
        def __init__(self):
            self.cdp = None
            self.activate_calls = []

        def activate_cdp_mode(self, url):
            self.activate_calls.append(url)
            self.cdp = FakeActiveCdp()

    fake_sb = FakeSb()

    class FakeContext:
        def __enter__(self):
            return fake_sb

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_sb_factory(**kwargs):
        created_kwargs.append(kwargs)
        return FakeContext()

    monkeypatch.setattr(browser_drivers, 'SB', fake_sb_factory)

    driver = browser_drivers.SeleniumBaseDriver(headless=False, timeout_seconds=3.0)
    driver.activate_cdp_mode('https://example.test/search')
    active_cdp = fake_sb.cdp
    assert active_cdp is not None
    driver.activate_cdp_mode('https://example.test/detail')

    assert created_kwargs == [{'uc': True, 'locale': 'zh-CN', 'headed': True}]
    assert fake_sb.activate_calls == ['https://example.test/search']
    assert active_cdp.get_calls == ['https://example.test/detail']


def test_seleniumbase_driver_uses_persistent_driver_dir_when_frozen(monkeypatch, tmp_path):
    created_kwargs = []
    local_app_data = tmp_path / 'LocalAppData'
    meipass_dir = tmp_path / '_MEI123456'
    expected_driver_dir = local_app_data / 'comic_downloader' / 'seleniumbase' / 'drivers'

    class FakeSb:
        cdp = None
        driver = None

    class FakeContext:
        def __enter__(self):
            return FakeSb()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_sb_factory(**kwargs):
        created_kwargs.append(kwargs)
        return FakeContext()

    monkeypatch.setattr(browser_drivers, 'SB', fake_sb_factory)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(meipass_dir), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(local_app_data))
    monkeypatch.setenv('PATH', os.defpath)
    monkeypatch.setattr(seleniumbase_settings(), 'NEW_DRIVER_DIR', None, raising=False)

    driver = browser_drivers.SeleniumBaseDriver(headless=True, timeout_seconds=3.0)

    configured_driver_dir = getattr(seleniumbase_settings(), 'NEW_DRIVER_DIR', None)

    assert created_kwargs == [{'uc': True, 'locale': 'zh-CN', 'headless': True}]
    assert configured_driver_dir == str(expected_driver_dir)
    assert expected_driver_dir.is_dir()
    assert str(meipass_dir) not in str(expected_driver_dir)

    driver.quit()


def test_source_seleniumbase_context_uses_persistent_driver_dir_when_frozen(monkeypatch, tmp_path):
    created_kwargs = []
    local_app_data = tmp_path / 'LocalAppData'
    meipass_dir = tmp_path / '_MEI789012'
    expected_driver_dir = local_app_data / 'comic_downloader' / 'seleniumbase' / 'drivers'

    class FakeContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_sb_factory(**kwargs):
        created_kwargs.append(kwargs)
        return FakeContext()

    monkeypatch.setattr(html_parser_module, 'SB', fake_sb_factory)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(meipass_dir), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(local_app_data))
    monkeypatch.setenv('PATH', os.defpath)
    monkeypatch.setattr(seleniumbase_settings(), 'NEW_DRIVER_DIR', None, raising=False)

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), None)
    source._seleniumbase_context()

    configured_driver_dir = getattr(seleniumbase_settings(), 'NEW_DRIVER_DIR', None)

    assert created_kwargs == [{'uc': True, 'test': True, 'locale': 'zh-CN', 'headed': True}]
    assert configured_driver_dir == str(expected_driver_dir)
    assert expected_driver_dir.is_dir()
    assert str(meipass_dir) not in str(expected_driver_dir)


def test_seleniumbase_driver_quit_skips_reconnect_teardown(monkeypatch):
    events = []

    class FakeManagedDriver:
        def __init__(self):
            self._already_quit = False

        def quit(self):
            events.append(('driver_quit', self._already_quit))

    class FakeSb:
        def __init__(self):
            self.cdp = None
            self.driver = FakeManagedDriver()

    fake_sb = FakeSb()

    class FakeContext:
        def __enter__(self):
            return fake_sb

        def __exit__(self, exc_type, exc, tb):
            teardown_done = getattr(fake_sb, '_BaseCase__called_teardown', False)
            events.append(('context_exit', teardown_done))
            if not teardown_done:
                raise KeyboardInterrupt
            return False

    monkeypatch.setattr(browser_drivers, 'SB', lambda **kwargs: FakeContext())

    driver = browser_drivers.SeleniumBaseDriver(headless=True, timeout_seconds=3.0)

    driver.quit()
    driver.quit()

    assert events == [('driver_quit', True), ('context_exit', True)]


def test_seleniumbase_driver_quit_suppresses_cleanup_interrupt(monkeypatch):
    exit_calls = []

    class FakeSb:
        cdp = None
        driver = None

    class FakeContext:
        def __enter__(self):
            return FakeSb()

        def __exit__(self, exc_type, exc, tb):
            exit_calls.append(True)
            raise KeyboardInterrupt

    monkeypatch.setattr(browser_drivers, 'SB', lambda **kwargs: FakeContext())

    driver = browser_drivers.SeleniumBaseDriver(headless=True, timeout_seconds=3.0)

    driver.quit()
    driver.quit()

    assert exit_calls == [True]


class FakeCloakDriver:
    def __init__(self, html):
        self.html = html
        self.visited_urls = []
        self.wait_calls = []

    def get(self, url):
        self.visited_urls.append(url)

    def wait_for_selector(self, selector, timeout=None):
        self.wait_calls.append((selector, timeout))

    @property
    def page_source(self):
        return self.html


def html_root(html):
    return etree.parse(StringIO(html), etree.HTMLParser())


def test_parse_html_can_use_seleniumbase_cdp(monkeypatch, tmp_path):
    html = '<html><body><main class="page-main"><h1>Rendered</h1></main></body></html>'
    fake_sb = FakeSeleniumBase(html)

    def fake_context(self):
        return fake_sb

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), None)
    source.seleniumbase_wait_selector = '.page-main'
    source.seleniumbase_wait_seconds = 7.0

    root = source.__parse_html__('https://example.test/search', 'SELENIUMBASE')

    assert fake_sb.activated_url == 'https://example.test/search'
    assert fake_sb.cdp.find_calls == [('.page-main', 7.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Rendered'


@pytest.mark.parametrize('status_code', [403, 429])
def test_requests_html_block_status_switches_to_seleniumbase(monkeypatch, tmp_path, status_code):
    html = '<html><body><main class="page-main"><h1>Fallback</h1></main></body></html>'
    fake_sb = FakeSeleniumBase(html)

    def fake_context(self):
        return fake_sb

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)

    http = StatusHttp(status_code)
    source = BrowserHtmlSource(str(tmp_path), cast(Any, http), None)
    source.browser_mode = REQUESTS_MODE
    source.browser_wait_selector = '.page-main'
    source.browser_wait_seconds = 5.0

    root = source.__parse_html__('https://example.test/search')

    assert http.get_calls == [
        (
            'https://example.test/search',
            {'timeout': 30, 'headers': {'referer': 'https://example.test'}},
        )
    ]
    assert source.browser_mode == REQUESTS_MODE
    assert source.last_page_load_result.browser_mode == SELENIUMBASE_MODE
    assert fake_sb.activated_url == 'https://example.test/search'
    assert fake_sb.cdp.find_calls == [('.page-main', 5.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Fallback'


def test_profiled_parse_html_uses_profile_base_url_and_keeps_fallback_non_sticky(
    monkeypatch, tmp_path
):
    html = '<html><body><main class="page-main"><h1>Fallback</h1></main></body></html>'
    fake_sb = FakeSeleniumBase(html)

    def fake_context(self):
        return fake_sb

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)

    http = StatusHttp(403)
    profile = SourceProfile(
        source_name='browser-html',
        class_name='BrowserHtmlSource',
        enabled=True,
        deprecated=False,
        base_url='https://profile.example',
        browser_mode=REQUESTS_MODE,
        browser_wait_selector='.page-main',
        browser_wait_seconds=5.0,
    )
    source = BrowserHtmlSource(str(tmp_path), cast(Any, http), None, profile=profile)

    root = source.__parse_html__('https://example.test/search')

    assert http.get_calls == [
        (
            'https://example.test/search',
            {'timeout': 30, 'headers': {'referer': 'https://profile.example'}},
        )
    ]
    assert source.profile is profile
    assert profile.browser_mode == REQUESTS_MODE
    assert source.browser_mode == REQUESTS_MODE
    assert source.last_page_load_result.browser_mode == SELENIUMBASE_MODE
    assert fake_sb.cdp.find_calls == [('.page-main', 5.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Fallback'


def test_parse_html_reuses_seleniumbase_driver(monkeypatch, tmp_path):
    html = '<html><body><main class="page-main"><h1>Reused</h1></main></body></html>'
    fake_driver = FakePersistentSeleniumBase(html)

    def fail_context(self):
        raise AssertionError('reusable SeleniumBase driver should be used')

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fail_context)

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), fake_driver)
    source.browser_mode = SELENIUMBASE_MODE
    source.browser_wait_selector = '.page-main'
    source.browser_wait_seconds = 3.0

    root = source.__parse_html__('https://example.test/detail')

    assert fake_driver.activated_url == 'https://example.test/detail'
    assert fake_driver.cdp.find_calls == [('.page-main', 3.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Reused'


def test_seleniumbase_html_retry_records_diagnostics_before_success(monkeypatch, tmp_path):
    html = '<html><body><main class="page-main"><h1>Recovered</h1></main></body></html>'
    failed_html = '<html><body><h1>Bad Gateway</h1></body></html>'
    contexts = []
    sleep_calls = []

    class RetryFakeCdp:
        def __init__(self, page_html):
            self.html = page_html
            self.find_calls = []

        def find(self, selector, timeout=None):
            self.find_calls.append((selector, timeout))

        def get_page_source(self):
            return self.html

    class RetryFakeSeleniumBase:
        def __init__(self, *, should_fail):
            self.should_fail = should_fail
            self.cdp = RetryFakeCdp(failed_html if should_fail else html)
            self.activated_urls = []
            self.current_url = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def activate_cdp_mode(self, url):
            self.activated_urls.append(url)
            self.current_url = url + '#gateway'
            if self.should_fail:
                raise RuntimeError('Bad Gateway')

        def sleep(self, seconds):
            pass

        def solve_captcha(self):
            pass

        def save_screenshot(self, name, folder=None, selector=None):
            screenshot_path = os.path.join(folder or '', name)
            with open(screenshot_path, 'wb') as f:
                f.write(b'fake-png')

    def fake_context(self):
        should_fail = len(contexts) == 0
        context = RetryFakeSeleniumBase(should_fail=should_fail)
        contexts.append(context)
        return context

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)
    monkeypatch.setattr(page_loading_module.time, 'sleep', lambda seconds: sleep_calls.append(seconds))

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), None)
    source.browser_mode = SELENIUMBASE_MODE
    source.browser_wait_selector = '.page-main'
    source.browser_wait_seconds = 2.0

    root = source.__parse_html__('https://example.test/search')

    assert root is not None
    assert root.xpath('string(//h1)') == 'Recovered'
    assert [context.activated_urls for context in contexts] == [
        ['https://example.test/search'],
        ['https://example.test/search'],
    ]
    assert sleep_calls == [3.0]

    diagnostic_dir = tmp_path / 'seleniumbase_diagnostics'
    html_paths = list(diagnostic_dir.glob('*.html'))
    screenshot_paths = list(diagnostic_dir.glob('*.png'))
    metadata_paths = list(diagnostic_dir.glob('*.json'))

    assert len(html_paths) == 1
    assert len(screenshot_paths) == 1
    assert len(metadata_paths) == 1
    assert 'Bad Gateway' in html_paths[0].read_text(encoding='utf-8')

    metadata = json.loads(metadata_paths[0].read_text(encoding='utf-8'))
    assert metadata['original_url'] == 'https://example.test/search'
    assert metadata['final_url'] == 'https://example.test/search#gateway'
    assert metadata['attempt'] == 1
    assert metadata['error'] == "RuntimeError('Bad Gateway')"


def test_seleniumbase_context_enter_failure_records_metadata_diagnostics(monkeypatch, tmp_path):
    contexts = []
    sleep_calls = []

    class FailingEnterSeleniumBase:
        def __enter__(self):
            contexts.append(self)
            raise RuntimeError('Bad Gateway')

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_context(self):
        return FailingEnterSeleniumBase()

    monkeypatch.setattr(BrowserHtmlSource, '_seleniumbase_context', fake_context)
    monkeypatch.setattr(page_loading_module.time, 'sleep', lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setenv('HTTPS_PROXY', 'http://user:secret@example.proxy:8080')

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), None)
    source.browser_mode = SELENIUMBASE_MODE

    root = source.__parse_html__('https://example.test/search')

    assert root is None
    assert len(contexts) == 2
    assert sleep_calls == [3.0]

    diagnostic_dir = tmp_path / 'seleniumbase_diagnostics'
    html_paths = list(diagnostic_dir.glob('*.html'))
    screenshot_paths = list(diagnostic_dir.glob('*.png'))
    metadata_paths = sorted(diagnostic_dir.glob('*.json'))

    assert html_paths == []
    assert screenshot_paths == []
    assert len(metadata_paths) == 2

    metadata = json.loads(metadata_paths[0].read_text(encoding='utf-8'))
    assert metadata['original_url'] == 'https://example.test/search'
    assert metadata['final_url'] is None
    assert metadata['attempt'] == 1
    assert metadata['error'] == "RuntimeError('Bad Gateway')"
    assert metadata['error_type'] == 'RuntimeError'
    assert metadata['error_module'] == 'builtins'
    assert metadata['error_message'] == 'Bad Gateway'
    assert metadata['error_args'] == ['Bad Gateway']
    assert metadata['error_chain'][0]['type'] == 'RuntimeError'
    assert metadata['error_chain'][0]['message'] == 'Bad Gateway'
    assert metadata['proxy_environment']['HTTPS_PROXY'] == {
        'set': True,
        'value': 'http://<credentials>@example.proxy:8080',
    }
    assert metadata['html_path'] is None
    assert metadata['screenshot_path'] is None


def test_parse_html_uses_source_configured_cloakbrowser_driver(tmp_path):
    html = '<html><body><main class="page-main"><h1>Cloaked</h1></main></body></html>'
    fake_driver = FakeCloakDriver(html)

    source = BrowserHtmlSource(str(tmp_path), cast(Any, DummyHttp()), fake_driver)
    source.browser_mode = CLOAKBROWSER_MODE
    source.browser_wait_selector = '.page-main'
    source.browser_wait_seconds = 9.0

    root = source.__parse_html__('https://example.test/search')

    assert fake_driver.visited_urls == ['https://example.test/search']
    assert fake_driver.wait_calls == [('.page-main', 9.0)]
    assert root is not None
    assert root.xpath('string(//h1)') == 'Cloaked'


def test_morui_search_uses_seleniumbase_html(monkeypatch, tmp_path):
    calls = []
    html = """
    <html>
      <body>
        <div class="page-main">
          <h4 class="fl">1</h4>
          <ul>
            <li class="item-lg">
              <a title="Test Comic" href="/comic/1">Test Comic</a>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """

    def fake_parse_html(self, url, *args, **kwargs):
        calls.append((url, args, kwargs))
        return html_root(html)

    monkeypatch.setattr(MoruiComic, '__parse_html__', fake_parse_html)

    source = MoruiComic(str(tmp_path), cast(Any, DummyHttp()), None)
    source.config = {
        'search_xpath': "//li[contains(@class,'item-lg')]",
        'search_extract': {'name': './a/@title', 'url': './a/@href'},
    }

    results = source.search('test')

    assert calls == [
        (
            'https://www.morui.com/search/?keywords=test',
            (),
            {},
        )
    ]
    assert len(results) == 1
    assert results[0].name == 'Test Comic'
    assert results[0].url == 'https://www.morui.com/comic/1'


class NoNetworkHttp:
    def get(self, *args, **kwargs):
        raise AssertionError('SeleniumBase image download should not use requests directly')


class FakeSeleniumBaseDownloadDriver:
    is_seleniumbase_driver = True

    def __init__(self):
        self.downloads = []

    def download_to_file(self, url, file_path, *, referer=None):
        self.downloads.append((url, referer))
        with open(file_path, 'wb') as f:
            f.write(b'image-bytes')


def test_seleniumbase_image_download_uses_driver(tmp_path):
    driver = FakeSeleniumBaseDownloadDriver()
    source = BrowserHtmlSource(str(tmp_path), cast(Any, NoNetworkHttp()), driver)
    source.browser_mode = SELENIUMBASE_MODE
    source.base_url = 'https://example.test'

    image_dir = tmp_path / 'chapter'
    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://cdn.example.test/0001.jpg'],
    )

    assert driver.downloads == [('https://cdn.example.test/0001.jpg', 'https://example.test')]
    assert result.status == 'downloaded'
    assert result.downloaded_count == 1
    assert result.archive_path is not None
