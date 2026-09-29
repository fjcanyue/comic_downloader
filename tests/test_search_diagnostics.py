from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import parse_qs, urlsplit

import main as main_module
import pytest
import requests

from downloader.browser.page_loading import PageLoadResult
from downloader.comic import ComicSource
from downloader.models import Comic, SourceSearchResult
from downloader.shell import SearchTask, Shell, _run_search_parallel
from downloader.sources.adapters.dmzj import DmzjComic
from downloader.sources.adapters.dumanwu import DumanwuComic
from downloader.sources.adapters.manhuafree import ManhuafreeComic
from downloader.sources.adapters.manhuagui import ManhuaguiComic
from downloader.sources.adapters.maofly import MaoflyComic
from downloader.sources.profiles import SourceBinding, SourceProfile
from downloader.sources.templates import ConfigurableSearchMixin


class FakeHttp:
    def __init__(self, html='<main></main>', error=None):
        self.html = html
        self.error = error
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if self.error:
            raise self.error
        response = requests.Response()
        response.status_code = 200
        response._content = self.html.encode()
        response.url = url
        return response

    def post(self, url, **kwargs):
        return self.get(url, **kwargs)


class ConfigSource(ConfigurableSearchMixin, ComicSource):
    name = 'Fixture'
    base_url = 'https://example.test'
    search_url_template = '{base_url}/search?q={keyword}'
    search_root_xpath = '//main'

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def make_source(tmp_path, http):
    source = ConfigSource(str(tmp_path), http, None)
    source.config = {
        'search_xpath': './/a',
        'search_extract': {'url': './@href', 'name': './text()'},
    }
    return source


def test_swallowed_network_error_is_visible_in_diagnostic_search(tmp_path):
    source = make_source(tmp_path, FakeHttp(error=requests.Timeout('network timed out')))
    response = source.search_with_diagnostics('漫画')
    assert response.comics == []
    assert response.error_message is not None
    assert 'network timed out' in response.error_message
    assert source.last_page_load_result is not None
    assert source.last_page_load_result.failure_reason == 'page_load_failed'


def test_browser_failure_reports_http_reason(tmp_path, monkeypatch):
    source = make_source(tmp_path, FakeHttp())
    monkeypatch.setattr(
        source,
        '_load_page_for_legacy_parse_html',
        lambda request: PageLoadResult(
            failure_reason='browser_adapter_required',
            status_code=429,
        ),
    )
    response = source.search_with_diagnostics('漫画')
    assert response.error_message is not None
    assert '429' in response.error_message
    assert response.error_message is not None
    assert 'browser_adapter_required' in response.error_message


def test_valid_empty_results_clear_previous_failure(tmp_path):
    source = make_source(tmp_path, FakeHttp())
    source.search_error = 'previous failure'
    source.last_parse_error = 'previous parse error'
    source.last_page_load_result = PageLoadResult(failure_reason='previous failure')
    response = source.search_with_diagnostics('漫画')
    assert response.comics == []
    assert response.error_message is None


def test_changed_page_structure_is_not_reported_as_empty_success(tmp_path):
    source = make_source(tmp_path, FakeHttp('<html><body>login page</body></html>'))
    response = source.search_with_diagnostics('漫画')
    assert response.comics == []
    assert response.error_message is not None
    assert '内容区域' in response.error_message


def test_invalid_xpath_is_reported_even_when_parser_swallows_exception(tmp_path):
    source = make_source(tmp_path, FakeHttp())
    source.config['search_xpath'] = '//['
    response = source.search_with_diagnostics('漫画')
    assert response.error_message is not None
    assert 'XPath' in response.error_message


def test_partial_results_survive_item_parse_failure(tmp_path, monkeypatch):
    source = make_source(
        tmp_path, FakeHttp('<main><a href="/1">one</a><a href="/2">two</a></main>')
    )
    parse = source._comic_from_search_item

    def parse_item(item):
        if item['url'] == '/2':
            raise ValueError('changed item')
        return parse(item)

    monkeypatch.setattr(source, '_comic_from_search_item', parse_item)
    response = source.search_with_diagnostics('漫画')
    assert len(response.comics) == 1
    assert response.comics[0].url == 'https://example.test/1'
    assert response.error_message is not None
    assert 'changed item' in response.error_message


def test_special_characters_are_one_search_keyword(tmp_path):
    http = FakeHttp()
    source = make_source(tmp_path, http)
    keyword = '漫画 & a/b # 特别篇'
    source.search_with_diagnostics(keyword)
    parsed = urlsplit(http.urls[0])
    assert parse_qs(parsed.query) == {'q': [keyword]}
    assert parsed.fragment == ''


def search_task(name, function, *, driver=False, unavailable=None):
    return SearchTask(
        name,
        ConfigSource,
        SourceProfile(name, 'ConfigSource', True, False),
        function,
        driver,
        name,
        unavailable_reason=unavailable,
    )


def test_parallel_progress_is_emitted_while_another_source_is_still_waiting():
    slow_started = threading.Event()
    release_slow = threading.Event()
    progress = []

    def slow(keyword):
        slow_started.set()
        assert release_slow.wait(3), (
            'fast completion was not reported while slow source was waiting'
        )
        return []

    def fast(keyword):
        assert slow_started.wait(3)
        return []

    def completed(outcome):
        progress.append(outcome.source_name)
        if outcome.source_name == 'fast':
            release_slow.set()

    outcomes = _run_search_parallel(
        [search_task('slow', slow), search_task('fast', fast)],
        '漫画',
        None,
        threading.Lock(),
        max_workers=2,
        on_complete=completed,
    )
    assert progress == ['fast', 'slow']
    assert all(outcome.ok for outcome in outcomes)


def test_serial_search_emits_progress_for_each_source():
    progress = []
    _run_search_parallel(
        [search_task('first', lambda _: []), search_task('second', lambda _: [])],
        '漫画',
        None,
        threading.Lock(),
        max_workers=1,
        on_complete=lambda outcome: progress.append(outcome.source_name),
    )
    assert progress == ['first', 'second']


def test_known_unavailable_search_never_calls_source_or_driver():
    task = search_task(
        'disabled',
        lambda _: pytest.fail('unavailable source was executed'),
        driver=True,
        unavailable='需要验证码',
    )
    outcome = _run_search_parallel([task], '漫画', None, None)[0]
    assert outcome.state == 'skipped'
    assert outcome.error_message == '需要验证码'
    assert outcome.ok is False


def test_runner_preserves_partial_results_and_total_before_optional_limit():
    comics = [Comic() for _ in range(15)]
    outcome = _run_search_parallel(
        [
            search_task('fixture', lambda _: SourceSearchResult(comics, '部分条目缺失')),
        ],
        '漫画',
        10,
        None,
    )[0]
    assert len(outcome.results) == 10
    assert outcome.total_count == 15
    assert outcome.state == 'partial'
    assert outcome.ok is False


@pytest.mark.parametrize(
    'source_class',
    [
        DumanwuComic,
        ManhuafreeComic,
        ManhuaguiComic,
        MaoflyComic,
        DmzjComic,
    ],
)
def test_custom_adapters_do_not_hide_network_failures_as_empty_success(tmp_path, source_class):
    source = source_class(str(tmp_path), FakeHttp(error=requests.Timeout('网络超时')), None)
    source.browser_mode = 'requests'
    outcome = _run_search_parallel(
        [
            search_task('fixture', source.search_with_diagnostics),
        ],
        '漫画',
        None,
        None,
    )[0]
    assert outcome.state == 'failed'
    assert outcome.error_message is not None
    assert '网络超时' in outcome.error_message


@pytest.mark.parametrize(
    'source_class, html',
    [
        (
            DumanwuComic,
            '<div class="view-item"><div class="itemnar"><p><a href="/1" title="valid"/></p></div><div class="itemnar"><p/></div></div>',
        ),
        (
            MaoflyComic,
            '<div class="comic-main-section"><div class="comicbook-index"><a href="/1" title="valid"/></div><div class="comicbook-index"/></div>',
        ),
        (
            MaoflyComic,
            '<div class="comic-main-section"><div class="comicbook-index"><a href="/1" title="valid"/></div><div class="comicbook-index"><a/></div></div>',
        ),
        (
            ManhuaguiComic,
            '<div class="book-result"><ul><li><div><a href="/1" title="valid"/></div></li><li/></ul></div>',
        ),
    ],
)
def test_manual_adapters_preserve_valid_entries_when_another_entry_is_broken(
    tmp_path, source_class, html
):
    source = source_class(str(tmp_path), FakeHttp(html), None)
    source.browser_mode = 'requests'
    response = source.search_with_diagnostics('漫画')
    assert len(response.comics) == 1
    assert response.comics[0].name == 'valid'
    assert response.error_message is not None
    assert '部分搜索条目' in response.error_message


def test_explicit_empty_result_page_is_not_a_structure_failure(tmp_path):
    source = ManhuaguiComic(
        str(tmp_path),
        cast(requests.Session, FakeHttp('<div class="no-result">没有找到</div>')),
        None,
    )
    source.browser_mode = 'requests'
    response = source.search_with_diagnostics('漫画')
    assert response.comics == []
    assert response.error_message is None


def test_cli_real_http_search_reports_failed_source_and_keeps_all_other_results(
    tmp_path, monkeypatch, capsys
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/bad/'):
                self.send_error(500)
                return
            html = (
                '<main>'
                + ''.join(f'<a href="/comic/{i}">漫画{i:03d}</a>' for i in range(1, 26))
                + '</main>'
            )
            data = html.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    class HttpSource(ConfigSource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.config = {
                'search_xpath': './/a',
                'search_extract': {'url': './@href', 'name': './text()'},
            }

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bindings = {
        name: SourceBinding(
            name,
            HttpSource,
            SourceProfile(
                name,
                'HttpSource',
                True,
                False,
                base_url=f'http://127.0.0.1:{server.server_port}/{name}',
            ),
        )
        for name in ('ok', 'bad')
    }
    monkeypatch.setattr(Shell, '_discover_source_bindings', lambda *a, **kw: bindings)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', str(tmp_path), 'search', '漫画 & #'])
    try:
        assert main_module.main() == 0
        output = capsys.readouterr().out
        assert '本次搜索源状态' in output
        assert '500' in output
        assert '漫画025' in output
        assert '结果可能不完整' in output
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
