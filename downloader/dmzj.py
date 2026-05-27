import requests

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class DmzjComic(ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '动漫之家'
    base_url = 'http://manhua.dmzj.com'
    base_img_url = 'http://images.dmzj.com'
    download_interval = 5
    download_requires_driver = True
    config_file = 'dmzj.json'
    enable = False
    search_requires_driver = True

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    def search(self, keyword):
        logger.info('开始在 动漫之家 搜索: {}', keyword)
        search_url = f'http://sacg.dmzj.com/comicsum/search.php?s={keyword}'
        arr = []
        try:
            r = self.http.get(search_url, timeout=30)
            r.raise_for_status()
            js_code = r.text + '; ' + self.config['search_js']
            results = self.execute_js_safely(self.driver, js_code, [])
            if not results:
                logger.info("动漫之家 搜索 '{}' 无结果或解析JS失败.", keyword)
                return arr
        except requests.exceptions.RequestException as e:
            logger.error('请求动漫之家搜索接口失败: {}, 错误: {}', search_url, e)
            return arr
        except Exception as e:
            logger.error('执行动漫之家搜索脚本失败: {}, 错误: {}', search_url, e, exc_info=True)
            return arr

        for book in results:
            comic = Comic()
            comic_url_raw = book.get('comic_url_raw') or ''
            comic.url = 'http:' + comic_url_raw
            if not comic.url.startswith(self.base_url):
                logger.debug('跳过非动漫之家站内链接: {}', comic.url)
                continue
            comic.name = book.get('comic_name', '未知漫画')
            comic.author = book.get('comic_author', '未知作者')
            logger.debug('找到漫画: {}, 作者: {}, URL: {}', comic.name, comic.author, comic.url)
            arr.append(comic)
        logger.info("动漫之家 搜索 '{}' 完成, 共找到 {} 条结果.", keyword, len(arr))
        return arr

    def info(self, url):
        logger.info('开始获取 动漫之家 动漫详细信息: {}', url)
        root = self.__parse_html__(url)
        if root is None:
            logger.error('获取动漫详细信息失败，无法获取页面内容: {}', url)
            return None

        comic = self._parse_comic_header(root, url)
        if comic is None:
            return None
        self._append_metadata(root, comic)
        book_list_nodes, is_direct_chapter_list = self._find_book_nodes(root, url)
        self._append_books(book_list_nodes, is_direct_chapter_list, comic, url)
        logger.info(
            '动漫之家 动漫详细信息获取完成: {}, 共 {} 个章节.', comic.name, len(comic.books)
        )
        return comic

    def _parse_comic_header(self, root, url):
        comic = Comic()
        comic.url = url
        try:
            comic.name = root.xpath('//span[@class="anim_title_text"]/a/h1')[0].text.strip()
            logger.debug('动漫名称: {}', comic.name)
        except IndexError:
            logger.error('解析动漫名称失败: {}, 页面结构可能已更改.', url)
            # 尝试备用路径
            try:
                comic.name = root.xpath(
                    '//div[@class="comic_deCon_new"]/div[@class="comic_deCon_left"]/h1/a'
                )[0].text.strip()
                logger.debug('动漫名称 (备用路径): {}', comic.name)
            except IndexError:
                logger.error('备用路径解析动漫名称也失败: {}', url)
                return None
        return comic

    def _append_metadata(self, root, comic):
        meta_table = root.xpath('//div[@class="anim-main_list"]/table/tr')
        for meta in meta_table:
            v_element = meta.xpath('td/a')
            if len(v_element) > 0:
                key = meta.xpath('th')[0].text
                value = v_element[0].text
                logger.debug('元数据: {} - {}', key, value)
                comic.metadata.append({'k': key, 'v': value})

    def _find_book_nodes(self, root, url):
        book_list_xpaths = [
            '//div[contains(@class,"cartoon_online_border")]//div[contains(@class,"tab-content")]//ul[contains(@class,"list_con_li")]',
            '//div[@class="middleright"]/div[@class="middleright_mr"]/div[@class="photo_part"]',  # 旧版结构
            '//div[contains(@class, "chapter_con")]/ul/li',  # 另一种可能的章节列表结构
        ]
        book_list_nodes = []
        is_direct_chapter_list = False
        for xpath_expr in book_list_xpaths:
            nodes = root.xpath(xpath_expr)
            if nodes:
                if 'chapter_con' in xpath_expr:
                    is_direct_chapter_list = True
                book_list_nodes = nodes
                break

        if not book_list_nodes:
            logger.warning('未找到章节列表元素: {}, 页面结构可能已更改或无章节信息.', url)
        return book_list_nodes, is_direct_chapter_list

    def _append_books(self, book_list_nodes, is_direct_chapter_list, comic, url):
        for book in book_list_nodes:
            if is_direct_chapter_list:
                comic_book = self._build_direct_chapter_book(book, url)
            else:  # 原有的处理逻辑，适用于按卷分组的章节
                comic_book = self._build_grouped_book(book, comic, url)

            if comic_book.vols or is_direct_chapter_list:
                comic.books.append(comic_book)
            elif not is_direct_chapter_list:
                logger.warning("章节分组 '{}' 不包含任何有效卷，已跳过.", comic_book.name)

    def _build_direct_chapter_book(self, book, url):
        a_tag = book.xpath('.//a')[0]
        comic_book = ComicBook()
        comic_book.name = a_tag.text.strip() if a_tag.text else '默认章节'
        vol_url_part = a_tag.attrib.get('href')
        if vol_url_part:
            full_vol_url = (
                self.base_url + vol_url_part
                if not vol_url_part.startswith('http')
                else vol_url_part
            )
            comic_book.vols.append(ComicVolume(comic_book.name, full_vol_url, comic_book.name))
        else:
            logger.warning('未找到卷链接 for {} in {}', comic_book.name, url)
        logger.debug('处理单卷章节: {}', comic_book.name)
        return comic_book

    def _build_grouped_book(self, book, comic, url):
        comic_book = ComicBook()
        comic_book.name = self._get_grouped_book_name(book, comic, url)
        logger.debug('处理章节分组: {}', comic_book.name)
        vol_list_nodes = self._get_grouped_volume_nodes(book)
        if not vol_list_nodes:
            logger.warning("在章节分组 '{}' 下未找到卷列表: {}", comic_book.name, url)
            return comic_book
        for vol_node in vol_list_nodes:
            self._append_grouped_volume(comic_book, vol_node, url)
        return comic_book

    def _get_grouped_book_name(self, book, comic, url):
        title_nodes = book.xpath(
            './/h2/text() | .//div[contains(@class,"title")]/a/text() | .//span[contains(@class,"title")]/text() | .//h3/text()'
        )
        if title_nodes:
            return title_nodes[0].strip()
        preceding_h2 = book.xpath('preceding-sibling::h2[1]/text()')
        if preceding_h2:
            return preceding_h2[0].strip()
        logger.warning('未找到明确的章节分组标题，使用默认名称 for {}', url)
        return f'默认卷 {(len(comic.books) + 1)}'

    def _get_grouped_volume_nodes(self, book):
        vol_list_nodes = book.xpath(
            './/ul[contains(@class,"list_con_li")]/li | .//div[contains(@class,"cartoon_online_border_other")]/ul/li | following-sibling::div[contains(@class,"cartoon_online_border")]/ul/li'
        )
        if not vol_list_nodes and book.tag == 'div' and 'photo_part' in book.get('class', ''):
            return book.xpath(
                'following-sibling::div[contains(@class,"cartoon_online_border")][1]/ul/li'
            )
        return vol_list_nodes

    def _append_grouped_volume(self, comic_book, vol_node, url):
        a = vol_node.xpath('.//a')[0]
        vol_name = a.text.strip()
        vol_url_part = a.attrib.get('href')
        if not vol_url_part:
            logger.warning('未找到卷链接 for {} in {} ({})', vol_name, comic_book.name, url)
            return
        full_vol_url = (
            self.base_url + vol_url_part if not vol_url_part.startswith('http') else vol_url_part
        )
        comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
        logger.debug('  找到卷: {} ({})', vol_name, full_vol_url)

    def __parse_imgs__(self, url):
        logger.info('开始从 动漫之家 解析图片列表: {}', url)
        try:
            self.driver.get(url)
            self.driver.implicitly_wait(10)
            imgs = self.execute_js_safely(self.driver, self.config['imgs_js'], [])
            if imgs and isinstance(imgs, list):
                logger.info('成功解析到 {} 张图片来自 {}', len(imgs), url)
            else:
                logger.warning('未解析到图片链接: {}', url)
            return imgs if isinstance(imgs, list) else []
        except Exception as e:
            logger.error('使用 Selenium 解析图片列表失败: {}, 错误: {}', url, e, exc_info=True)
            return []
