from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from downloader.browser.modes import CLOAKBROWSER_MODE, REQUESTS_MODE, SELENIUMBASE_MODE
from downloader.browser.page_loading import PageLoadAdapters, PageLoader, PageLoadRequest
from downloader.comic import ComicSource


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.encoding = None

    def raise_for_status(self) -> None:
        return None


class FakeHttp:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.response


class FakeCdp:
    def __init__(self, html: str) -> None:
        self.html = html
        self.find_calls = []

    def find(self, selector, timeout=None):
        self.find_calls.append((selector, timeout))

    def get_page_source(self):
        return self.html


class FakeSeleniumBaseBrowser:
    is_seleniumbase_driver = True

    def __init__(self, html: str) -> None:
        self.cdp = FakeCdp(html)
        self.activated_urls = []
        self.sleep_calls = []
        self.captcha_calls = 0

    def activate_cdp_mode(self, url: str):
        self.activated_urls.append(url)

    def sleep(self, seconds: float):
        self.sleep_calls.append(seconds)

    def solve_captcha(self):
        self.captcha_calls += 1


class FailingSeleniumBaseBrowser(FakeSeleniumBaseBrowser):
    def __init__(self, html: str) -> None:
        super().__init__(html)
        self.current_url = 'https://example.test/comic#blocked'

    def activate_cdp_mode(self, url: str):
        super().activate_cdp_mode(url)
        raise RuntimeError('Bad Gateway')

    def save_screenshot(self, name, folder=None, selector=None):
        screenshot_path = Path(folder or '.') / name
        screenshot_path.write_bytes(b'fake-png')


class FakeCloakBrowser:
    def __init__(self, html: str) -> None:
        self.html = html
        self.visited_urls = []
        self.wait_calls = []

    def get(self, url: str) -> None:
        self.visited_urls.append(url)

    def wait_for_selector(self, selector: str, timeout=None) -> None:
        self.wait_calls.append((selector, timeout))

    @property
    def page_source(self) -> str:
        return self.html


class CompatibilitySource(ComicSource):
    name = 'compatibility-source'
    base_url = 'https://example.test'

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_requests_success_returns_structured_page_result():
    http = FakeHttp(FakeResponse(200, '<html><body><h1>Loaded</h1></body></html>'))
    loader = PageLoader()

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/comic',
            base_url='https://example.test',
            browser_mode=REQUESTS_MODE,
            diagnostics_dir=Path('unused-diagnostics'),
        ),
        PageLoadAdapters(http=http),
    )

    assert result.ok is True
    assert result.root is not None
    assert result.root.xpath('string(//h1)') == 'Loaded'
    assert result.failure_reason is None
    assert http.get_calls == [
        (
            'https://example.test/comic',
            {'timeout': 30, 'headers': {'referer': 'https://example.test'}},
        )
    ]


def test_blocked_get_without_browser_adapter_returns_recoverable_failure():
    http = FakeHttp(FakeResponse(403, '<html><body>blocked</body></html>'))
    loader = PageLoader()

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/comic',
            base_url='https://example.test',
            browser_mode=REQUESTS_MODE,
            diagnostics_dir=Path('unused-diagnostics'),
        ),
        PageLoadAdapters(http=http),
    )

    assert result.ok is False
    assert result.root is None
    assert result.failure_reason == 'browser_adapter_required'
    assert result.status_code == 403
    assert result.required_browser_mode == SELENIUMBASE_MODE
    assert result.recoverable is True


def test_blocked_get_with_seleniumbase_adapter_falls_back_to_browser():
    http = FakeHttp(FakeResponse(403, '<html><body>blocked</body></html>'))
    browser = FakeSeleniumBaseBrowser(
        '<html><body><main class="page-main"><h1>Rendered</h1></main></body></html>'
    )
    loader = PageLoader()

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/comic',
            base_url='https://example.test',
            browser_mode=REQUESTS_MODE,
            wait_selector='.page-main',
            wait_seconds=7.0,
            diagnostics_dir=Path('unused-diagnostics'),
        ),
        PageLoadAdapters(http=http, browsers={SELENIUMBASE_MODE: browser}),
    )

    assert result.ok is True
    assert result.root is not None
    assert result.root.xpath('string(//h1)') == 'Rendered'
    assert result.browser_mode == SELENIUMBASE_MODE
    assert browser.activated_urls == ['https://example.test/comic']
    assert browser.cdp.find_calls == [('.page-main', 7.0)]


def test_blocked_post_does_not_use_default_browser_fallback():
    http = FakeHttp(FakeResponse(403, '<html><body>blocked</body></html>'))
    browser = FakeSeleniumBaseBrowser('<html><body><h1>Should not load</h1></body></html>')
    loader = PageLoader()

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/search',
            base_url='https://example.test',
            browser_mode=REQUESTS_MODE,
            method='POST',
            data={'k': 'keyword'},
            diagnostics_dir=Path('unused-diagnostics'),
        ),
        PageLoadAdapters(http=http, browsers={SELENIUMBASE_MODE: browser}),
    )

    assert result.ok is False
    assert result.failure_reason == 'unsupported_fallback_method'
    assert result.status_code == 403
    assert result.recoverable is False
    assert browser.activated_urls == []
    assert http.post_calls == [
        (
            'https://example.test/search',
            {
                'data': {'k': 'keyword'},
                'timeout': 30,
                'headers': {'referer': 'https://example.test'},
            },
        )
    ]


def test_seleniumbase_failure_records_diagnostics(monkeypatch):
    diagnostics_dir = Path('seleniumbase_diagnostics') / f'page-loading-{uuid4().hex}'
    browser = FailingSeleniumBaseBrowser('<html><body><h1>Bad Gateway</h1></body></html>')
    loader = PageLoader()
    monkeypatch.setenv('HTTPS_PROXY', 'http://user:secret@example.proxy:8080')

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/comic',
            base_url='https://example.test',
            browser_mode=SELENIUMBASE_MODE,
            diagnostics_dir=diagnostics_dir,
        ),
        PageLoadAdapters(
            http=FakeHttp(FakeResponse(200, '')), browsers={SELENIUMBASE_MODE: browser}
        ),
    )

    assert result.ok is False
    assert result.failure_reason == 'browser_load_failed'
    assert result.error_message == 'Bad Gateway'
    assert result.diagnostic_paths is not None

    html_path = Path(result.diagnostic_paths['html'])
    screenshot_path = Path(result.diagnostic_paths['screenshot'])
    metadata_path = Path(result.diagnostic_paths['metadata'])

    assert 'Bad Gateway' in html_path.read_text(encoding='utf-8')
    assert screenshot_path.read_bytes() == b'fake-png'

    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['original_url'] == 'https://example.test/comic'
    assert metadata['final_url'] == 'https://example.test/comic#blocked'
    assert metadata['error_type'] == 'RuntimeError'
    assert metadata['error_message'] == 'Bad Gateway'
    assert metadata['proxy_environment']['HTTPS_PROXY'] == {
        'set': True,
        'value': 'http://<credentials>@example.proxy:8080',
    }


def test_cloakbrowser_mode_uses_browser_adapter():
    browser = FakeCloakBrowser(
        '<html><body><main class="page-main"><h1>Cloaked</h1></main></body></html>'
    )
    loader = PageLoader()

    result = loader.load(
        PageLoadRequest(
            url='https://example.test/comic',
            base_url='https://example.test',
            browser_mode=CLOAKBROWSER_MODE,
            wait_selector='.page-main',
            wait_seconds=9.0,
            diagnostics_dir=Path('unused-diagnostics'),
        ),
        PageLoadAdapters(
            http=FakeHttp(FakeResponse(200, '')),
            browsers={CLOAKBROWSER_MODE: browser},
        ),
    )

    assert result.ok is True
    assert result.root is not None
    assert result.root.xpath('string(//h1)') == 'Cloaked'
    assert result.browser_mode == CLOAKBROWSER_MODE
    assert browser.visited_urls == ['https://example.test/comic']
    assert browser.wait_calls == [('.page-main', 9.0)]


def test_legacy_parse_html_returns_root_and_records_last_page_load_result():
    http = FakeHttp(FakeResponse(200, '<html><body><h1>Compat</h1></body></html>'))
    source = CompatibilitySource('download-output', http, None)

    root = source.__parse_html__('https://example.test/comic')

    assert root is not None
    assert root.xpath('string(//h1)') == 'Compat'
    assert source.last_page_load_result.ok is True
    assert source.last_page_load_result.root is root
