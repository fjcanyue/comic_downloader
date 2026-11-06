from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest
import requests
from lxml import html
from rich.cells import cell_len
from rich.console import Console

from downloader.models import Comic, SearchOutcome
from downloader.search_paging import SearchPageState, append_unique_results
from downloader.shell import Shell
from downloader.sources.adapters.manhuagui import ManhuaguiComic
from downloader.sources.profiles import SourceBinding, SourceProfile
from downloader.tui import SearchPageView, TerminalPresenter

FIXTURES = Path(__file__).parent / 'fixtures' / 'sources'


class PageHttp:
    def __init__(self, body):
        self.body = body
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = self.body.encode('utf-8')
        return response


def source_for(tmp_path, page=1):
    http = PageHttp(
        (FIXTURES / f'manhuagui-search-live-page{page}.html').read_text(encoding='utf-8')
    )
    source = ManhuaguiComic(str(tmp_path), cast(requests.Session, http), None)
    source.browser_mode = 'requests'
    return source, http


def test_real_search_structures_expose_next_page_and_keep_book_identity(tmp_path):
    source, http = source_for(tmp_path)
    first = source.search_with_diagnostics('海')
    assert first.error_message is None
    assert len(first.comics) == 2
    assert first.comics[0].url == 'https://www.manhuagui.com/comic/33509/'
    assert first.comics[0].name == '北海道辣妹贼拉可爱'
    assert first.comics[0].author == '伊科田海'
    assert first.next_page_url == 'https://www.manhuagui.com/s/%E6%B5%B7_p2.html'
    http.body = (FIXTURES / 'manhuagui-search-live-page2.html').read_text(encoding='utf-8')
    second = source.search_with_diagnostics('海', page_url=first.next_page_url)
    assert second.error_message is None and len(second.comics) == 2
    assert second.next_page_url == 'https://www.manhuagui.com/s/%E6%B5%B7_p3.html'
    assert not {c.url for c in first.comics} & {c.url for c in second.comics}
    assert http.urls == ['https://www.manhuagui.com/s/%E6%B5%B7.html', first.next_page_url]


@pytest.mark.parametrize(
    'url',
    [
        'https://evil.test/s/%E6%B5%B7_p2.html',
        'https://www.manhuagui.com/s/other_p2.html',
        'https://www.manhuagui.com/s/%E6%B5%B7.html',
        'https://www.manhuagui.com/s/%E6%B5%B7_p1.html',
        'https://www.manhuagui.com/s/%E6%B5%B7_p2.html?extra=1',
        'https://www.manhuagui.com/s/%E6%B5%B7_p2.html#fragment',
    ],
)
def test_page_url_is_validated_before_any_request(tmp_path, url):
    source, http = source_for(tmp_path)
    with pytest.raises(ValueError, match='不属于'):
        source.search_with_diagnostics('海', page_url=url)
    assert not http.urls


@pytest.mark.parametrize(
    'href', ['https://evil.test/s/海_p2.html', '/s/other_p2.html', '/s/海.html', '/s/海_p3.html']
)
def test_wrong_keyword_origin_or_skipped_page_link_is_reported(tmp_path, href):
    source, http = source_for(tmp_path)
    http.body = http.body.replace('/s/海_p2.html', href)
    response = source.search_with_diagnostics('海')
    assert len(response.comics) == 2
    assert response.error_message and '下一页地址' in response.error_message
    assert response.next_page_url is None


def test_last_page_clears_previous_cursor_without_stale_next_link(tmp_path):
    source, http = source_for(tmp_path)
    assert source.search_with_diagnostics('海').next_page_url
    root = html.fromstring(http.body)
    for link in root.xpath('//a[contains(., "下一页")]'):
        link.getparent().remove(link)
    http.body = cast(str, html.tostring(root, encoding='unicode'))
    response = source.search_with_diagnostics(
        '海', page_url='https://www.manhuagui.com/s/%E6%B5%B7_p2.html'
    )
    assert response.next_page_url is None and response.error_message is None


def test_partial_page_keeps_valid_results_but_does_not_advance_cursor(tmp_path):
    source, http = source_for(tmp_path, 2)
    http.body = http.body.replace('<li class="cf">', '<li></li><li class="cf">', 1)
    url = 'https://www.manhuagui.com/s/%E6%B5%B7_p2.html'
    response = source.search_with_diagnostics('海', page_url=url)
    outcome = SearchOutcome(
        'manhuagui',
        response.comics,
        response.error_message,
        0,
        next_page_url=response.next_page_url,
    )
    cursor = SearchPageState(url)
    cursor.accept(url, outcome)
    assert len(response.comics) == 2 and outcome.state == 'partial'
    assert cursor.pages == 1 and cursor.next_url == url and not cursor.visited


def test_append_deduplicates_within_source_but_preserves_other_sources_and_existing_objects():
    def comic(source, url, name):
        item = Comic()
        item.source, item.url, item.name = source, url, name
        return item

    original = comic('a', 'https://example.test/1', '原名称')
    existing = [original]
    incoming = [
        comic('a', original.url, '更改名称'),
        comic('b', original.url, '另一来源'),
        comic('a', 'https://example.test/2', '新条目'),
        comic('a', 'https://example.test/2', '重复'),
        comic('a', None, '无地址'),
    ]
    assert append_unique_results(existing, incoming) == 2
    assert existing == [original, incoming[1], incoming[2]]
    assert existing[0].name == '原名称'


def test_repeated_page_cursor_stops_without_looping_requests():
    cursor = SearchPageState('https://example.test/p2')
    outcome = SearchOutcome('fixture', [], None, 0, next_page_url=cursor.next_url)
    assert cursor.next_url is not None
    cursor.accept(cursor.next_url, outcome)
    assert cursor.pages == 2 and cursor.next_url is None
    assert outcome.error_message and '已加载过' in outcome.error_message


def test_special_keyword_pagination_uses_encoded_keyword_without_query_injection(tmp_path):
    source, http = source_for(tmp_path)
    keyword = '海 & / #_p2'
    path = f'/s/{quote(keyword, safe="")}_p2.html'
    http.body = http.body.replace('/s/海_p2.html', path)
    response = source.search_with_diagnostics(keyword)
    assert response.next_page_url == source.base_url + path
    assert response.error_message is None
    http.body = '<div class="no-result">没有找到</div>'
    last = source.search_with_diagnostics(keyword, page_url=response.next_page_url)
    assert last.next_page_url is None and last.error_message is None
    assert http.urls[-1] == source.base_url + path


@pytest.mark.parametrize('width', [48, 80, 120])
def test_paging_feedback_wraps_without_markup_or_truncated_source_commands(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    presenter.search_pages(
        [SearchPageView('manhuagui', 2, 19, True), SearchPageView('[red]源[/]', 1, 10, False)]
    )
    text = output.getvalue()
    plain = ''.join(text.replace('│', '').split())
    assert 'moremanhuagui' in plain and 'pnext只翻本地缓存' in plain
    assert '[red]源[/]' in plain and '未提供下一页' in plain
    assert max(cell_len(line) for line in text.splitlines()) <= width


def test_real_http_workflow_retries_same_page_then_stops_at_terminal_page(tmp_path, monkeypatch):
    first = (FIXTURES / 'manhuagui-search-live-page1.html').read_text(encoding='utf-8')
    root = html.fromstring(
        (FIXTURES / 'manhuagui-search-live-page2.html').read_text(encoding='utf-8')
    )
    for link in root.xpath('//a[contains(., "下一页")]'):
        link.getparent().remove(link)
    last = cast(str, html.tostring(root, encoding='unicode'))
    paths = []
    next_attempts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            body = first
            if '_p2.html' in self.path:
                next_attempts.append(self.path)
                body = '<html>temporary invalid page</html>' if len(next_attempts) == 1 else last
            payload = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f'http://127.0.0.1:{server.server_port}'
    bindings = {
        'manhuagui': SourceBinding(
            'manhuagui',
            ManhuaguiComic,
            SourceProfile('manhuagui', 'ManhuaguiComic', True, False, base_url=base_url),
        )
    }
    monkeypatch.setattr(Shell, '_discover_source_bindings', lambda *a, **kw: bindings)
    shell = Shell(str(tmp_path))
    shell.presenter = TerminalPresenter(Console(file=StringIO(), width=80, color_system=None))
    shell.console = shell.presenter.console
    shell.plain = True
    try:
        shell.onecmd('s 海')
        assert shell.last_command_ok and len(shell.context.searched_results) == 2
        original = list(shell.context.searched_results)
        cursor = shell.search_pages['manhuagui']
        cursor.last_attempt = float('-inf')
        shell.onecmd('more manhuagui')
        assert not shell.last_command_ok and cursor.pages == 1
        assert shell.context.searched_results == original
        cursor.last_attempt = float('-inf')
        shell.onecmd('more manhuagui')
        assert shell.last_command_ok and cursor.pages == 2 and cursor.next_url is None
        assert shell.context.searched_results[:2] == original
        assert len(shell.context.searched_results) == 4
        shell.onecmd('more manhuagui')
        shell.onecmd('p next')
        assert paths == ['/s/%E6%B5%B7.html', '/s/%E6%B5%B7_p2.html', '/s/%E6%B5%B7_p2.html']
        shell.onecmd('s 新关键词')
        assert shell.search_pages['manhuagui'].pages == 1
        assert (
            shell.search_pages['manhuagui'].next_url is None
        )  # Old keyword's next link is rejected.
    finally:
        shell.context.destroy()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
