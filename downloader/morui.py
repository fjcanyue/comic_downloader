from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser_modes import CLOAKBROWSER_MODE
from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class MoruiComic(ComicSource):
    name = '摩锐漫画'
    base_url = 'https://www.morui.com'
    base_img_url = 'http://lao.haotu90.top'
    browser_mode = CLOAKBROWSER_MODE
    browser_wait_selector = '.page-main'
    browser_wait_seconds = 60.0
    browser_headless = False
    download_interval = 5
    download_requires_driver = True
    seleniumbase_wait_selector = '.page-main'
    seleniumbase_wait_seconds = 60.0
    seleniumbase_headless = False
    config_file = 'morui.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/search/?keywords={keyword}'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error("搜索 '{}' 失败，无法获取或解析页面: {}", keyword, search_url)
                return arr

            main_nodes = root.xpath('//div[contains(@class,"page-main")]')
            if not main_nodes:
                logger.info(
                    "在 {} 搜索 '{}' 时未找到主要内容区域，可能无结果或页面结构变更.",
                    self.name,
                    keyword,
                )
                return arr
            main = main_nodes[0]

            result_count_nodes = main.xpath('.//h4[@class="fl"]')
            if result_count_nodes:
                result_text = result_count_nodes[0].text.strip()
                logger.info('共 {} 条相关的结果', result_text)
            else:
                logger.info('未找到结果数量信息.')

            # 使用通用方法解析搜索结果
            items = self.parse_xpath_list(
                main, self.config['search_xpath'], self.config['search_extract']
            )
            for item in items:
                comic = Comic()
                try:
                    comic.url = item['url']
                    if not comic.url:
                        logger.warning('解析到一个没有URL的漫画条目，已跳过。')
                        continue
                    if not comic.url.startswith('http'):
                        comic.url = (
                            self.base_url + comic.url
                            if comic.url.startswith('/')
                            else self.base_url + '/' + comic.url
                        )
                    comic.name = item['name'] or '未知漫画'
                    comic.author = ''
                    logger.debug(
                        '找到漫画: {}, 作者: {}, URL: {}', comic.name, comic.author, comic.url
                    )
                    arr.append(comic)
                except Exception as e:
                    logger.error('解析漫画条目时出错: {}, 错误: {}', item, e, exc_info=True)
                    continue
        except Exception as e:
            logger.error("在 {} 搜索 '{}' 过程中发生错误: {}", self.name, keyword, e, exc_info=True)
            return arr
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
            name_nodes = root.xpath('//div[contains(@class,"book-title")]/h1/span')
            if not name_nodes or not name_nodes[0].text:
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
        meta_table = root.xpath('//ul[contains(@class,"detail-list")]/li')
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            for span in meta.xpath('.//span'):
                self._append_metadata_span(comic, span)
        except Exception as e:
            logger.warning(
                '解析元数据时出错: {}, 错误: {}',
                etree.tostring(meta, encoding='unicode'),
                e,
                exc_info=True,
            )

    def _append_metadata_span(self, comic, span):
        key = ''
        value = ''

        strong_node = span.find('strong')
        if strong_node is not None and strong_node.text:
            key = strong_node.text.strip().rstrip('：')
        if not key:
            return

        values = [
            link.text.strip() for link in span.xpath('.//a') if link.text and link.text.strip()
        ]
        if values:
            value = ' | '.join(values)

        if key and value:
            logger.debug('元数据: {} - {}', key, value)
            comic.metadata.append({'k': key, 'v': value})
        elif key:
            logger.debug("元数据项 '{}' 的值为空或未找到.", key)

    def _append_books(self, root, comic, url):
        book_list = root.xpath('//div[contains(@class,"comic-chapters")]')
        for book in book_list:
            book_name_nodes = book.xpath(
                'div[contains(@class,"chapter-category")]/div[contains(@class,"caption")]/span'
            )
            if not book_name_nodes or not book_name_nodes[0].text:
                logger.warning('未找到章节分组标题，跳过此分组: {}', url)
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug('处理章节分组: {}', comic_book.name)
            self._append_book_volumes(book, comic_book)
            comic_book.vols.reverse()  # 保持原有反转逻辑
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                logger.warning("章节分组 '{}' 不包含任何有效卷，已跳过.", comic_book.name)

    def _append_book_volumes(self, book, comic_book):
        vol_list = book.xpath('div[contains(@class,"chapter-body")]/ul/li')
        for vol_node in vol_list:
            title_node = vol_node.xpath('a/span')
            href_node = vol_node.xpath('a')
            if (
                not title_node
                or not title_node[0].text
                or not href_node
                or not href_node[0].attrib.get('href')
            ):
                logger.warning('卷信息不完整: {}', etree.tostring(vol_node, encoding='unicode'))
                continue

            vol_title = title_node[0].text.strip()
            vol_href = href_node[0].attrib.get('href')
            full_vol_url = (
                self.base_url + vol_href
                if vol_href.startswith('/')
                else f'{self.base_url}/{vol_href}'
            )
            if vol_href.startswith('http'):
                full_vol_url = vol_href

            comic_book.vols.append(ComicVolume(vol_title, full_vol_url, comic_book.name))
            logger.debug('  找到卷: {} ({})', vol_title, full_vol_url)

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片列表: {}', self.name, url)
        try:
            self.driver.get(url)
            img_urls = self.execute_js_safely(self.driver, self.config['imgs_js'], [])
            if not img_urls:
                logger.warning('未能从页面 {} 获取图片变量.', url)
                return []

            processed_imgs = [img for img in img_urls if img and isinstance(img, str)]
            logger.info('成功从 {} 解析并处理了 {} 张图片.', url, len(processed_imgs))
            return processed_imgs
        except Exception as e:
            logger.error(
                '使用 Selenium 解析图片列表时发生错误: {}, 错误: {}', url, e, exc_info=True
            )
            return []
