from __future__ import annotations

import re
from urllib.parse import quote

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser.modes import REQUESTS_MODE
from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger

# 漫画状态码映射
STATUS_MAP = {'0': '完结', '1': '连载', '2': '暂停'}

# 图片服务器线路映射 (line 字段值 -> 主机)
IMG_HOST_LINE_2 = 'https://f40-1-4.g-mh.online'
IMG_HOST_LINE_2_VALUE = 2
DEFAULT_IMG_HOST = 'https://t40-1-4.g-mh.online'

# API 成功状态码
API_SUCCESS_CODE = 200


class ManhuafreeComic(ComicSource):
    name = 'GoDa漫画'
    base_url = 'https://manhuafree.com'
    browser_mode = REQUESTS_MODE
    download_interval = 2
    config_file = 'manhuafree.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True, *, profile=None):
        super().__init__(output_dir, http, driver, overwrite, profile=profile)

    def _api_get(self, path, params=None):
        """调用 API 并返回 JSON 数据，失败返回 None"""
        api_url = f'{self.config["api_base_url"]}{path}'
        try:
            resp = self.http.get(
                api_url,
                params=params,
                headers={'Referer': self.base_url, 'User-Agent': 'Mozilla/5.0'},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error('API 请求失败: {}, 错误: {}', api_url, e, exc_info=True)
            return None

    def _extract_mid(self, root, url):
        """从页面提取 data-mid 属性"""
        mid_nodes = root.xpath(self.config['info_mid_attr'])
        if not mid_nodes:
            logger.error('无法从页面提取 data-mid: {}', url)
            return None
        mid = str(mid_nodes[0]).strip()
        if not mid:
            logger.error('data-mid 为空: {}', url)
            return None
        return mid

    def _extract_chapter_ids(self, root, url):
        """从章节页面提取 data-ms (mid) 和 data-cs (chapter_id)"""
        raw_ms = root.xpath('//@data-ms')
        raw_cs = root.xpath('//@data-cs')
        if raw_ms and raw_cs:
            return str(raw_ms[0]).strip(), str(raw_cs[0]).strip()
        # 回退：从原始 HTML 中正则提取
        page_html = etree.tostring(root, encoding='unicode')
        ms_match = re.search(r'data-ms="(\d+)"', page_html)
        cs_match = re.search(r'data-cs="(\d+)"', page_html)
        if ms_match and cs_match:
            return ms_match.group(1), cs_match.group(1)
        logger.error('无法从页面提取 data-ms 或 data-cs: {}', url)
        return None, None

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/s/{quote(keyword)}'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error("搜索 '{}' 失败，无法获取或解析页面: {}", keyword, search_url)
                return arr

            items = self.parse_xpath_list(
                root, self.config['search_xpath'], self.config['search_extract']
            )
            if not items:
                logger.info(
                    "在 {} 搜索 '{}' 时未找到结果，可能无结果或页面结构变更.",
                    self.name,
                    keyword,
                )
                return arr

            for item in items:
                comic = self._parse_search_item(item)
                if comic:
                    arr.append(comic)
        except Exception as e:
            logger.error("在 {} 搜索 '{}' 期间发生错误: {}", self.name, keyword, e, exc_info=True)
            return arr
        logger.info("{} 搜索 '{}' 完成, 共找到 {} 条结果.", self.name, keyword, len(arr))
        return arr

    def _parse_search_item(self, item):
        """解析单个搜索结果"""
        try:
            url_part = item.get('url')
            if not url_part:
                logger.warning('解析到一个没有URL的漫画条目，已跳过。')
                return None
            comic = Comic()
            comic.url = self.base_url + url_part if url_part.startswith('/') else url_part
            name_text = item.get('name') or ''
            comic.name = name_text.strip() or '未知漫画'
            comic.author = ''
            logger.debug('找到漫画: {}, URL: {}', comic.name, comic.url)
            return comic
        except Exception as e:
            logger.error('解析漫画条目时出错: {}, 错误: {}', item, e, exc_info=True)
            return None

    def info(self, url):
        logger.info('开始获取 {} 动漫详细信息: {}', self.name, url)
        root = self.__parse_html__(url)
        if root is None:
            logger.error('获取动漫详细信息失败，无法获取或解析页面内容: {}', url)
            return None

        mid = self._extract_mid(root, url)
        if not mid:
            return None
        logger.debug('提取到 data-mid: {}', mid)

        data = self._api_get('/api/manga/get', params={'mid': mid})
        if data is None:
            return None

        if not data.get('status') and data.get('code') != API_SUCCESS_CODE:
            logger.error('API 返回错误状态')
            return None

        manga = data.get('data', {})
        if not manga:
            logger.error('API 返回数据为空')
            return None

        return self._build_comic(manga, url)

    def _build_comic(self, manga, url):
        """从 API 数据构建 Comic 对象"""
        comic = Comic()
        comic.url = url
        comic.name = manga.get('title', '').strip() or '未知漫画'
        comic.author = ''

        # 状态
        status_code = str(manga.get('status', ''))
        status_value = STATUS_MAP.get(status_code, status_code)
        if status_value:
            comic.metadata.append({'k': '状态', 'v': status_value})

        # 简介
        desc = manga.get('desc', '')
        if desc:
            comic.metadata.append({'k': '简介', 'v': desc.strip()})

        # 章节列表
        comic_book = ComicBook()
        comic_book.name = '连载'

        slug = manga.get('slug', '')
        chapters = manga.get('chapters', [])
        for chapter in chapters:
            attrs = chapter.get('attributes', {})
            ch_title = attrs.get('title', '').strip()
            ch_slug = attrs.get('slug', '')
            if ch_title and ch_slug and slug:
                ch_url = f'{self.base_url}/manga/{slug}/{ch_slug}'
                comic_book.vols.append(ComicVolume(ch_title, ch_url, comic_book.name))

        comic_book.vols.reverse()
        if comic_book.vols:
            comic.books.append(comic_book)
        else:
            logger.warning('章节列表不包含任何有效章节: {}', url)

        logger.info(
            '{} 动漫详细信息获取完成: {}, 共 {} 个章节.',
            self.name,
            comic.name,
            len(comic_book.vols),
        )
        return comic

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片列表: {}', self.name, url)
        try:
            root = self.__parse_html__(url)
            if root is None:
                logger.error('解析图片页面失败，无法获取或解析页面: {}', url)
                return []

            mid, chapter_id = self._extract_chapter_ids(root, url)
            if not mid or not chapter_id:
                return []
            logger.debug('提取到 data-ms={}, data-cs={}', mid, chapter_id)

            data = self._api_get('/api/chapter/getinfo', params={'m': mid, 'c': chapter_id})
            if data is None or not data.get('status'):
                logger.error('章节 API 返回错误')
                return []

            chapter_data = data.get('data', {}).get('info', {})
            if not chapter_data:
                logger.error('章节 API 返回数据为空')
                return []

            return self._extract_img_urls(chapter_data)
        except Exception as e:
            logger.error('解析图片列表时发生错误: {}, 错误: {}', url, e, exc_info=True)
            return []

    def _extract_img_urls(self, chapter_data):
        """从章节 API 数据中提取图片 URL 列表

        API 返回的 images 字段是一个对象: {"images": [...], "line": 3}
        """
        images_field = chapter_data.get('images', {})
        if isinstance(images_field, dict):
            images_list = images_field.get('images', [])
            line = images_field.get('line', 3)
        else:
            # 兼容旧格式：images 直接是数组
            images_list = images_field if isinstance(images_field, list) else []
            line = chapter_data.get('line', 3)

        img_host = IMG_HOST_LINE_2 if line == IMG_HOST_LINE_2_VALUE else DEFAULT_IMG_HOST

        images_sorted = sorted(images_list, key=lambda x: x.get('order', 0))
        img_urls = []
        for img in images_sorted:
            img_path = img.get('url', '')
            if not img_path:
                continue
            if img_path.startswith('http'):
                img_urls.append(img_path)
            else:
                img_urls.append(img_host + img_path)
        logger.info('成功解析了 {} 张图片.', len(img_urls))
        return img_urls
