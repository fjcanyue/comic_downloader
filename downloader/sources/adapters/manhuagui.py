from selenium.webdriver.support.ui import WebDriverWait

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger
from downloader.sources.templates import InfoFlowMixin, JsImageSourceMixin


class ManhuaguiComic(InfoFlowMixin, JsImageSourceMixin, ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '看漫画'
    base_url = 'https://www.manhuagui.com'
    # base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5
    download_requires_driver = True
    config_file = 'manhuagui.json'
    enable = True

    def search(self, keyword):
        logger.info('开始在 看漫画 搜索: {}', keyword)
        search_url = f'{self.base_url}/s/{keyword}.html'
        root = self.__parse_html__(search_url)
        arr = []
        if root is None:
            logger.error('搜索失败，无法获取页面内容: {}', search_url)
            return arr

        main_nodes = root.xpath('//div[contains(@class,"book-result")]/ul')
        if not main_nodes:
            logger.warning(
                '没有找到页面关键元素 (book-result)，搜索可能无结果或页面结构已更改: {}', search_url
            )
            # 尝试查找是否有提示信息，例如 "没有找到xxx相关的漫画"
            no_result_nodes = root.xpath(
                '//div[contains(@class, "no-result")] | //div[contains(text(),"没有找到")]'
            )
            if no_result_nodes:
                no_result_text = (
                    no_result_nodes[0].text_content().strip()
                    if hasattr(no_result_nodes[0], 'text_content')
                    else '未找到明确的无结果提示'
                )
                logger.info("搜索 '{}' 无结果: {}", keyword, no_result_text)
            return arr

        main = main_nodes[0]
        # result = main.xpath('//em[@class="c_6"]')[0].text
        # print('共 %s 条相关的结果' % result)
        book_list = main.xpath('li')
        for book in book_list:
            b = book.xpath('div/a')[0]
            comic = Comic()
            comic.url = f'{self.base_url}{b.attrib.get("href")}'
            author_list = book.xpath('div[contains(@class,"book-detail")]/dl/dd[3]/span/a')
            authors = [author.text for author in author_list]
            comic.author = ', '.join(authors)
            comic.name = b.attrib.get('title')
            logger.debug('找到漫画: {}, 作者: {}, URL: {}', comic.name, comic.author, comic.url)
            arr.append(comic)
        logger.info("看漫画 搜索 '{}' 完成, 共找到 {} 条结果.", keyword, len(arr))
        return arr

    def _parse_comic_header(self, root, url):
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//div[contains(@class,"book-title")]/h1')[0].text.strip()
        return comic

    def _append_metadata(self, root, comic):
        meta_table = root.xpath('//ul[contains(@class,"detail-list")]/li')
        for meta in meta_table:
            kvs = [meta.xpath('span/strong')[0].text, '']
            link = meta.find('span/a')
            if link is None:
                value = kvs[1]
                if not value:
                    continue
            else:
                value = link.text
            logger.debug('元数据: {} - {}', kvs[0], value.strip())
            comic.metadata.append({'k': kvs[0], 'v': value.strip()})

    def _append_books(self, root, comic, url):
        book_list_nodes = root.xpath('//div[contains(@class,"chapter-list")]')
        if not book_list_nodes:
            logger.warning('未找到章节列表元素: {}, 页面结构可能已更改或无章节信息.', url)
            return

        for book_index, book_node in enumerate(book_list_nodes):
            comic_book = ComicBook()
            try:
                # 尝试更稳健地获取章节标题
                title_node = book_node.xpath('preceding-sibling::h4[1]/span | self::div/h4/span')
                if title_node:
                    comic_book.name = title_node[0].text.strip()
                else:  # 如果特定结构找不到，尝试通用一些的父/兄节点标题
                    # 这是一个备用逻辑，可能需要根据实际页面调整
                    fallback_title_nodes = book_node.xpath(
                        '../h4/span | ../../h4/span | preceding-sibling::div[contains(@class, "title")]/h4/span'
                    )
                    if fallback_title_nodes:
                        comic_book.name = fallback_title_nodes[0].text.strip()
                    else:
                        comic_book.name = f'章节卷 {book_index + 1}'  # 默认名称
                logger.debug('处理章节: {}', comic_book.name)
            except IndexError:
                logger.warning(
                    '解析章节名称失败，使用默认名称: 章节卷 {} ({})', book_index + 1, url
                )
                comic_book.name = f'章节卷 {book_index + 1}'
            vol_list = book_node.xpath('ul/li')
            for vol in vol_list:
                v = vol.xpath('a')[0]
                vol_url = self.absolute_url(v.attrib.get('href'))
                if vol_url:
                    comic_book.vols.append(
                        ComicVolume(
                            v.xpath('span')[0].text.strip(),
                            vol_url,
                            comic_book.name,
                        )
                    )
            comic_book.vols.reverse()  # 保持原有反转逻辑
            comic.books.append(comic_book)

    def _prepare_driver_for_image_parse(self):
        self.driver.implicitly_wait(5)
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script(
                "return typeof pVars !== 'undefined' && pVars.page !== undefined"
            )
        )
