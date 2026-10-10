"""Unit tests for the DmzjComic adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic
from downloader.sources.adapters.dmzj import DmzjComic


@pytest.fixture
def mock_http():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    driver.implicitly_wait = MagicMock()
    return driver


@pytest.fixture
def dmzj(tmp_path, mock_http, mock_driver):
    """Create a DmzjComic instance."""
    with patch.object(DmzjComic, 'load_config'):
        source = DmzjComic(str(tmp_path), mock_http, mock_driver)
        source.config = {
            'search_js': 'return g_search_data;',
            'imgs_js': 'return imgs;',
        }
        return source


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class TestDmzjSearch:
    def test_search_returns_results(self, dmzj):
        resp = MagicMock()
        resp.text = 'var g_search_data = [];'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        search_results = [
            {
                'comic_url_raw': '//manhua.dmzj.com/hunter',
                'comic_name': '猎人',
                'comic_author': '富坚义博',
            },
            {
                'comic_url_raw': '//manhua.dmzj.com/onepiece',
                'comic_name': '海贼王',
                'comic_author': '尾田荣一郎',
            },
        ]
        with patch.object(dmzj, 'execute_js_safely', return_value=search_results):
            results = dmzj.search('猎人')

        assert len(results) == 2
        assert results[0].name == '猎人'
        assert results[0].url == 'http://manhua.dmzj.com/hunter'
        assert results[0].author == '富坚义博'
        assert results[1].name == '海贼王'

    def test_search_skips_non_dmzj_urls(self, dmzj):
        resp = MagicMock()
        resp.text = 'var g_search_data = [];'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        search_results = [
            {
                'comic_url_raw': '//other-site.com/hunter',
                'comic_name': '猎人',
                'comic_author': '富坚义博',
            },
        ]
        with patch.object(dmzj, 'execute_js_safely', return_value=search_results):
            results = dmzj.search('猎人')

        assert results == []

    def test_search_returns_empty_when_no_results(self, dmzj):
        resp = MagicMock()
        resp.text = 'var g_search_data = [];'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        with patch.object(dmzj, 'execute_js_safely', return_value=[]):
            results = dmzj.search('不存在')

        assert results == []

    def test_search_returns_empty_when_js_fails(self, dmzj):
        resp = MagicMock()
        resp.text = 'invalid js'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        with patch.object(dmzj, 'execute_js_safely', return_value=None):
            results = dmzj.search('猎人')

        assert results == []

    def test_search_returns_empty_on_request_error(self, dmzj):
        dmzj.http.get.side_effect = requests.exceptions.Timeout('timeout')

        results = dmzj.search('猎人')

        assert results == []

    def test_search_returns_empty_on_script_exception(self, dmzj):
        resp = MagicMock()
        resp.text = 'var g_search_data = [];'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        with patch.object(dmzj, 'execute_js_safely', side_effect=RuntimeError('js error')):
            results = dmzj.search('猎人')

        assert results == []

    def test_search_handles_missing_comic_url_raw(self, dmzj):
        resp = MagicMock()
        resp.text = 'var g_search_data = [];'
        resp.raise_for_status = MagicMock()
        dmzj.http.get.return_value = resp

        search_results = [
            {
                'comic_url_raw': '',
                'comic_name': '猎人',
                'comic_author': '富坚义博',
            },
        ]
        with patch.object(dmzj, 'execute_js_safely', return_value=search_results):
            results = dmzj.search('猎人')

        # url becomes 'http:' which doesn't start with base_url, so skipped
        assert results == []


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
class TestDmzjInfo:
    def test_info_returns_comic(self, dmzj):
        html = """
        <html><body>
        <span class="anim_title_text"><a><h1>猎人</h1></a></span>
        <div class="anim-main_list">
            <table><tr><th>作者</th><td><a>富坚义博</a></td></tr></table>
        </div>
        <div class="cartoon_online_border">
            <div class="tab-content">
                <ul class="list_con_li">
                    <li><a href="/hunter/1">第1话</a></li>
                    <li><a href="/hunter/2">第2话</a></li>
                </ul>
            </div>
        </div>
        </body></html>
        """
        with patch.object(dmzj, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = dmzj.info('http://manhua.dmzj.com/hunter')

        assert result is not None
        assert result.name == '猎人'
        assert result.url == 'http://manhua.dmzj.com/hunter'
        assert len(result.metadata) == 1
        assert result.metadata[0] == {'k': '作者', 'v': '富坚义博'}

    def test_info_returns_none_when_parse_fails(self, dmzj):
        with patch.object(dmzj, '__parse_html__', return_value=None):
            result = dmzj.info('http://manhua.dmzj.com/hunter')

        assert result is None

    def test_info_returns_none_when_no_name(self, dmzj):
        html = '<html><body><div>no title</div></body></html>'
        with patch.object(dmzj, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = dmzj.info('http://manhua.dmzj.com/hunter')

        assert result is None


# ---------------------------------------------------------------------------
# _parse_comic_header
# ---------------------------------------------------------------------------
class TestDmzjParseComicHeader:
    def test_parse_header_success(self, dmzj):

        html = """
        <html><body>
        <span class="anim_title_text"><a><h1>猎人</h1></a></span>
        </body></html>
        """
        root = etree.HTML(html)

        result = dmzj._parse_comic_header(root, 'http://manhua.dmzj.com/hunter')

        assert result is not None
        assert result.name == '猎人'

    def test_parse_header_fallback_path(self, dmzj):

        html = """
        <html><body>
        <div class="comic_deCon_new">
            <div class="comic_deCon_left"><h1><a>海贼王</a></h1></div>
        </div>
        </body></html>
        """
        root = etree.HTML(html)

        result = dmzj._parse_comic_header(root, 'http://manhua.dmzj.com/onepiece')

        assert result is not None
        assert result.name == '海贼王'

    def test_parse_header_returns_none_when_no_name(self, dmzj):

        html = '<html><body><div>nothing</div></body></html>'
        root = etree.HTML(html)

        result = dmzj._parse_comic_header(root, 'http://manhua.dmzj.com/test')

        assert result is None


# ---------------------------------------------------------------------------
# _append_metadata
# ---------------------------------------------------------------------------
class TestDmzjAppendMetadata:
    def test_append_metadata(self, dmzj):


        html = """
        <html><body>
        <div class="anim-main_list">
            <table>
                <tr><th>作者</th><td><a>富坚义博</a></td></tr>
                <tr><th>状态</th><td><a>连载</a></td></tr>
                <tr><th>无链接</th><td>纯文本</td></tr>
            </table>
        </div>
        </body></html>
        """
        root = etree.HTML(html)
        comic = Comic()

        dmzj._append_metadata(root, comic)

        assert len(comic.metadata) == 2
        assert comic.metadata[0] == {'k': '作者', 'v': '富坚义博'}
        assert comic.metadata[1] == {'k': '状态', 'v': '连载'}


# ---------------------------------------------------------------------------
# _find_book_nodes
# ---------------------------------------------------------------------------
class TestDmzjFindBookNodes:
    def test_find_book_nodes_first_xpath(self, dmzj):

        html = """
        <html><body>
        <div class="cartoon_online_border">
            <div class="tab-content">
                <ul class="list_con_li">
                    <li><a href="/1">第1话</a></li>
                </ul>
            </div>
        </div>
        </body></html>
        """
        root = etree.HTML(html)
        nodes, is_direct = dmzj._find_book_nodes(root, 'http://example.com')

        assert len(nodes) > 0
        assert is_direct is False

    def test_find_book_nodes_returns_empty_on_no_match(self, dmzj):

        html = '<html><body><div>nothing</div></body></html>'
        root = etree.HTML(html)
        nodes, is_direct = dmzj._find_book_nodes(root, 'http://example.com')

        assert nodes == []
        assert is_direct is False


# ---------------------------------------------------------------------------
# _build_direct_chapter_book
# ---------------------------------------------------------------------------
class TestDmzjBuildDirectChapterBook:
    def test_build_direct_chapter(self, dmzj):

        html = '<li><a href="/hunter/1">第1话</a></li>'
        book = etree.HTML(f'<html><body>{html}</body></html>').xpath('//li')[0]

        result = dmzj._build_direct_chapter_book(book, 'http://manhua.dmzj.com/hunter')

        assert result.name == '第1话'
        assert len(result.vols) == 1
        assert result.vols[0].url == 'http://manhua.dmzj.com/hunter/1'

    def test_build_direct_chapter_absolute_url(self, dmzj):

        html = '<li><a href="http://other.com/1">第1话</a></li>'
        book = etree.HTML(f'<html><body>{html}</body></html>').xpath('//li')[0]

        result = dmzj._build_direct_chapter_book(book, 'http://manhua.dmzj.com/hunter')

        assert result.vols[0].url == 'http://other.com/1'


# ---------------------------------------------------------------------------
# _build_grouped_book
# ---------------------------------------------------------------------------
class TestDmzjBuildGroupedBook:
    def test_build_grouped_book_with_title(self, dmzj):


        html = """
        <html><body>
        <div class="photo_part">
            <h2>正篇</h2>
        </div>
        </body></html>
        """
        root = etree.HTML(html)
        book_node = root.xpath('//div[contains(@class,"photo_part")]')[0]
        comic = Comic()

        result = dmzj._build_grouped_book(book_node, comic, 'http://example.com')

        assert result.name == '正篇'


# ---------------------------------------------------------------------------
# __parse_imgs__
# ---------------------------------------------------------------------------
class TestDmzjParseImgs:
    def test_parse_imgs_returns_list(self, dmzj):
        dmzj.config['imgs_js'] = 'return imgs;'

        with patch.object(
            dmzj, 'execute_js_safely', return_value=['https://img.example.com/1.jpg']
        ):
            result = dmzj.parse_images('http://manhua.dmzj.com/hunter/1')

        assert result == ['https://img.example.com/1.jpg']

    def test_parse_imgs_returns_empty_on_none(self, dmzj):
        dmzj.config['imgs_js'] = 'return imgs;'

        with patch.object(dmzj, 'execute_js_safely', return_value=None):
            result = dmzj.parse_images('http://manhua.dmzj.com/hunter/1')

        assert result == []

    def test_parse_imgs_returns_empty_on_non_list(self, dmzj):
        dmzj.config['imgs_js'] = 'return imgs;'

        with patch.object(dmzj, 'execute_js_safely', return_value='not a list'):
            result = dmzj.parse_images('http://manhua.dmzj.com/hunter/1')

        assert result == []

    def test_parse_imgs_handles_exception(self, dmzj):
        dmzj.driver.get.side_effect = RuntimeError('driver error')

        result = dmzj.parse_images('http://manhua.dmzj.com/hunter/1')

        assert result == []
