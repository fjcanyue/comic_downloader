import re

import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger

JS_SNIPPET_LONG_LENGTH = 400


class MaoflyComic(ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '漫画猫'
    base_url = 'https://www.maofly.com'
    base_img_url = 'https://mao.mhtupian.com/uploads'
    download_interval = 5
    download_requires_driver = True
    config_file = 'maofly.json'
    enable = False

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)
        js_url = f'{self.base_url}/static/js/string.min.js'
        try:
            logger.info('正在为 {} 初始化JS解码器...', self.name)
            r = self.http.get(js_url, timeout=30)
            r.raise_for_status()
            self.jsstring = r.text
            logger.info('成功获取JS解码脚本: {}', js_url)
        except requests.exceptions.RequestException as e:
            logger.error('获取JS解码脚本失败: {}, 错误: {}', js_url, e, exc_info=True)
            self.jsstring = ''  # 设置为空字符串，后续解码会失败但不会抛出未定义错误
        except Exception as e:
            logger.error('初始化 {} JS解码器时发生未知错误: {}', self.name, e, exc_info=True)
            self.jsstring = ''

        self.pattern_img_data = re.compile(r'let img_data\s*=\s*"(.+)"')

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/search.html?q={keyword}'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error("搜索 '{}' 失败，无法获取或解析页面: {}", keyword, search_url)
                return arr
            main_nodes = root.xpath('//div[contains(@class,"comic-main-section")]')
            if not main_nodes:
                logger.info(
                    "在 {} 搜索 '{}' 时未找到主要内容区域，可能无结果或页面结构变更.",
                    self.name,
                    keyword,
                )
                return arr
            main = main_nodes[0]
            result_nodes = main.xpath('//div[@class="text-muted"]')
            if result_nodes:
                logger.info(result_nodes[0].text.strip())
            else:
                logger.info('未找到结果数量信息.')
        except Exception as e:
            logger.error("在 {} 搜索 '{}' 过程中发生错误: {}", self.name, keyword, e, exc_info=True)
            return arr
        book_list = main.xpath('//div[contains(@class,"comicbook-index")]')
        arr = []
        for book in book_list:
            b = book.xpath('a')[0]
            comic = Comic()
            try:
                comic.url = b.attrib.get('href')
                if not comic.url:
                    logger.warning('解析到一个没有URL的漫画条目，已跳过。')
                    continue
                if not comic.url.startswith('http'):
                    comic.url = (
                        self.base_url + comic.url
                        if comic.url.startswith('/')
                        else self.base_url + '/' + comic.url
                    )

                comic.name = b.attrib.get('title', '未知漫画')
                author_nodes = book.xpath('div/a')
                comic.author = author_nodes[0].text.strip() if author_nodes else '未知作者'
                logger.debug('找到漫画: {}, 作者: {}, URL: {}', comic.name, comic.author, comic.url)
                arr.append(comic)
            except Exception as e:
                logger.error('解析漫画条目时出错: {}', e, exc_info=True)
                continue
        logger.info("{} 搜索 '{}' 完成, 共找到 {} 条结果.", self.name, keyword, len(arr))
        return arr

    def info(self, url):
        logger.info('开始获取 {} 动漫详细信息: {}', self.name, url)
        root = self.__parse_html__(url)
        if root is None:
            logger.error('获取动漫详细信息失败，无法获取或解析页面内容: {}', url)
            return None

        comic = self._parse_comic_header(root, url)
        if comic is None:
            return None
        self._append_metadata(root, comic)
        self._append_books(root, comic, url)
        logger.info(
            '{} 动漫详细信息获取完成: {}, 共 {} 个章节分组.',
            self.name,
            comic.name,
            len(comic.books),
        )
        return comic

    def _parse_comic_header(self, root, url):
        try:
            comic = Comic()
            comic.url = url
            name_nodes = root.xpath('//td[@class="comic-titles"]')
            if not name_nodes:
                logger.error('解析动漫名称失败: {}, 页面结构可能已更改.', url)
                return None
            comic.name = name_nodes[0].text.strip()
            logger.debug('动漫名称: {}', comic.name)
        except Exception as e:
            logger.error(
                '获取 {} 动漫详细信息时发生初始错误: {}, 错误: {}', self.name, url, e, exc_info=True
            )
            return None

        return comic

    def _append_metadata(self, root, comic):
        meta_table = root.xpath('//table[contains(@class,"comic-meta-data-table")]/tbody/tr')
        for meta in meta_table:
            self._append_metadata_row(comic, meta)

    def _append_metadata_row(self, comic, meta):
        try:
            key_node = meta.xpath('th')
            if not key_node or not key_node[0].text:
                logger.warning('元数据缺少键名.')
                return
            key = key_node[0].text.strip()
            value = ''
            link_node = meta.find('td/a')
            td_node = meta.find('td')

            if link_node is not None and link_node.text:
                value = link_node.text.strip()
            elif td_node is not None and td_node.text:
                value = td_node.text.strip()

            if key and value:
                logger.debug('元数据: {} - {}', key, value)
                comic.metadata.append({'k': key, 'v': value})
            elif key:
                logger.debug("元数据项 '{}' 的值为空或未找到.", key)
        except Exception as e:
            logger.warning(
                '解析元数据时出错: {}, 错误: {}',
                etree.tostring(meta, encoding='unicode'),
                e,
                exc_info=True,
            )

    def _append_books(self, root, comic, url):
        book_list = root.xpath('//div[@id="comic-book-list"]/div')
        for book in book_list:
            book_name_nodes = book.xpath('div/div/h2')
            if not book_name_nodes:
                logger.warning('未找到章节分组标题，跳过此分组: {}', url)
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug('处理章节分组: {}', comic_book.name)
            self._append_book_volumes(book, comic_book)
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                logger.warning("章节分组 '{}' 不包含任何有效卷，已跳过.", comic_book.name)

    def _append_book_volumes(self, book, comic_book):
        vol_list = book.xpath('ol/li/a')
        for vol_node in vol_list:
            vol_title = vol_node.attrib.get('title')
            vol_href = vol_node.attrib.get('href')
            if not vol_title or not vol_href:
                logger.warning(
                    '卷信息不完整 (缺少title或href): {}',
                    etree.tostring(vol_node, encoding='unicode'),
                )
                continue
            full_vol_url = vol_href if vol_href.startswith('http') else self.base_url + vol_href
            comic_book.vols.append(ComicVolume(vol_title.strip(), full_vol_url, comic_book.name))
            logger.debug('  找到卷: {} ({})', vol_title.strip(), full_vol_url)

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片列表: {}', self.name, url)
        try:
            img_data_str = self.__find_img_data__(url)
            if not img_data_str:
                logger.error('未能从页面找到 img_data 变量: {}', url)
                return []

            imgs_list_str = self.__decode_img_data__(img_data_str)
            if not imgs_list_str:
                logger.error('解码 img_data 失败或返回空: {}', url)
                return []

            # 图片URL需要拼接 base_img_url
            # 示例: /comic/123/abc.jpg -> https://mao.mhtupian.com/uploads/comic/123/abc.jpg
            # 确保 self.base_img_url 不以 / 结尾，且图片路径以 / 开头
            # 如果图片路径已经是完整URL，则直接使用
            processed_imgs = []
            for img_path in imgs_list_str:
                if not img_path or not isinstance(img_path, str):
                    logger.warning('无效的图片路径: {}', img_path)
                    continue
                if img_path.startswith(('http://', 'https://')):
                    processed_imgs.append(img_path)
                else:
                    # 确保 base_img_url 和 img_path 正确拼接
                    # 通常 img_path 会以 / 开头，如果不是，可能需要调整
                    full_img_url = self.base_img_url.rstrip('/') + '/' + img_path.lstrip('/')
                    processed_imgs.append(full_img_url)
                logger.debug('解析到图片URL: {}', processed_imgs[-1])

            logger.info('成功从 {} 解析并处理了 {} 张图片.', url, len(processed_imgs))
            return processed_imgs
        except Exception as e:
            logger.error('解析图片列表时发生意外错误: {}, 错误: {}', url, e, exc_info=True)
            return []

    def __find_img_data__(self, url):
        logger.debug('开始在 {} 查找 img_data 变量', url)
        try:
            root = self.__parse_html__(url)
            if root is None:
                logger.error('查找 img_data 失败，无法获取或解析页面: {}', url)
                return None
            scripts = root.xpath('//script[not(@src)]/text()')
            for script_content in scripts:
                if not script_content:
                    continue
                match = self.pattern_img_data.search(
                    script_content
                )  # 使用search而不是findall，因为我们只需要第一个匹配
                if match:
                    img_data_value = match.group(1)
                    logger.debug('成功找到 img_data 变量值 (长度: {})', len(img_data_value))
                    return img_data_value
            logger.warning('未能在页面脚本中找到 img_data 变量: {}', url)
            return None
        except Exception as e:
            logger.error('查找 img_data 时发生错误: {}, 错误: {}', url, e, exc_info=True)
            return None

    def __decode_img_data__(self, img_data_str):
        logger.debug('开始解码 img_data (长度: {})', len(img_data_str))
        if not self.jsstring:
            logger.error('JS解码脚本 (self.jsstring) 未初始化或为空，无法解码 img_data.')
            return []
        if not img_data_str or not isinstance(img_data_str, str):
            logger.error('无效的 img_data_str 输入: {}', img_data_str)
            return []
        js_code = ''
        try:
            # 确保img_data_str中的特殊字符被正确转义以用于JS字符串
            escaped_img_data = (
                img_data_str.replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace("'", "\\'")
                .replace('\n', '\\n')
                .replace('\r', '\\r')
            )
            js_code = (
                f'{self.jsstring}; return LZString.decompressFromBase64("{escaped_img_data}");'
            )

            logger.debug('准备执行JS解码...')
            decoded_string = self.driver.execute_script(js_code)

            if decoded_string and isinstance(decoded_string, str):
                logger.info('成功解码 img_data, 解码后字符串长度: {}', len(decoded_string))
                # 假设解码后的字符串是以逗号分隔的图片路径列表
                img_paths = decoded_string.split(',')
                return [path.strip() for path in img_paths if path.strip()]  # 去除空路径和首尾空格
            if not decoded_string:
                logger.warning('JS解码返回空字符串或None.')
                return []
            logger.warning(
                'JS解码返回了非字符串类型: {}, 内容: {}...',
                type(decoded_string),
                str(decoded_string)[:100],
            )
            return []
        except Exception as e:
            logger.error('使用 Selenium 解码 img_data 时发生错误: {}', e, exc_info=True)
            logger.debug(
                '执行的JS代码片段(部分): {}...{}',
                js_code[:200],
                js_code[-200:] if len(js_code) > JS_SNIPPET_LONG_LENGTH else '',
            )
            return []
