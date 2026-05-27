from __future__ import annotations

from io import StringIO
from typing import Any, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader import browser_drivers
from downloader.browser_modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE
from downloader.comic import ComicSource
from downloader.morui import MoruiComic


class DummyHttp:
    pass


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
    driver.activate_cdp_mode('https://example.test/detail')

    assert created_kwargs == [{'uc': True, 'test': True, 'locale': 'zh-CN', 'headed': True}]
    assert fake_sb.activate_calls == ['https://example.test/search']
    assert active_cdp.get_calls == ['https://example.test/detail']


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
