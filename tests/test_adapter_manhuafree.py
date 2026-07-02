"""Unit tests for the ManhuafreeComic adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.sources.adapters.manhuafree import (
    API_SUCCESS_CODE,
    DEFAULT_IMG_HOST,
    IMG_HOST_LINE_2,
    IMG_HOST_LINE_2_VALUE,
    ManhuafreeComic,
)


@pytest.fixture
def mock_http():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def manhuafree(tmp_path, mock_http, mock_driver):
    """Create a ManhuafreeComic instance with config loaded."""
    with patch.object(ManhuafreeComic, 'load_config'):
        source = ManhuafreeComic(str(tmp_path), mock_http, mock_driver)
        source.config = {
            'api_base_url': 'https://api.manhuafree.com',
            'search_xpath': '//div[@class="item"]',
            'search_extract': {'name': './@title', 'url': './@href'},
            'info_mid_attr': '//@data-mid',
        }
        return source


# ---------------------------------------------------------------------------
# _api_get
# ---------------------------------------------------------------------------
class TestManhuafreeApiGet:
    def test_api_get_success(self, manhuafree):
        resp = MagicMock()
        resp.json.return_value = {'status': True, 'data': {'title': 'Test'}}
        resp.raise_for_status = MagicMock()
        manhuafree.http.get.return_value = resp

        result = manhuafree._api_get('/api/manga/get', params={'mid': '123'})

        assert result == {'status': True, 'data': {'title': 'Test'}}
        manhuafree.http.get.assert_called_once()

    def test_api_get_failure(self, manhuafree):
        manhuafree.http.get.side_effect = requests.exceptions.ConnectionError('fail')

        result = manhuafree._api_get('/api/manga/get')

        assert result is None


# ---------------------------------------------------------------------------
# _extract_mid
# ---------------------------------------------------------------------------
class TestManhuafreeExtractMid:
    def test_extract_mid_success(self, manhuafree):

        html = '<html><body><div data-mid="12345">content</div></body></html>'
        root = etree.HTML(html)
        manhuafree.config['info_mid_attr'] = '//@data-mid'

        result = manhuafree._extract_mid(root, 'https://example.com')

        assert result == '12345'

    def test_extract_mid_not_found(self, manhuafree):

        html = '<html><body><div>no mid</div></body></html>'
        root = etree.HTML(html)
        manhuafree.config['info_mid_attr'] = '//@data-mid'

        result = manhuafree._extract_mid(root, 'https://example.com')

        assert result is None


# ---------------------------------------------------------------------------
# _extract_chapter_ids
# ---------------------------------------------------------------------------
class TestManhuafreeExtractChapterIds:
    def test_extract_from_attributes(self, manhuafree):

        html = '<html><body><div data-ms="100" data-cs="200">content</div></body></html>'
        root = etree.HTML(html)

        mid, chapter_id = manhuafree._extract_chapter_ids(root, 'https://example.com')

        assert mid == '100'
        assert chapter_id == '200'

    def test_extract_from_regex_fallback(self, manhuafree):

        html = '<html><body><script>var x = 1; data-ms="300" data-cs="400"</script></body></html>'
        root = etree.HTML(html)

        mid, chapter_id = manhuafree._extract_chapter_ids(root, 'https://example.com')

        assert mid == '300'
        assert chapter_id == '400'

    def test_extract_returns_none_when_not_found(self, manhuafree):

        html = '<html><body><div>no data</div></body></html>'
        root = etree.HTML(html)

        mid, chapter_id = manhuafree._extract_chapter_ids(root, 'https://example.com')

        assert mid is None
        assert chapter_id is None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class TestManhuafreeSearch:
    def test_search_returns_results(self, manhuafree):
        html = """
        <html><body>
        <div class="item" title="猎人" href="/manga/hunter"></div>
        <div class="item" title="海贼王" href="/manga/onepiece"></div>
        </body></html>
        """
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            manhuafree.config['search_xpath'] = '//div[@class="item"]'
            manhuafree.config['search_extract'] = {'name': './@title', 'url': './@href'}

            results = manhuafree.search('猎人')

        assert len(results) == 2
        assert results[0].name == '猎人'
        assert results[0].url == 'https://manhuafree.com/manga/hunter'

    def test_search_returns_empty_when_parse_fails(self, manhuafree):
        with patch.object(manhuafree, '__parse_html__', return_value=None):
            results = manhuafree.search('test')

        assert results == []

    def test_search_returns_empty_when_no_items(self, manhuafree):
        html = '<html><body><div>nothing</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            manhuafree.config['search_xpath'] = '//div[@class="item"]'
            manhuafree.config['search_extract'] = {'name': './@title', 'url': './@href'}

            results = manhuafree.search('test')

        assert results == []

    def test_search_handles_exception(self, manhuafree):
        with patch.object(
            manhuafree, '__parse_html__', side_effect=RuntimeError('fail')
        ):
            results = manhuafree.search('test')

        assert results == []


# ---------------------------------------------------------------------------
# _parse_search_item
# ---------------------------------------------------------------------------
class TestManhuafreeParseSearchItem:
    def test_parse_search_item_success(self, manhuafree):
        item = {'name': '猎人', 'url': '/manga/hunter'}
        result = manhuafree._parse_search_item(item)

        assert result is not None
        assert result.name == '猎人'
        assert result.url == 'https://manhuafree.com/manga/hunter'

    def test_parse_search_item_absolute_url(self, manhuafree):
        item = {'name': '猎人', 'url': 'https://other.com/manga/hunter'}
        result = manhuafree._parse_search_item(item)

        assert result is not None
        assert result.url == 'https://other.com/manga/hunter'

    def test_parse_search_item_no_url(self, manhuafree):
        item = {'name': '猎人', 'url': ''}
        result = manhuafree._parse_search_item(item)

        assert result is None

    def test_parse_search_item_no_name(self, manhuafree):
        item = {'name': '', 'url': '/manga/hunter'}
        result = manhuafree._parse_search_item(item)

        assert result is not None
        assert result.name == '未知漫画'


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------
class TestManhuafreeInfo:
    def test_info_returns_comic(self, manhuafree):
        html = '<html><body><div data-mid="123">content</div></body></html>'

        api_response = {
            'status': True,
            'code': API_SUCCESS_CODE,
            'data': {
                'title': '猎人',
                'status': '1',
                'desc': '好看的漫画',
                'slug': 'hunter',
                'chapters': [
                    {'attributes': {'title': '第1话', 'slug': 'ch-1'}},
                    {'attributes': {'title': '第2话', 'slug': 'ch-2'}},
                ],
            },
        }

        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(manhuafree, '_api_get', return_value=api_response):
                result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is not None
        assert result.name == '猎人'
        assert len(result.metadata) == 2
        assert result.metadata[0] == {'k': '状态', 'v': '连载'}
        assert result.metadata[1] == {'k': '简介', 'v': '好看的漫画'}
        assert len(result.books) == 1
        assert len(result.books[0].vols) == 2

    def test_info_returns_none_when_parse_fails(self, manhuafree):
        with patch.object(manhuafree, '__parse_html__', return_value=None):
            result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is None

    def test_info_returns_none_when_no_mid(self, manhuafree):
        html = '<html><body><div>no mid</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is None

    def test_info_returns_none_when_api_fails(self, manhuafree):
        html = '<html><body><div data-mid="123">content</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(manhuafree, '_api_get', return_value=None):
                result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is None

    def test_info_returns_none_when_api_error_status(self, manhuafree):
        html = '<html><body><div data-mid="123">content</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(
                manhuafree, '_api_get', return_value={'status': False, 'code': 500}
            ):
                result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is None

    def test_info_returns_none_when_api_data_empty(self, manhuafree):
        html = '<html><body><div data-mid="123">content</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(
                manhuafree,
                '_api_get',
                return_value={'status': True, 'code': API_SUCCESS_CODE, 'data': {}},
            ):
                result = manhuafree.info('https://manhuafree.com/manga/hunter')

        assert result is None


# ---------------------------------------------------------------------------
# _build_comic
# ---------------------------------------------------------------------------
class TestManhuafreeBuildComic:
    def test_build_comic_with_chapters(self, manhuafree):
        manga = {
            'title': '猎人',
            'status': '0',
            'desc': '经典漫画',
            'slug': 'hunter',
            'chapters': [
                {'attributes': {'title': '第1话', 'slug': 'ch-1'}},
                {'attributes': {'title': '第2话', 'slug': 'ch-2'}},
            ],
        }

        result = manhuafree._build_comic(manga, 'https://manhuafree.com/manga/hunter')

        assert result.name == '猎人'
        assert result.metadata[0] == {'k': '状态', 'v': '完结'}
        assert len(result.books) == 1
        # Chapters are reversed
        assert result.books[0].vols[0].name == '第2话'
        assert result.books[0].vols[1].name == '第1话'

    def test_build_comic_empty_chapters(self, manhuafree):
        manga = {'title': '猎人', 'status': '', 'slug': 'hunter', 'chapters': []}

        result = manhuafree._build_comic(manga, 'https://manhuafree.com/manga/hunter')

        assert result.name == '猎人'
        assert len(result.books) == 0

    def test_build_comic_missing_title(self, manhuafree):
        manga = {'slug': 'hunter', 'chapters': []}

        result = manhuafree._build_comic(manga, 'https://manhuafree.com/manga/hunter')

        assert result.name == '未知漫画'


# ---------------------------------------------------------------------------
# __parse_imgs__
# ---------------------------------------------------------------------------
class TestManhuafreeParseImgs:
    def test_parse_imgs_returns_urls(self, manhuafree):
        html = '<html><body><div data-ms="100" data-cs="200">content</div></body></html>'
        api_response = {
            'status': True,
            'data': {
                'info': {
                    'images': {
                        'images': [
                            {'url': '/img/1.jpg', 'order': 1},
                            {'url': '/img/2.jpg', 'order': 2},
                        ],
                        'line': 3,
                    }
                }
            },
        }

        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(manhuafree, '_api_get', return_value=api_response):
                result = manhuafree.parse_images(
                    'https://manhuafree.com/manga/hunter/ch-1'
                )

        assert len(result) == 2
        assert result[0] == f'{DEFAULT_IMG_HOST}/img/1.jpg'
        assert result[1] == f'{DEFAULT_IMG_HOST}/img/2.jpg'

    def test_parse_imgs_line_2_uses_alternate_host(self, manhuafree):
        html = '<html><body><div data-ms="100" data-cs="200">content</div></body></html>'
        api_response = {
            'status': True,
            'data': {
                'info': {
                    'images': {
                        'images': [{'url': '/img/1.jpg', 'order': 1}],
                        'line': IMG_HOST_LINE_2_VALUE,
                    }
                }
            },
        }

        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(manhuafree, '_api_get', return_value=api_response):
                result = manhuafree.parse_images(
                    'https://manhuafree.com/manga/hunter/ch-1'
                )

        assert len(result) == 1
        assert result[0] == f'{IMG_HOST_LINE_2}/img/1.jpg'

    def test_parse_imgs_returns_empty_when_parse_fails(self, manhuafree):
        with patch.object(manhuafree, '__parse_html__', return_value=None):
            result = manhuafree.parse_images(
                'https://manhuafree.com/manga/hunter/ch-1'
            )

        assert result == []

    def test_parse_imgs_returns_empty_when_no_chapter_ids(self, manhuafree):
        html = '<html><body><div>no ids</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            result = manhuafree.parse_images(
                'https://manhuafree.com/manga/hunter/ch-1'
            )

        assert result == []

    def test_parse_imgs_returns_empty_when_api_fails(self, manhuafree):
        html = '<html><body><div data-ms="100" data-cs="200">content</div></body></html>'
        with patch.object(manhuafree, '__parse_html__') as mock_parse:

            mock_parse.return_value = etree.HTML(html)
            with patch.object(manhuafree, '_api_get', return_value=None):
                result = manhuafree.parse_images(
                    'https://manhuafree.com/manga/hunter/ch-1'
                )

        assert result == []

    def test_parse_imgs_handles_exception(self, manhuafree):
        with patch.object(
            manhuafree, '__parse_html__', side_effect=RuntimeError('fail')
        ):
            result = manhuafree.parse_images(
                'https://manhuafree.com/manga/hunter/ch-1'
            )

        assert result == []


# ---------------------------------------------------------------------------
# _extract_img_urls
# ---------------------------------------------------------------------------
class TestManhuafreeExtractImgUrls:
    def test_dict_format_with_line(self, manhuafree):
        chapter_data = {
            'images': {
                'images': [
                    {'url': '/img/a.jpg', 'order': 2},
                    {'url': '/img/b.jpg', 'order': 1},
                ],
                'line': 3,
            }
        }

        result = manhuafree._extract_img_urls(chapter_data)

        # Sorted by order
        assert result[0] == f'{DEFAULT_IMG_HOST}/img/b.jpg'
        assert result[1] == f'{DEFAULT_IMG_HOST}/img/a.jpg'

    def test_list_format_fallback(self, manhuafree):
        chapter_data = {
            'images': [
                {'url': '/img/a.jpg', 'order': 1},
            ],
            'line': 3,
        }

        result = manhuafree._extract_img_urls(chapter_data)

        assert result == [f'{DEFAULT_IMG_HOST}/img/a.jpg']

    def test_absolute_url_passthrough(self, manhuafree):
        chapter_data = {
            'images': {
                'images': [{'url': 'https://cdn.example.com/img.jpg', 'order': 1}],
                'line': 3,
            }
        }

        result = manhuafree._extract_img_urls(chapter_data)

        assert result == ['https://cdn.example.com/img.jpg']

    def test_empty_url_skipped(self, manhuafree):
        chapter_data = {
            'images': {
                'images': [{'url': '', 'order': 1}, {'url': '/img/a.jpg', 'order': 2}],
                'line': 3,
            }
        }

        result = manhuafree._extract_img_urls(chapter_data)

        assert len(result) == 1
        assert result[0] == f'{DEFAULT_IMG_HOST}/img/a.jpg'
