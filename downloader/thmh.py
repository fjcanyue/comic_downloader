from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class TmhComic(ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """
    name = '31漫画'
    base_url = 'https://www.31mh.cc'
    download_interval = 5
    config_file = 'thmh.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    def search(self, keyword):
        logger.info(f'开始在 {self.name} 搜索: {keyword}')
        search_url = '%s/search/?keywords=%s' % (self.base_url, keyword)
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error(f"搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}")
                return arr

            main_nodes = root.xpath('//ul[contains(@class,"list_con_li")]')
            if not main_nodes:
                logger.info(
                    f"在 {self.name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更."
                )
                return arr
            main = main_nodes[0]

            result_count_nodes = main.xpath('.//em[@class="c_6"]')  # 使用 .// 从当前节点开始搜索
            if result_count_nodes:
                result_text = result_count_nodes[0].text.strip()
                logger.info(f'共 {result_text} 条相关的结果')
            else:
                logger.info('未找到结果数量信息.')
        except Exception as e:
            logger.error(f"在 {self.name} 搜索 '{keyword}' 过程中发生错误: {e}", exc_info=True)
            return arr
        book_list = main.xpath('//li[contains(@class,"list-comic")]')
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

                comic.name = b.attrib.get('title', '未知漫画').strip()
                author_nodes = book.xpath('p[contains(@class,"auth")]')
                comic.author = (
                    author_nodes[0].text.strip()
                    if author_nodes and author_nodes[0].text
                    else '未知作者'
                )
                logger.debug(f'找到漫画: {comic.name}, 作者: {comic.author}, URL: {comic.url}')
                arr.append(comic)
            except Exception as e:
                logger.error(
                    f'解析漫画条目时出错: {etree.tostring(book, encoding="unicode")}, 错误: {e}',
                    exc_info=True,
                )
                continue
        logger.info(f"{self.name} 搜索 '{keyword}' 完成, 共找到 {len(arr)} 条结果.")
        return arr

    def info(self, url):
        logger.info(f'开始获取 {self.name} 动漫详细信息: {url}')
        try:
            root = self.__parse_html__(url)
            if root is None:
                logger.error(f'获取动漫详细信息失败，无法获取或解析页面内容: {url}')
                return None
            comic = Comic()
            comic.url = url
            name_nodes = root.xpath('//div[contains(@class,"comic_deCon")]/h1')
            if not name_nodes or not name_nodes[0].text:
                logger.error(f'解析动漫名称失败: {url}, 页面结构可能已更改.')
                return None
            comic.name = name_nodes[0].text.strip()
            logger.debug(f'动漫名称: {comic.name}')
        except Exception as e:
            logger.error(
                f'获取 {self.name} 动漫详细信息时发生初始错误: {url}, 错误: {e}', exc_info=True
            )
            return None
        meta_table = root.xpath('//ul[contains(@class,"comic_deCon_liO")]/li')
        for meta in meta_table:
            try:
                key = ''
                value = ''
                if meta.text:
                    kvs = meta.text.split('：', 1)
                    key = kvs[0].strip()
                    if len(kvs) > 1:
                        value = kvs[1].strip()

                link_node = meta.find('a')
                if link_node is not None and link_node.text:
                    # 如果有链接，链接文本通常是值，键在链接外部的文本中
                    value = link_node.text.strip()
                    # 尝试从meta的直接文本中获取key，如果之前没有通过split获得
                    if not key and meta.text and '：' in meta.text:
                        key = meta.text.split('：')[0].strip()
                    elif (
                        not key
                        and link_node.getprevious() is not None
                        and link_node.getprevious().tail
                    ):
                        # 有时键在链接之前的文本中
                        key = link_node.getprevious().tail.strip().rstrip('：')
                    elif not key and link_node.getparent().text:
                        # 键可能在父节点的文本中
                        key = link_node.getparent().text.split('：')[0].strip()

                if key and value:
                    logger.debug(f'元数据: {key} - {value}')
                    comic.metadata.append({'k': key, 'v': value})
                elif key:
                    logger.debug(f"元数据项 '{key}' 的值为空或未找到.")
                else:
                    logger.warning(f'无法解析元数据项: {etree.tostring(meta, encoding="unicode")}')
            except Exception as e:
                logger.warning(
                    f'解析元数据时出错: {etree.tostring(meta, encoding="unicode")}, 错误: {e}',
                    exc_info=True,
                )
                continue
        book_list = root.xpath('//div[contains(@class,"zj_list")]')
        for book in book_list:
            book_name_nodes = book.xpath('div[contains(@class,"zj_list_head")]/h2')
            if not book_name_nodes or not book_name_nodes[0].text:
                logger.warning(f'未找到章节分组标题，跳过此分组: {url}')
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug(f'处理章节分组: {comic_book.name}')
            vol_list = book.xpath('div[contains(@class,"zj_list_con")]/ul/li')
            for vol_node in vol_list:
                try:
                    title_node = vol_node.xpath('a/span[contains(@class,"list_con_zj")]')
                    href_node = vol_node.xpath('a')
                    if (
                        not title_node
                        or not title_node[0].text
                        or not href_node
                        or not href_node[0].attrib.get('href')
                    ):
                        logger.warning(
                            f'卷信息不完整: {etree.tostring(vol_node, encoding="unicode")}'
                        )
                        continue

                    vol_title = title_node[0].text.strip()
                    vol_href = href_node[0].attrib.get('href')
                    if not vol_href.startswith('http'):
                        full_vol_url = (
                            self.base_url + vol_href
                            if vol_href.startswith('/')
                            else self.base_url + '/' + vol_href
                        )
                    else:
                        full_vol_url = vol_href

                    comic_book.vols.append(ComicVolume(vol_title, full_vol_url, comic_book.name))
                    logger.debug(f'  找到卷: {vol_title} ({full_vol_url})')
                except Exception as e:
                    logger.error(
                        f"解析卷 '{vol_title if 'vol_title' in locals() else '未知卷'}' 时出错: {e}",
                        exc_info=True,
                    )
            comic_book.vols.reverse()  # 保持原有反转逻辑
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
        try:
            self.driver.get(url)
            img_urls = self.execute_js_safely(self.driver, self.config['imgs_js'], [])
            if not img_urls:
                logger.warning(f'未能从页面 {url} 获取图片变量.')
                return []

            processed_imgs = [img for img in img_urls if img and isinstance(img, str)]
            logger.info(f'成功从 {url} 解析并处理了 {len(processed_imgs)} 张图片.')
            return processed_imgs
        except Exception as e:
            logger.error(f'使用 Selenium 解析图片列表时发生错误: {url}, 错误: {e}', exc_info=True)
            return []
