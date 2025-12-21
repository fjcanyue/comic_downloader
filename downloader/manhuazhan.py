from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class ManhuazhanComic(ComicSource):
    name = '漫画站'
    base_url = 'https://www.manhuazhan.com'
    download_interval = 5

    config = {'imgs_js': 'return typeof newImgs !== "undefined" ? newImgs : [];'}

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        logger.info(
            '网站开启了验证码验证，无法使用搜索功能，请手动输入漫画地址。例如：i https://www.manhuazhan.com/comic/255423'
        )
        logger.info(f'开始在 {self.name} 搜索: {keyword}')
        # 由于网站开启了验证码验证，无法使用搜索功能
        # 这里提供一个示例搜索URL，实际使用时需要手动输入漫画地址
        # 例如：i https://www.manhuazhan.com/comic/255423
        search_url = f'{self.base_url}/index.php/search?key={keyword}&verify=1&callback=jQuery112406074091281837971_1750596681221&pcode=anys&_=1750596681224'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error(f"搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}")
                return arr
            # find xpath div id = contents
            main_nodes = root.xpath('//div[@id="contents"]')
            if not main_nodes:
                logger.info(
                    f"在 {self.name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更."
                )
                logger.info(f'页面HTML: {root.xpath("string()")}')
                return arr
            main = main_nodes[0]
        except Exception as e:
            logger.error(f"在 {self.name} 搜索 '{keyword}' 过程中发生错误: {e}", exc_info=True)
            return arr
        book_list = main.xpath('//a')
        logger.info(f'共 {len(book_list)} 条相关的结果')
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
            name_nodes = root.xpath('//div[contains(@class,"d-name")]/div/h1')
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
        meta_table = root.xpath('//div[contains(@class,"d-vod-type")]/p')
        try:
            for meta in meta_table:
                key = ''
                value = ''
                # 优先查找 <span> 作为 key
                span_node = meta.find('span')
                if span_node is not None and span_node.text:
                    key = span_node.text.strip().rstrip('：')
                # value 可能在 <em>、<a> 或 <span> 之后的 tail 文本
                em_node = meta.find('em')
                a_node = meta.find('a')
                if em_node is not None and em_node.text:
                    value = em_node.text.strip()
                elif a_node is not None and a_node.text:
                    value = a_node.text.strip()
                else:
                    # 直接在 <span> 后的 tail
                    if span_node is not None and span_node.tail:
                        value = span_node.tail.strip()
                    elif meta.text and not key:
                        # 没有 <span>，直接分割
                        kvs = meta.text.split('：', 1)
                        key = kvs[0].strip()
                        if len(kvs) > 1:
                            value = kvs[1].strip()
                if key and value:
                    logger.debug(f'元数据: {key} - {value}')
                    comic.metadata.append({'k': key, 'v': value})
                elif key:
                    logger.debug(f"元数据项 '{key}' 的值为空或未找到.")
                else:
                    logger.warning(f'无法解析元数据项: {etree.tostring(meta, encoding="unicode")}')
        except Exception as e:
            logger.warning(f'解析元数据时出错，跳过剩余元数据项，错误: {e}', exc_info=True)
        book_list = root.xpath('//div[contains(@class,"d-play-list")]')
        for book in book_list:
            book_name_nodes = book.xpath('div[contains(@class,"d-title")]/h2')
            if not book_name_nodes or not book_name_nodes[0].xpath('text()'):
                logger.warning(f'未找到章节分组标题，跳过此分组: {url}')
                continue
            # 只获取h2的直接文本（不包括<i>标签内容）
            h2_node = book_name_nodes[0]
            book_title = ''.join(h2_node.xpath('text()')).strip()
            comic_book = ComicBook()
            comic_book.name = book_title
            logger.debug(f'处理章节分组: {comic_book.name}')
            vol_list = book.xpath(
                'div[contains(@class,"d-play-box")]/div[contains(@class,"d-player-list")]/a'
            )
            for vol_node in vol_list:
                try:
                    vol_title = vol_node.text.strip()
                    vol_href = vol_node.attrib.get('href')
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
            # comic_book.vols.reverse() # 保持原有反转逻辑
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

            processed_imgs = []
            for img_url in img_urls:
                if (
                    isinstance(img_url, dict)
                    and 'url' in img_url
                    and isinstance(img_url['url'], str)
                ):
                    processed_imgs.append(img_url['url'])
                    logger.debug(f'解析到图片URL: {img_url["url"]}')
                else:
                    logger.warning(f'无效的图片URL: {img_url}')
            logger.info(f'成功从 {url} 解析并处理了 {len(processed_imgs)} 张图片.')
            return processed_imgs
        except Exception as e:
            logger.error(f'使用 Selenium 解析图片列表时发生错误: {url}, 错误: {e}', exc_info=True)
            return []
