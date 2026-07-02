"""Unit tests for the ManhuaguiComic adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic
from downloader.sources.adapters.manhuagui import ManhuaguiComic


@pytest.fixture
def mock_http():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    driver.implicitly_wait = MagicMock()
    driver.execute_script = MagicMock(return_value=True)
    return driver


@pytest.fixture
def manhuagui(tmp_path, mock_http, mock_driver):
    """Create a ManhuaguiComic instance."""
    with patch.object(ManhuaguiComic, 'load_config'):
        source = ManhuaguiComic(str(tmp_path), mock_http, mock_driver)
        source.config = {'imgs_js': 'return [];'}
        return source


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class TestManhuaguiSearch:
    def test_search_returns_results(self, manhuagui):
        html = """
        <html><body>
        <div class="book-result">
            <ul>
                <li>
                    <div><a href="/comic/123" title="猎人">猎人</a></div>
                    <div class="book-detail">
                        <dl><dd></dd><dd></dd><dd><span><a>富坚义博</a></span></dd></dl>
                    </div>
                </li>
                <li>
                    <div><a href="/comic/456" title="海贼王">海贼王</a></div>
                    <div class="book-detail">
                        <dl><dd></dd><dd></dd><dd><span><a>尾田荣一郎</a></span></dd></dl>
                    </div>
                </li>
            </ul>
        </div>
        </body></html>
        """
        with patch.object(manhuagui, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = manhuagui.search('猎人')

        assert len(results) == 2
        assert results[0].name == '猎人'
        assert results[0].url == 'https://www.manhuagui.com/comic/123'
        assert results[0].author == '富坚义博'
        assert results[1].name == '海贼王'
        assert results[1].author == '尾田荣一郎'

    def test_search_returns_empty_when_parse_fails(self, manhuagui):
        with patch.object(manhuagui, '__parse_html__', return_value=None):
            results = manhuagui.search('test')

        assert results == []

    def test_search_returns_empty_when_no_book_result(self, manhuagui):
        html = '<html><body><div>no results</div></body></html>'
        with patch.object(manhuagui, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = manhuagui.search('test')

        assert results == []

    def test_search_returns_empty_with_no_result_hint(self, manhuagui):
        html = """
        <html><body>
        <div class="no-result">没有找到相关的漫画</div>
        </body></html>
        """
        with patch.object(manhuagui, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = manhuagui.search('不存在')

        assert results == []


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
class TestManhuaguiInfo:
    def test_info_returns_comic_with_books(self, manhuagui):
        html = """
        <html><body>
        <div class="book-title"><h1>猎人</h1></div>
        <ul class="detail-list">
            <li><span><strong>作者：</strong><a>富坚义博</a></span></li>
        </ul>
        <div class="chapter-list">
            <h4><span>连载</span></h4>
            <ul>
                <li><a href="comic/123/1"><span>第1话</span></a></li>
                <li><a href="comic/123/2"><span>第2话</span></a></li>
            </ul>
        </div>
        </body></html>
        """
        with patch.object(manhuagui, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = manhuagui.info('https://www.manhuagui.com/comic/123')

        assert result is not None
        assert result.name == '猎人'
        assert result.url == 'https://www.manhuagui.com/comic/123'
        assert len(result.books) == 1
        assert len(result.books[0].vols) == 2

    def test_info_returns_none_when_parse_fails(self, manhuagui):
        with patch.object(manhuagui, '__parse_html__', return_value=None):
            result = manhuagui.info('https://www.manhuagui.com/comic/123')

        assert result is None

    def test_info_handles_missing_chapter_list(self, manhuagui):
        html = """
        <html><body>
        <div class="book-title"><h1>猎人</h1></div>
        <ul class="detail-list"></ul>
        </body></html>
        """
        with patch.object(manhuagui, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = manhuagui.info('https://www.manhuagui.com/comic/123')

        assert result is not None
        assert result.name == '猎人'
        assert result.books == []


# ---------------------------------------------------------------------------
# _parse_comic_header
# ---------------------------------------------------------------------------
class TestManhuaguiParseComicHeader:
    def test_parse_header_success(self, manhuagui):

        html = '<html><body><div class="book-title"><h1>猎人</h1></div></body></html>'
        root = etree.HTML(html)

        result = manhuagui._parse_comic_header(root, 'https://example.com')

        assert result is not None
        assert result.name == '猎人'
        assert result.url == 'https://example.com'


# ---------------------------------------------------------------------------
# _append_metadata
# ---------------------------------------------------------------------------
class TestManhuaguiAppendMetadata:
    def test_append_metadata_with_link(self, manhuagui):


        html = """
        <html><body>
        <ul class="detail-list">
            <li><span><strong>作者：</strong><a>富坚义博</a></span></li>
            <li><span><strong>类型：</strong><a>少年</a></span></li>
        </ul>
        </body></html>
        """
        root = etree.HTML(html)
        comic = Comic()

        manhuagui._append_metadata(root, comic)

        assert len(comic.metadata) == 2
        assert comic.metadata[0] == {'k': '作者：', 'v': '富坚义博'}
        assert comic.metadata[1] == {'k': '类型：', 'v': '少年'}

    def test_append_metadata_skips_items_without_link(self, manhuagui):


        html = """
        <html><body>
        <ul class="detail-list">
            <li><span><strong>状态：</strong></span></li>
        </ul>
        </body></html>
        """
        root = etree.HTML(html)
        comic = Comic()

        manhuagui._append_metadata(root, comic)

        assert comic.metadata == []


# ---------------------------------------------------------------------------
# _append_books
# ---------------------------------------------------------------------------
class TestManhuaguiAppendBooks:
    def test_append_books_with_volumes(self, manhuagui):


        html = """
        <html><body>
        <div class="chapter-list">
            <ul>
                <li><a href="comic/123/1"><span>第1话</span></a></li>
                <li><a href="comic/123/2"><span>第2话</span></a></li>
            </ul>
        </div>
        </body></html>
        """
        root = etree.HTML(html)
        comic = Comic()

        manhuagui._append_books(root, comic, 'https://www.manhuagui.com/comic/123')

        assert len(comic.books) == 1
        assert len(comic.books[0].vols) == 2
        # Volumes are reversed
        assert comic.books[0].vols[0].name == '第2话'
        assert comic.books[0].vols[1].name == '第1话'


# ---------------------------------------------------------------------------
# __parse_imgs__
# ---------------------------------------------------------------------------
class TestManhuaguiParseImgs:
    def test_parse_imgs_returns_list(self, manhuagui):
        manhuagui.driver.execute_script.side_effect = [True]  # pVars check
        manhuagui.config['imgs_js'] = 'return imgs;'

        with patch.object(manhuagui, 'execute_js_safely') as mock_exec:
            mock_exec.return_value = [
                'https://img.example.com/1.jpg',
                'https://img.example.com/2.jpg',
            ]
            # Need to mock WebDriverWait
            with patch(
                'downloader.sources.adapters.manhuagui.WebDriverWait'
            ) as mock_wait:
                mock_wait.return_value.until = MagicMock(return_value=True)
                result = manhuagui.parse_images(
                    'https://www.manhuagui.com/comic/123/1'
                )

        assert len(result) == 2
        assert result[0] == 'https://img.example.com/1.jpg'

    def test_parse_imgs_returns_empty_on_no_results(self, manhuagui):
        manhuagui.config['imgs_js'] = 'return imgs;'

        with patch.object(manhuagui, 'execute_js_safely', return_value=None), patch(
            'downloader.sources.adapters.manhuagui.WebDriverWait'
        ) as mock_wait:
            mock_wait.return_value.until = MagicMock(return_value=True)
            result = manhuagui.parse_images(
                'https://www.manhuagui.com/comic/123/1'
            )

        assert result == []

    def test_parse_imgs_handles_exception(self, manhuagui):
        manhuagui.driver.get.side_effect = RuntimeError('driver error')

        result = manhuagui.parse_images(
            'https://www.manhuagui.com/comic/123/1'
        )

        assert result == []

    def test_parse_imgs_filters_non_string_items(self, manhuagui):
        manhuagui.config['imgs_js'] = 'return imgs;'

        with (
            patch.object(
                manhuagui,
                'execute_js_safely',
                return_value=['https://img.example.com/1.jpg', 123, None],
            ),
            patch('downloader.sources.adapters.manhuagui.WebDriverWait') as mock_wait,
        ):
            mock_wait.return_value.until = MagicMock(return_value=True)
            result = manhuagui.parse_images(
                'https://www.manhuagui.com/comic/123/1'
            )

        assert result == ['https://img.example.com/1.jpg']

    def test_parse_imgs_returns_empty_for_non_list(self, manhuagui):
        manhuagui.config['imgs_js'] = 'return imgs;'

        with patch.object(manhuagui, 'execute_js_safely', return_value='not a list'), patch(
            'downloader.sources.adapters.manhuagui.WebDriverWait'
        ) as mock_wait:
            mock_wait.return_value.until = MagicMock(return_value=True)
            result = manhuagui.parse_images(
                'https://www.manhuagui.com/comic/123/1'
            )

        assert result == []
