"""Unit tests for the MaoflyComic adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic, ComicBook
from downloader.sources.adapters.maofly import MaoflyComic


@pytest.fixture
def mock_http():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def maofly(tmp_path, mock_http, mock_driver):
    """Create a MaoflyComic instance with mocked JS init."""
    resp = MagicMock()
    resp.text = 'var LZString = {};'
    resp.raise_for_status = MagicMock()
    mock_http.get.return_value = resp
    source = MaoflyComic(str(tmp_path), mock_http, mock_driver)
    return source


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------
class TestMaoflyInit:
    def test_successful_js_init(self, tmp_path, mock_http, mock_driver):
        resp = MagicMock()
        resp.text = 'var LZString = { decompress: function(){} };'
        resp.raise_for_status = MagicMock()
        mock_http.get.return_value = resp

        source = MaoflyComic(str(tmp_path), mock_http, mock_driver)

        assert source.jsstring == 'var LZString = { decompress: function(){} };'
        mock_http.get.assert_called_once()

    def test_js_init_request_exception(self, tmp_path, mock_http, mock_driver):
        mock_http.get.side_effect = requests.exceptions.ConnectionError('timeout')

        source = MaoflyComic(str(tmp_path), mock_http, mock_driver)

        assert source.jsstring == ''

    def test_js_init_unexpected_exception(self, tmp_path, mock_http, mock_driver):
        mock_http.get.side_effect = RuntimeError('unexpected')

        source = MaoflyComic(str(tmp_path), mock_http, mock_driver)

        assert source.jsstring == ''


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class TestMaoflySearch:
    def test_search_returns_results(self, maofly):
        html = """
        <html><body>
        <div class="comic-main-section">
            <div class="text-muted">共 2 条结果</div>
            <div class="comicbook-index">
                <a href="/comic/123" title="猎人">猎人</a>
                <div><a>作者A</a></div>
            </div>
            <div class="comicbook-index">
                <a href="https://www.maofly.com/comic/456" title="猎人X">猎人X</a>
                <div><a>作者B</a></div>
            </div>
        </div>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            root = etree.HTML(html)
            mock_parse.return_value = root

            results = maofly.search('猎人')

        assert len(results) == 2
        assert results[0].name == '猎人'
        assert results[0].url == 'https://www.maofly.com/comic/123'
        assert results[0].author == '作者A'
        assert results[1].url == 'https://www.maofly.com/comic/456'

    def test_search_returns_empty_when_parse_fails(self, maofly):
        with patch.object(maofly, '__parse_html__', return_value=None):
            results = maofly.search('test')

        assert results == []

    def test_search_returns_empty_when_no_main_section(self, maofly):
        html = '<html><body><div>empty page</div></body></html>'
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = maofly.search('test')

        assert results == []

    def test_search_handles_exception(self, maofly):
        with patch.object(maofly, '__parse_html__', side_effect=RuntimeError('fail')):
            results = maofly.search('test')

        assert results == []

    def test_search_skips_entries_without_url(self, maofly):
        html = """
        <html><body>
        <div class="comic-main-section">
            <div class="comicbook-index">
                <a title="猎人">猎人</a>
                <div><a>作者A</a></div>
            </div>
        </div>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            results = maofly.search('猎人')

        assert results == []


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
class TestMaoflyInfo:
    def test_info_returns_comic_with_books(self, maofly):
        html = """
        <html><body>
        <td class="comic-titles">漫画名称</td>
        <table class="comic-meta-data-table"><tbody>
            <tr><th>作者</th><td><a>张三</a></td></tr>
            <tr><th>状态</th><td>连载中</td></tr>
        </tbody></table>
        <div id="comic-book-list">
            <div>
                <div><div><h2>正篇</h2></div></div>
                <ol>
                    <li><a title="第1话" href="/comic/123/1">第1话</a></li>
                    <li><a title="第2话" href="/comic/123/2">第2话</a></li>
                </ol>
            </div>
        </div>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = maofly.info('https://www.maofly.com/comic/123')

        assert result is not None
        assert result.name == '漫画名称'
        assert result.url == 'https://www.maofly.com/comic/123'
        assert len(result.metadata) == 2
        assert result.metadata[0] == {'k': '作者', 'v': '张三'}
        assert result.metadata[1] == {'k': '状态', 'v': '连载中'}
        assert len(result.books) == 1
        assert result.books[0].name == '正篇'
        assert len(result.books[0].vols) == 2
        assert result.books[0].vols[0].name == '第1话'

    def test_info_returns_none_when_parse_fails(self, maofly):
        with patch.object(maofly, '__parse_html__', return_value=None):
            result = maofly.info('https://www.maofly.com/comic/123')

        assert result is None

    def test_info_returns_none_when_no_title(self, maofly):
        html = '<html><body><div>no comic titles</div></body></html>'
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = maofly.info('https://www.maofly.com/comic/123')

        assert result is None


# ---------------------------------------------------------------------------
# __parse_imgs__
# ---------------------------------------------------------------------------
class TestMaoflyParseImgs:
    def test_parse_imgs_returns_processed_urls(self, maofly):
        page_html = """
        <html><body>
        <script>let img_data = "encoded_data_here"</script>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(page_html)
            maofly.jsstring = 'var LZString = {};'
            maofly.driver.execute_script.return_value = '/comic/1.jpg,/comic/2.jpg'

            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert len(result) == 2
        assert result[0] == 'https://mao.mhtupian.com/uploads/comic/1.jpg'
        assert result[1] == 'https://mao.mhtupian.com/uploads/comic/2.jpg'

    def test_parse_imgs_handles_absolute_urls(self, maofly):
        page_html = """
        <html><body>
        <script>let img_data = "encoded_data"</script>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(page_html)
            maofly.jsstring = 'var LZString = {};'
            maofly.driver.execute_script.return_value = (
                'https://cdn.example.com/img1.jpg,https://cdn.example.com/img2.jpg'
            )

            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert len(result) == 2
        assert result[0] == 'https://cdn.example.com/img1.jpg'

    def test_parse_imgs_returns_empty_when_no_img_data(self, maofly):
        page_html = '<html><body><script>var x = 1;</script></body></html>'
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(page_html)

            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert result == []

    def test_parse_imgs_returns_empty_when_parse_fails(self, maofly):
        with patch.object(maofly, '__parse_html__', return_value=None):
            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert result == []

    def test_parse_imgs_returns_empty_when_decode_fails(self, maofly):
        page_html = """
        <html><body>
        <script>let img_data = "encoded_data"</script>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(page_html)
            maofly.jsstring = 'var LZString = {};'
            maofly.driver.execute_script.return_value = None

            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert result == []

    def test_parse_imgs_returns_empty_when_jsstring_empty(self, maofly):
        page_html = """
        <html><body>
        <script>let img_data = "encoded_data"</script>
        </body></html>
        """
        with patch.object(maofly, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(page_html)
            maofly.jsstring = ''

            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert result == []

    def test_parse_imgs_handles_exception(self, maofly):
        with patch.object(
            maofly, '__parse_html__', side_effect=RuntimeError('fail')
        ):
            result = maofly.parse_images(
                'https://www.maofly.com/comic/123/1'
            )

        assert result == []


# ---------------------------------------------------------------------------
# _parse_comic_header
# ---------------------------------------------------------------------------
class TestMaoflyParseComicHeader:
    def test_parse_header_exception(self, maofly):

        root = etree.HTML('<html><body><td class="comic-titles"></td></body></html>')
        # text is None on the td node, will raise AttributeError
        result = maofly._parse_comic_header(root, 'https://example.com')
        # Should return None because .text.strip() fails
        assert result is None


# ---------------------------------------------------------------------------
# _append_metadata_row
# ---------------------------------------------------------------------------
class TestMaoflyAppendMetadata:
    def test_metadata_row_missing_key(self, maofly):


        comic = Comic()
        row = etree.HTML('<html><body><tr><th></th><td>value</td></tr></body></html>').xpath(
            '//tr'
        )[0]
        # Should not raise, just log warning
        maofly._append_metadata_row(comic, row)
        assert comic.metadata == []

    def test_metadata_row_with_link(self, maofly):


        comic = Comic()
        row_html = '<html><body><tr><th>作者</th><td><a>张三</a></td></tr></body></html>'
        row = etree.HTML(row_html).xpath('//tr')[0]
        maofly._append_metadata_row(comic, row)
        assert comic.metadata == [{'k': '作者', 'v': '张三'}]


# ---------------------------------------------------------------------------
# _append_book_volumes
# ---------------------------------------------------------------------------
class TestMaoflyAppendBookVolumes:
    def test_skips_volumes_without_title_or_href(self, maofly):


        book_html = """
        <div>
            <ol>
                <li><a href="/comic/1">Vol1</a></li>
                <li><a title="Vol2">Vol2</a></li>
            </ol>
        </div>
        """
        book = etree.HTML(book_html).xpath('//div')[0]
        comic_book = ComicBook()
        maofly._append_book_volumes(book, comic_book)
        # Only the first one has both title and href? Actually first has no title attr
        # Second has no href attr. So both should be skipped.
        assert len(comic_book.vols) == 0
