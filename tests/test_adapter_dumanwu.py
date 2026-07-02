"""Unit tests for the DumanwuComic adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic, ComicBook
from downloader.sources.adapters.dumanwu import DumanwuComic


@pytest.fixture
def mock_http():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    driver.execute_script = MagicMock(return_value=0)
    driver.find_elements = MagicMock(return_value=[])
    return driver


@pytest.fixture
def dumanwu(tmp_path, mock_http, mock_driver):
    """Create a DumanwuComic instance."""
    source = DumanwuComic(str(tmp_path), mock_http, mock_driver)
    return source


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class TestDumanwuSearch:
    def test_search_returns_results(self, dumanwu):
        html = """
        <html><body>
        <div class="view-item">
            <div class="item-title"><span><font>漫画</font><font>2</font></span></div>
            <div class="itemnar">
                <p><a href="/comic/123" title="猎人">猎人</a></p>
            </div>
            <div class="itemnar">
                <p><a href="/comic/456" title="海贼王">海贼王</a></p>
            </div>
        </div>
        </body></html>
        """
        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = dumanwu.search('猎人')

        assert len(results) == 2
        assert results[0].name == '猎人'
        assert results[0].url == 'https://www.dumanwu.com/comic/123'
        assert results[1].name == '海贼王'

    def test_search_returns_empty_when_parse_fails(self, dumanwu):
        with patch.object(dumanwu, '__parse_html__', return_value=None):
            results = dumanwu.search('test')

        assert results == []

    def test_search_returns_empty_when_no_view_item(self, dumanwu):
        html = '<html><body><div>empty page</div></body></html>'
        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = dumanwu.search('test')

        assert results == []

    def test_search_handles_exception(self, dumanwu):
        with patch.object(
            dumanwu, '__parse_html__', side_effect=RuntimeError('fail')
        ):
            results = dumanwu.search('test')

        assert results == []

    def test_search_skips_entry_without_url(self, dumanwu):
        html = """
        <html><body>
        <div class="view-item">
            <div class="itemnar">
                <p><a title="猎人">猎人</a></p>
            </div>
        </div>
        </body></html>
        """
        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = dumanwu.search('猎人')

        assert results == []


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
class TestDumanwuInfo:
    def test_info_returns_comic(self, dumanwu):
        html = """
        <html><body>
        <div class="detinfo">
            <h1 class="name_mh">漫画名称</h1>
            <p><span>作者：张三</span></p>
            <p><span>状态：连载</span></p>
        </div>
        <div class="chapterlistload">
            <ul>
                <a href="/comic/123/1"><li>第1话</li></a>
                <a href="/comic/123/2"><li>第2话</li></a>
            </ul>
            <div class="chaplist-more">more</div>
        </div>
        </body></html>
        """
        # Mock the more chapters response
        more_response = MagicMock()
        more_response.json.return_value = {'code': '200', 'data': []}
        more_response.raise_for_status = MagicMock()
        dumanwu.http.post.return_value = more_response

        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = dumanwu.info('https://www.dumanwu.com/comic123')

        assert result is not None
        assert result.name == '漫画名称'
        assert len(result.metadata) == 2
        assert result.metadata[0] == {'k': '作者', 'v': '张三'}

    def test_info_returns_none_when_parse_fails(self, dumanwu):
        with patch.object(dumanwu, '__parse_html__', return_value=None):
            result = dumanwu.info('https://www.dumanwu.com/comic123')

        assert result is None

    def test_info_returns_none_when_no_detinfo(self, dumanwu):
        html = '<html><body><div>no info</div></body></html>'
        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = dumanwu.info('https://www.dumanwu.com/comic123')

        assert result is None

    def test_info_returns_none_when_no_name(self, dumanwu):
        html = '<html><body><div class="detinfo"><h1>not_right_class</h1></div></body></html>'
        with patch.object(dumanwu, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = dumanwu.info('https://www.dumanwu.com/comic123')

        assert result is None


# ---------------------------------------------------------------------------
# _append_more_chapters
# ---------------------------------------------------------------------------
class TestDumanwuAppendMoreChapters:
    def test_append_more_chapters_success(self, dumanwu):


        html = """
        <div class="chapterlistload">
            <ul></ul>
            <div class="chaplist-more">more</div>
        </div>
        """
        book_node = etree.HTML(html).xpath('//div[contains(@class,"chapterlistload")]')[0]
        comic_book = ComicBook()
        comic_book.name = '章节列表1'

        more_response = MagicMock()
        more_response.json.return_value = {
            'code': '200',
            'data': [
                {'chaptername': '第3话', 'chapterid': '3'},
                {'chaptername': '第4话', 'chapterid': '4'},
            ],
        }
        more_response.raise_for_status = MagicMock()
        dumanwu.http.post.return_value = more_response

        dumanwu._append_more_chapters(book_node, comic_book, 'https://www.dumanwu.com/comic123')

        assert len(comic_book.vols) == 2
        assert comic_book.vols[0].name == '第3话'
        assert comic_book.vols[1].name == '第4话'

    def test_append_more_chapters_request_error(self, dumanwu):


        html = """
        <div class="chapterlistload">
            <ul></ul>
            <div class="chaplist-more">more</div>
        </div>
        """
        book_node = etree.HTML(html).xpath('//div[contains(@class,"chapterlistload")]')[0]
        comic_book = ComicBook()
        comic_book.name = '章节列表1'

        dumanwu.http.post.side_effect = requests.exceptions.Timeout('timeout')

        dumanwu._append_more_chapters(book_node, comic_book, 'https://www.dumanwu.com/comic123')

        assert len(comic_book.vols) == 0

    def test_append_more_chapters_json_error(self, dumanwu):


        html = """
        <div class="chapterlistload">
            <ul></ul>
            <div class="chaplist-more">more</div>
        </div>
        """
        book_node = etree.HTML(html).xpath('//div[contains(@class,"chapterlistload")]')[0]
        comic_book = ComicBook()
        comic_book.name = '章节列表1'

        more_response = MagicMock()
        more_response.raise_for_status = MagicMock()
        more_response.json.side_effect = json.JSONDecodeError('fail', '', 0)
        more_response.text = 'invalid json'
        dumanwu.http.post.return_value = more_response

        dumanwu._append_more_chapters(book_node, comic_book, 'https://www.dumanwu.com/comic123')

        assert len(comic_book.vols) == 0

    def test_append_more_chapter_response_non_200(self, dumanwu):

        comic_book = ComicBook()
        comic_book.name = '章节列表1'

        dumanwu._append_more_chapter_response(
            comic_book, 'comic123', {'code': '500', 'msg': 'server error'}
        )

        assert len(comic_book.vols) == 0

    def test_append_more_chapter_response_empty_data(self, dumanwu):

        comic_book = ComicBook()
        comic_book.name = '章节列表1'

        dumanwu._append_more_chapter_response(comic_book, 'comic123', {'code': '200', 'data': []})

        assert len(comic_book.vols) == 0


# ---------------------------------------------------------------------------
# _append_metadata_item
# ---------------------------------------------------------------------------
class TestDumanwuAppendMetadata:
    def test_metadata_empty_text(self, dumanwu):


        comic = Comic()
        meta = etree.HTML('<html><body><span></span></body></html>').xpath('//span')[0]
        dumanwu._append_metadata_item(comic, meta)
        assert comic.metadata == []

    def test_metadata_invalid_format(self, dumanwu):


        comic = Comic()
        meta = etree.HTML('<html><body><span>no_colon_here</span></body></html>').xpath('//span')[0]
        dumanwu._append_metadata_item(comic, meta)
        assert comic.metadata == []

    def test_metadata_valid_pair(self, dumanwu):


        comic = Comic()
        meta = etree.HTML('<html><body><span>作者：张三</span></body></html>').xpath('//span')[0]
        dumanwu._append_metadata_item(comic, meta)
        assert comic.metadata == [{'k': '作者', 'v': '张三'}]


# ---------------------------------------------------------------------------
# _parse_comic_header
# ---------------------------------------------------------------------------
class TestDumanwuParseComicHeader:
    def test_parse_header_exception_on_missing_name(self, dumanwu):

        html = '<html><body><div class="detinfo"><h1>wrong class</h1></div></body></html>'
        root = etree.HTML(html)
        result = dumanwu._parse_comic_header(root, 'https://example.com')
        assert result is None
