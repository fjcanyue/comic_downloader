from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class MoruiComic(ComicSource):
    name = '摩锐漫画'
    base_url = 'https://www.morui.com'
    base_img_url = 'http://lao.haotu90.top'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        logger.info(f'开始在 {self.name} 搜索: {keyword}')
        search_url = '%s/search/?keywords=%s' % (self.base_url, keyword)
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error(f"搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}")
                return arr

            main_nodes = root.xpath('//div[contains(@class,"page-main")]')
            if not main_nodes:
                logger.info(
                    f"在 {self.name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更."
                )
                return arr
            main = main_nodes[0]

            result_count_nodes = main.xpath('.//h4[@class="fl"]')  # 使用 .// 从当前节点开始搜索
            if result_count_nodes:
                result_text = result_count_nodes[0].text.strip()
                logger.info(f'共 {result_text} 条相关的结果')
            else:
                logger.info('未找到结果数量信息.')
        except Exception as e:
            logger.error(f"在 {self.name} 搜索 '{keyword}' 过程中发生错误: {e}", exc_info=True)
            return arr
        book_list = main.xpath('//li[contains(@class,"item-lg")]')
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
                # 作者信息未在此处直接提供，设为空
                comic.author = ''
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
            name_nodes = root.xpath('//div[contains(@class,"book-title")]/h1/span')
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
        # 解析元数据 - 新的HTML结构处理
        meta_table = root.xpath('//ul[contains(@class,"detail-list")]/li')
        for meta in meta_table:
            try:
                # 遍历li下的所有span元素
                spans = meta.xpath('.//span')
                for span in spans:
                    key = ''
                    value = ''
                    
                    # 从strong标签获取键
                    strong_node = span.find('strong')
                    if strong_node is not None and strong_node.text:
                        key = strong_node.text.strip().rstrip('：')
                    
                    # 如果没有找到key，跳过此span
                    if not key:
                        continue
                    
                    # 从span下的所有a标签获取值
                    link_nodes = span.xpath('.//a')
                    if link_nodes:
                        values = []
                        for link in link_nodes:
                            if link.text and link.text.strip():
                                values.append(link.text.strip())
                        
                        if values:
                            value = ' | '.join(values)
                    
                    # 如果找到了有效的键值对
                    if key and value:
                        logger.debug(f'元数据: {key} - {value}')
                        comic.metadata.append({'k': key, 'v': value})
                    elif key:
                        logger.debug(f"元数据项 '{key}' 的值为空或未找到.")
                    else:
                        logger.warning(f'无法解析元数据项: {etree.tostring(span, encoding="unicode")}')
            except Exception as e:
                logger.warning(
                    f'解析元数据时出错: {etree.tostring(meta, encoding="unicode")}, 错误: {e}',
                    exc_info=True,
                )
                continue
        book_list = root.xpath('//div[contains(@class,"comic-chapters")]')
        for book in book_list:
            book_name_nodes = book.xpath('div[contains(@class,"chapter-category")]/div[contains(@class,"caption")]/span')
            if not book_name_nodes or not book_name_nodes[0].text:
                logger.warning(f'未找到章节分组标题，跳过此分组: {url}')
                continue
            comic_book = ComicBook()
            comic_book.name = book_name_nodes[0].text.strip()
            logger.debug(f'处理章节分组: {comic_book.name}')
            vol_list = book.xpath('div[contains(@class,"chapter-body")]/ul/li')
            for vol_node in vol_list:
                try:
                    title_node = vol_node.xpath('a/span')
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
            # 等待页面加载完成，特别是JS变量chapterImages
            # 可以考虑添加显式等待 WebDriverWait if needed
            # self.driver.implicitly_wait(5) # 隐式等待，如果需要
            img_urls = self.driver.execute_script(
                'return typeof chapterImages !== "undefined" ? chapterImages : [];'
            )
            if not img_urls:
                logger.warning(f'未能从页面 {url} 获取 chapterImages 变量，或变量为空.')
                # 尝试查找其他可能的图片源或结构
                # 例如，直接从img标签解析
                # img_elements = self.driver.find_elements(By.XPATH, "//div[@id='comicContain']//img")
                # if img_elements:
                #    self.logger.info(f"尝试从img标签解析图片, 找到 {len(img_elements)} 个元素")
                #    img_urls = [img.get_attribute('src') for img in img_elements if img.get_attribute('src')]
                # else:
                #    self.logger.error(f"无法从 {url} 解析图片列表，chapterImages未定义且未找到img标签.")
                #    return []
                return []  # 如果chapterImages为空，则返回空列表

            processed_imgs = []
            for img_url in img_urls:
                if not img_url or not isinstance(img_url, str):
                    logger.warning(f'无效的图片URL: {img_url}')
                    continue
                processed_imgs.append(img_url)
                logger.debug(f'解析到图片URL: {img_url}')

            logger.info(f'成功从 {url} 解析并处理了 {len(processed_imgs)} 张图片.')
            return processed_imgs
        except Exception as e:
            logger.error(f'使用 Selenium 解析图片列表时发生错误: {url}, 错误: {e}', exc_info=True)
            return []
