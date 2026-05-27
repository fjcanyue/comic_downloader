from __future__ import annotations

from io import StringIO
from typing import Any, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser_modes import CLOAKBROWSER_MODE
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
