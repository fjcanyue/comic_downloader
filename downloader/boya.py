from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class BoyaComic(ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '博雅漫画'
    base_url = 'http://www.boyamh.com'
    config_file = 'boya.json'
    enable = False

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/search/{keyword}/'
        arr = []
        try:
            root = self.__parse_html__(search_url, 'gbk')
            if root is None:
                logger.error("搜索 '{}' 失败，无法获取或解析页面: {}", keyword, search_url)
                return arr
            main_nodes = root.xpath('//ul[contains(@class,"cartoon-block-box")]')
            if not main_nodes:
                logger.info(
                    "在 {} 搜索 '{}' 时未找到主要内容区域，可能无结果或页面结构变更.",
                    self.name,
                    keyword,
                )
                return arr
            main = main_nodes[0]
        except Exception as e:
            logger.error("在 {} 搜索 '{}' 过程中发生错误: {}", self.name, keyword, e, exc_info=True)
            return arr
        # result = main.xpath('//em[@class="c_6"]')[0].text
        # print('共 %s 条相关的结果' % result)
        book_list = main.xpath('li')
        for book in book_list:
            b = book.xpath('div/a')[0]
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

                author_nodes = b.xpath('span')
                comic.author = author_nodes[0].text.strip() if author_nodes else '未知作者'

                name_nodes = book.xpath('div/div/p/a')
                comic.name = name_nodes[0].text.strip() if name_nodes else '未知漫画'

                logger.debug('找到漫画: {}, 作者: {}, URL: {}', comic.name, comic.author, comic.url)
                arr.append(comic)
            except Exception as e:
                logger.error('解析漫画条目时出错: {}', e, exc_info=True)
                continue
        logger.info("{} 搜索 '{}' 完成, 共找到 {} 条结果.", self.name, keyword, len(arr))
        return arr

    def info(self, url):
        logger.info('开始获取 {} 动漫详细信息: {}', self.name, url)
        root = self.__parse_html__(url, 'gbk')
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
            name_nodes = root.xpath('//div[contains(@class,"article-info-item")]/h1')
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
        meta_table = root.xpath('//div[contains(@class,"info-item-bottom")]/p')
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            key_node = meta.xpath('span')
            if not key_node:
                return
            key = key_node[0].text.strip()
            value = ''
            link_node = meta.find('a')
            if link_node is not None and link_node.text:
                value = link_node.text.strip()
            else:
                p_text_content = meta.text_content().strip()
                if p_text_content.startswith(key):
                    value = p_text_content[len(key) :].strip()
                if not value and meta.xpath('text()'):
                    p_direct_texts = meta.xpath('text()')
                    value = ' '.join(t.strip() for t in p_direct_texts if t.strip())

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
        book_list = root.xpath('//div[contains(@class,"article-chapter-list")]')
        for book in book_list:
            book_name_nodes = book.xpath('div/div[contains(@class,"cart-tag")]')
            if not book_name_nodes:
                logger.warning('未找到章节分组标题，跳过此分组: {}', url)
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug('处理章节分组: {}', comic_book.name)
            self._append_book_volumes(book, comic_book)
            comic_book.vols.reverse()  # 保留原有反转逻辑
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                logger.warning("章节分组 '{}' 不包含任何有效卷，已跳过.", comic_book.name)

    def _append_book_volumes(self, book, comic_book):
        vol_list = book.xpath('ul[contains(@class,"chapter-list")]/li')
        for vol_node in vol_list:
            a_tags = vol_node.xpath('a')
            if not a_tags:
                logger.warning(
                    '解析卷信息失败，缺少<a>标签: {}', etree.tostring(vol_node, encoding='unicode')
                )
                continue
            a_tag = a_tags[0]
            vol_name = a_tag.text.strip() if a_tag.text else '未知卷'
            vol_url_part = a_tag.attrib.get('href')
            if not vol_url_part:
                logger.warning("卷 '{}' 的URL部分为空，跳过.", vol_name)
                continue
            full_vol_url = (
                self.base_url + vol_url_part
                if vol_url_part.startswith('/')
                else self.base_url + '/' + vol_url_part
            )
            comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
            logger.debug('  找到卷: {} ({})', vol_name, full_vol_url)

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片列表: {}', self.name, url)
        arr = []
        try:
            root = self.__parse_html__(url, 'gbk')
            if root is None:
                logger.error('解析图片列表失败，无法获取或解析页面内容: {}', url)
                return arr
            img_nodes = root.xpath(self.config['imgs_xpath'])
            if not img_nodes:
                logger.warning('未找到图片元素: {}', url)
                return arr
            for img_node in img_nodes:
                img_url = img_node.attrib.get(self.config['imgs_attr']) or img_node.attrib.get(
                    'src'
                )
                if img_url:
                    if not img_url.startswith('http'):
                        img_url = (
                            self.base_url + img_url
                            if img_url.startswith('/')
                            else self.base_url + '/' + img_url
                        )
                    arr.append(img_url)
                    logger.debug('找到图片URL: {}', img_url)
                else:
                    logger.warning(
                        '图片标签缺少属性: {}', etree.tostring(img_node, encoding='unicode')
                    )
            logger.info('成功从 {} 解析到 {} 张图片.', url, len(arr))
        except Exception as e:
            logger.error('解析图片列表失败: {}, 错误: {}', url, e, exc_info=True)
        return arr
