from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic, ComicBook, ComicVolume
from downloader.sources import load_source_classes
from downloader.sources.adapters.manhuafree import ManhuafreeComic
from downloader.sources.parsing import finalize_comic_info, http_url

FIXTURES = Path(__file__).parent / 'fixtures' / 'sources'
SOURCE_NAMES = ['morui', 'thmh', 'manhuazhan', 'tuku', 'dumanwu', 'manhuagui', 'manhuafree']
HTML_SOURCES = SOURCE_NAMES[:-1]
BASE = 'https://example.test'
PAGE = BASE + '/demo/'


class FixtureResponse(requests.Response):
    def __init__(self, url, content, status=200):
        super().__init__()
        self.url = url
        self._content = content.encode('utf-8')
        self._content_consumed = True
        self.status_code = status
        self.encoding = 'utf-8'
        self.closed = False

    def close(self):
        self.closed = True
        super().close()


class FixtureHttp:
    def __init__(self, name):
        self.html = (FIXTURES / f'{name}-info.html').read_text(encoding='utf-8')
        self.api = json.loads((FIXTURES / 'manhuafree-api.json').read_text(encoding='utf-8'))
        self.more = json.loads((FIXTURES / 'dumanwu-more.json').read_text(encoding='utf-8'))
        self.more_status = 200
        self.responses = []
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        content = json.dumps(self.api) if '/api/manga/get' in url else self.html
        response = FixtureResponse(url, content)
        self.responses.append(response)
        return response

    def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        assert url == BASE + '/morechapter', 'unexpected network request'
        response = FixtureResponse(url, json.dumps(self.more), self.more_status)
        self.responses.append(response)
        return response


def source_fixture(name, tmp_path):
    http = FixtureHttp(name)
    source = load_source_classes()[name](str(tmp_path), cast(Any, http), None)
    source.browser_mode = 'requests'
    source.base_url = BASE
    if name == 'manhuafree':
        source.config['api_base_url'] = BASE
    return source, http


def test_every_default_source_has_a_detail_contract_fixture():
    assert set(load_source_classes()) == set(SOURCE_NAMES)


@pytest.mark.parametrize('name', SOURCE_NAMES)
def test_real_adapter_parses_nested_titles_and_chapter_order(name, tmp_path):
    source, http = source_fixture(name, tmp_path)
    comic = source.info(PAGE)
    assert comic is not None
    assert comic.name == '星海纪行'
    assert len(comic.books) == 1
    volumes = comic.books[0].vols
    assert [volume.name for volume in volumes] == ['第一话', '第二话']
    suffixes = (
        ['/manga/starsea/chapter-1', '/manga/starsea/chapter-2']
        if name == 'manhuafree'
        else ['/chapter/1', '/chapter/2']
    )
    assert [volume.url for volume in volumes] == [BASE + suffix for suffix in suffixes]
    assert comic.parse_warnings == []
    if name == 'manhuafree':
        assert http.calls[-1][2]['timeout'] == 30
        assert http.responses[-1].closed


@pytest.mark.parametrize('name', HTML_SOURCES)
def test_bad_link_preserves_other_chapters_and_surfaces_warning(name, tmp_path):
    source, http = source_fixture(name, tmp_path)
    root = etree.HTML(http.html)
    root.xpath('//a[@data-chapter="2"]')[0].set('href', 'javascript:void(0)')
    http.html = etree.tostring(root, encoding='unicode')
    comic = source.info(PAGE)
    assert comic is not None
    assert [volume.name for volume in comic.books[0].vols] == ['第一话']
    assert any('无效' in warning for warning in comic.parse_warnings)


@pytest.mark.parametrize('name', HTML_SOURCES)
def test_absolute_and_protocol_relative_links_are_not_concatenated(name, tmp_path):
    source, http = source_fixture(name, tmp_path)
    root = etree.HTML(http.html)
    root.xpath('//a[@data-chapter="1"]')[0].set('href', BASE + '/chapter/1')
    root.xpath('//a[@data-chapter="2"]')[0].set('href', '//example.test/chapter/2')
    http.html = etree.tostring(root, encoding='unicode')
    comic = source.info(PAGE)
    assert comic is not None
    assert [volume.url for volume in comic.books[0].vols] == [
        BASE + '/chapter/1',
        BASE + '/chapter/2',
    ]


@pytest.mark.parametrize('name', SOURCE_NAMES)
def test_unrecognized_detail_page_does_not_create_a_comic(name, tmp_path):
    source, http = source_fixture(name, tmp_path)
    http.html = (FIXTURES / 'structure-changed.html').read_text(encoding='utf-8')
    assert source.info(PAGE) is None


@pytest.mark.parametrize('name', SOURCE_NAMES)
def test_empty_catalog_is_explicit_and_has_no_downloadable_volumes(name, tmp_path):
    source, http = source_fixture(name, tmp_path)
    if name == 'manhuafree':
        http.api['data']['chapters'] = []
    else:
        root = etree.HTML(http.html)
        for link in root.xpath('//a[@data-chapter]'):
            link.getparent().remove(link)
        http.html = etree.tostring(root, encoding='unicode')
    comic = source.info(PAGE)
    assert comic is not None
    assert not any(book.vols for book in comic.books)
    assert any('未解析到可下载章节' in warning for warning in comic.parse_warnings)


def test_manhuafree_retains_valid_chapters_after_malformed_api_entry(tmp_path):
    source, http = source_fixture('manhuafree', tmp_path)
    http.api['data']['chapters'].insert(1, {'attributes': None})
    comic = source.info(PAGE)
    assert comic is not None
    assert [volume.name for volume in comic.books[0].vols] == ['第一话', '第二话']
    assert comic.parse_warnings


def test_group_without_title_retains_chapters_and_uses_explicit_fallback(tmp_path):
    source, http = source_fixture('morui', tmp_path)
    root = etree.HTML(http.html)
    title = root.xpath('//div[@class="chapter-category"]')[0]
    title.getparent().remove(title)
    http.html = etree.tostring(root, encoding='unicode')
    comic = source.info(PAGE)
    assert comic is not None
    assert comic.books[0].name == '章节分组 1'
    assert len(comic.books[0].vols) == 2
    assert any('分组缺少标题' in warning for warning in comic.parse_warnings)


def test_more_chapter_invalid_entries_do_not_hide_later_valid_items(tmp_path):
    source, http = source_fixture('dumanwu', tmp_path)
    add_more_marker(http)
    http.more['code'] = 200
    http.more['data'].insert(0, None)
    http.more['data'].insert(1, {'chaptername': 'broken', 'chapterid': '../outside'})
    comic = source.info(PAGE)
    assert comic is not None
    assert len(comic.books[0].vols) == 4
    assert comic.parse_warnings
    assert http.responses[-1].closed


def test_api_http_error_releases_response_and_returns_no_details(tmp_path, monkeypatch):
    source, _ = source_fixture('manhuafree', tmp_path)
    assert isinstance(source, ManhuafreeComic)
    response = FixtureResponse(BASE + '/api/manga/get', 'unavailable', status=503)
    monkeypatch.setattr(source.http, 'get', lambda *args, **kwargs: response)
    assert source._api_get('/api/manga/get') is None
    assert response.closed


def add_more_marker(http):
    root = etree.HTML(http.html)
    group = root.xpath('//div[@class="chapterlistload"]')[0]
    marker = etree.SubElement(group, 'div')
    marker.set('class', 'chaplist-more')
    http.html = etree.tostring(root, encoding='unicode')


@pytest.mark.parametrize('status', [200, 503])
def test_more_chapter_request_reports_failures_and_always_closes_response(tmp_path, status):
    source, http = source_fixture('dumanwu', tmp_path)
    add_more_marker(http)
    http.more_status = status
    comic = source.info(PAGE)
    assert comic is not None
    assert http.responses[-1].closed
    assert http.calls[-1][2]['timeout'] == 30
    if status == 503:
        assert len(comic.books[0].vols) == 2
        assert any('可能不完整' in warning for warning in comic.parse_warnings)
    else:
        assert len(comic.books[0].vols) == 4


def test_more_marker_is_scoped_to_its_group_and_duplicate_urls_are_merged(tmp_path):
    source, http = source_fixture('dumanwu', tmp_path)
    root = etree.HTML(http.html)
    group = root.xpath('//div[@class="chapterlistload"]')[0]
    group.getparent().append(copy.deepcopy(group))
    etree.SubElement(group, 'div').set('class', 'chaplist-more')
    http.html = etree.tostring(root, encoding='unicode')
    http.more['data'].append(copy.deepcopy(http.more['data'][0]))
    comic = source.info(PAGE)
    assert comic is not None
    assert len([call for call in http.calls if call[0] == 'POST']) == 1
    assert [len(book.vols) for book in comic.books] == [4, 2]
    assert any('重复' in warning for warning in comic.parse_warnings)


@pytest.mark.parametrize(
    'value',
    [
        None,
        '',
        '#reader',
        'javascript:void(0)',
        'data:text/html,bad',
        'https://user:pass@example.test/1',
        'https://example.test:99999/1',
    ],
)
def test_non_downloadable_links_are_rejected(value):
    assert http_url(value, PAGE) is None


def test_deduplication_preserves_order_and_same_url_in_different_groups():
    comic = Comic()
    for name in ('正篇', '单行本'):
        book = ComicBook()
        book.name = name
        book.vols = [
            ComicVolume('第一话', '/1#reader'),
            ComicVolume('第二话', '/2'),
            ComicVolume('重复第一话', BASE + '/1'),
        ]
        comic.books.append(book)
    finalize_comic_info(comic, PAGE)
    assert [[volume.name for volume in book.vols] for book in comic.books] == [
        ['第一话', '第二话'],
        ['第一话', '第二话'],
    ]
    first_warnings = list(comic.parse_warnings)
    finalize_comic_info(comic, PAGE)
    assert comic.parse_warnings == first_warnings
