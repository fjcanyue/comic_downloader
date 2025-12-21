from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class BoyaComic(ComicSource):
    name = '博雅漫画'
    base_url = 'http://www.boyamh.com'

    config = {
        'search_xpath': '//ul[contains(@class,"cartoon-block-box")]/li',
        'info_name_xpath': '//div[contains(@class,"article-info-item")]/h1',
        'info_meta_xpath': '//div[contains(@class,"info-item-bottom")]/p',
        'info_books_xpath': '//div[contains(@class,"article-chapter-list")]',
        'info_book_name_xpath': 'div/div[contains(@class,"cart-tag")]',
        'info_vols_xpath': 'ul[contains(@class,"chapter-list")]/li',
        'info_vol_extract': {'name': './a', 'url': './a/@href'},
        'imgs_xpath': '//div[contains(@class,"chapter-content")]/img',
        'imgs_attr': 'data-original',
    }

    def search(self, keyword):
        logger.info(f'开始在 {self.name} 搜索: {keyword}')
        search_url = '%s/search/%s/' % (self.base_url, keyword)
        arr = []
        try:
            root = self.__parse_html__(search_url, 'gbk')
            if root is None:
                logger.error(f"搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}")
                return arr
            main_nodes = root.xpath('//ul[contains(@class,"cartoon-block-box")]')
            if not main_nodes:
                logger.info(
                    f"在 {self.name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更."
                )
                return arr
            main = main_nodes[0]
        except Exception as e:
            logger.error(f"在 {self.name} 搜索 '{keyword}' 过程中发生错误: {e}", exc_info=True)
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

                logger.debug(f'找到漫画: {comic.name}, 作者: {comic.author}, URL: {comic.url}')
                arr.append(comic)
            except Exception as e:
                logger.error(f'解析漫画条目时出错: {e}', exc_info=True)
                continue
        logger.info(f"{self.name} 搜索 '{keyword}' 完成, 共找到 {len(arr)} 条结果.")
        return arr

    def info(self, url):
        logger.info(f'开始获取 {self.name} 动漫详细信息: {url}')
        try:
            root = self.__parse_html__(url, 'gbk')
            if root is None:
                logger.error(f'获取动漫详细信息失败，无法获取或解析页面内容: {url}')
                return None
            comic = Comic()
            comic.url = url
            name_nodes = root.xpath('//div[contains(@class,"article-info-item")]/h1')
            if not name_nodes:
                logger.error(f'解析动漫名称失败: {url}, 页面结构可能已更改.')
                return None
            comic.name = name_nodes[0].text.strip()
            logger.debug(f'动漫名称: {comic.name}')
        except Exception as e:
            logger.error(
                f'获取 {self.name} 动漫详细信息时发生初始错误: {url}, 错误: {e}', exc_info=True
            )
            return None
        meta_table = root.xpath('//div[contains(@class,"info-item-bottom")]/p')
        for meta in meta_table:
            kvs = [meta.xpath('span')[0].text, '']
            link = meta.find('a')
            try:
                key_node = meta.xpath('span')
                if not key_node:
                    continue
                key = key_node[0].text.strip()
                value = ''
                link_node = meta.find('a')
                if link_node is not None and link_node.text:
                    value = link_node.text.strip()
                else:  # 尝试直接获取P标签文本内容作为值（排除span的文本）
                    p_text_content = meta.text_content().strip()
                    # 移除key的部分，剩下的作为value
                    if p_text_content.startswith(key):
                        value = p_text_content[len(key) :].strip()
                    if not value and meta.xpath(
                        'text()'
                    ):  # 如果没有a标签，且直接文本内容也为空，尝试获取P标签的直接文本
                        # 有些网站信息直接在P标签内，而不是A标签
                        p_direct_texts = meta.xpath('text()')
                        value = ' '.join(t.strip() for t in p_direct_texts if t.strip())

                if key and value:
                    logger.debug(f'元数据: {key} - {value}')
                    comic.metadata.append({'k': key, 'v': value})
                elif key:
                    logger.debug(f"元数据项 '{key}' 的值为空或未找到.")
            except Exception as e:
                logger.warning(
                    f'解析元数据时出错: {etree.tostring(meta, encoding="unicode")}, 错误: {e}',
                    exc_info=True,
                )
                continue
        book_list = root.xpath('//div[contains(@class,"article-chapter-list")]')
        for book in book_list:
            book_xpath = book.xpath('div/div[contains(@class,"cart-tag")]')
            book_name_nodes = book.xpath('div/div[contains(@class,"cart-tag")]')
            if not book_name_nodes:
                logger.warning(f'未找到章节分组标题，跳过此分组: {url}')
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug(f'处理章节分组: {comic_book.name}')
            vol_list = book.xpath('ul[contains(@class,"chapter-list")]/li')
            for vol_node in vol_list:
                try:
                    a_tag = vol_node.xpath('a')[0]
                    vol_name = a_tag.text.strip()
                    vol_url_part = a_tag.attrib.get('href')
                    if not vol_url_part:
                        logger.warning(f"卷 '{vol_name}' 的URL部分为空，跳过.")
                        continue
                    full_vol_url = (
                        self.base_url + vol_url_part
                        if vol_url_part.startswith('/')
                        else self.base_url + '/' + vol_url_part
                    )
                    comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
                    logger.debug(f'  找到卷: {vol_name} ({full_vol_url})')
                except IndexError:
                    logger.warning(
                        f'解析卷信息失败，缺少<a>标签: {etree.tostring(vol_node, encoding="unicode")}'
                    )
                except Exception as e:
                    logger.error(
                        f"解析卷 '{vol_name if 'vol_name' in locals() else '未知卷'}' 时出错: {e}",
                        exc_info=True,
                    )
            comic_book.vols.reverse()  # 保留原有反转逻辑
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                logger.warning(f"章节分组 '{comic_book.name}' 不包含任何有效卷，已跳过.")
        logger.info(
            f'{self.name} 动漫详细信息获取完成: {comic.name}, 共 {len(comic.books)} 个章节分组.'
        )
        return comic

    def __parse_imgs__(self, url):
        logger.info(f'开始从 {self.name} 解析图片列表: {url}')
        arr = []
        try:
            root = self.__parse_html__(url, 'gbk')
            if root is None:
                logger.error(f'解析图片列表失败，无法获取或解析页面内容: {url}')
                return arr
            img_nodes = root.xpath(self.config['imgs_xpath'])
            if not img_nodes:
                logger.warning(f'未找到图片元素: {url}')
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
                    logger.debug(f'找到图片URL: {img_url}')
                else:
                    logger.warning(
                        f'图片标签缺少属性: {etree.tostring(img_node, encoding="unicode")}'
                    )
            logger.info(f'成功从 {url} 解析到 {len(arr)} 张图片.')
        except Exception as e:
            logger.error(f'解析图片列表失败: {url}, 错误: {e}', exc_info=True)
        return arr
