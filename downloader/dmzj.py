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
    config_file = 'dmzj.json'

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    def search(self, keyword):
        logger.info(f'开始在 动漫之家 搜索: {keyword}')
        search_url = 'http://sacg.dmzj.com/comicsum/search.php?s=%s' % keyword
        arr = []
        try:
            r = self.http.get(search_url, timeout=30)
            r.raise_for_status()
            js_code = r.text + '; ' + self.config['search_js']
            results = self.execute_js_safely(self.driver, js_code, [])
            if not results:
                logger.info(f"动漫之家 搜索 '{keyword}' 无结果或解析JS失败.")
                return arr
        except requests.exceptions.RequestException as e:
            logger.error(f'请求动漫之家搜索接口失败: {search_url}, 错误: {e}')
            return arr
        except Exception as e:
            logger.error(f'执行动漫之家搜索脚本失败: {search_url}, 错误: {e}', exc_info=True)
            return arr

        for book in results:
            comic = Comic()
            comic.url = 'http:' + book.get('comic_url_raw', '')
            if not comic.url.startswith(self.base_url):
                logger.debug(f'跳过非动漫之家站内链接: {comic.url}')
                continue
            comic.name = book.get('comic_name', '未知漫画')
            comic.author = book.get('comic_author', '未知作者')
            logger.debug(f'找到漫画: {comic.name}, 作者: {comic.author}, URL: {comic.url}')
            arr.append(comic)
        logger.info(f"动漫之家 搜索 '{keyword}' 完成, 共找到 {len(arr)} 条结果.")
        return arr

    def info(self, url):
        logger.info(f'开始获取 动漫之家 动漫详细信息: {url}')
        root = self.__parse_html__(url)
        if root is None:
            logger.error(f'获取动漫详细信息失败，无法获取页面内容: {url}')
            return None
        comic = Comic()
        comic.url = url
        try:
            comic.name = root.xpath('//span[@class="anim_title_text"]/a/h1')[0].text.strip()
            logger.debug(f'动漫名称: {comic.name}')
        except IndexError:
            logger.error(f'解析动漫名称失败: {url}, 页面结构可能已更改.')
            # 尝试备用路径
            try:
                comic.name = root.xpath(
                    '//div[@class="comic_deCon_new"]/div[@class="comic_deCon_left"]/h1/a'
                )[0].text.strip()
                logger.debug(f'动漫名称 (备用路径): {comic.name}')
            except IndexError:
                logger.error(f'备用路径解析动漫名称也失败: {url}')
                return None
        meta_table = root.xpath('//div[@class="anim-main_list"]/table/tr')
        for meta in meta_table:
            v_element = meta.xpath('td/a')
            if len(v_element) > 0:
                key = meta.xpath('th')[0].text
                value = v_element[0].text
                logger.debug(f'元数据: {key} - {value}')
                comic.metadata.append({'k': key, 'v': value})

        # 章节列表的Xpath，可能需要根据实际页面调整，尝试兼容多种可能的结构
        book_list_xpaths = [
            '//div[contains(@class,"cartoon_online_border")]//div[contains(@class,"tab-content")]//ul[contains(@class,"list_con_li")]',
            '//div[@class="middleright"]/div[@class="middleright_mr"]/div[@class="photo_part"]',  # 旧版结构
            '//div[contains(@class, "chapter_con")]/ul/li',  # 另一种可能的章节列表结构
        ]
        book_list_nodes = []
        for xpath_expr in book_list_xpaths:
            nodes = root.xpath(xpath_expr)
            if nodes:
                # 如果是章节本身的列表 (如第三个xpath)，则直接使用
                if 'chapter_con' in xpath_expr:
                    # 这种结构下，每个li是一个章节，标题和链接都在li内部
                    # 需要特殊处理，这里暂时简化为先找到包含章节的父节点
                    # 实际解析在下面的循环中进行
                    book_list_nodes = nodes  # 直接将li列表作为处理对象
                    break
                # 如果是包含多个章节列表的父节点
                book_list_nodes = nodes
                break

        if not book_list_nodes:
            logger.warning(f'未找到章节列表元素: {url}, 页面结构可能已更改或无章节信息.')
            return comic  # 即使没有章节，也返回已获取的漫画基本信息
        # vol_divs = root.xpath('//div[@class="cartoon_online_border" or @class="cartoon_online_border_other"]')
        # for index, book in enumerate(book_list):
        for book in book_list_nodes:
            # 根据 book_list_nodes 的结构调整章节名和卷列表的获取方式
            # 检查是否直接是章节列表 (每个元素是一个章节)
            is_direct_chapter_list = 'chapter_con' in (xpath_expr or '')

            if is_direct_chapter_list:
                # book_list_nodes 中的每个 book 就是一个章节的 li 元素
                a_tag = book.xpath('.//a')[0]
                comic_book = ComicBook()
                comic_book.name = a_tag.text.strip()
                # 这种结构下，一个book就是一个vol，没有更细的vols列表
                # 但为了统一数据结构，我们仍将其视为一个book，包含一个vol
                vol_url_part = a_tag.attrib.get('href')
                if vol_url_part:
                    full_vol_url = (
                        self.base_url + vol_url_part
                        if not vol_url_part.startswith('http')
                        else vol_url_part
                    )
                    comic_book.vols.append(
                        ComicVolume(comic_book.name, full_vol_url, comic_book.name)
                    )
                else:
                    logger.warning(f'未找到卷链接 for {comic_book.name} in {url}')
                logger.debug(f'处理单卷章节: {comic_book.name}')
            else:  # 原有的处理逻辑，适用于按卷分组的章节
                # 尝试获取章节分组标题 (如 连载，单行本等)
                title_nodes = book.xpath(
                    './/h2/text() | .//div[contains(@class,"title")]/a/text() | .//span[contains(@class,"title")]/text() | .//h3/text()'
                )
                comic_book = ComicBook()
                if title_nodes:
                    comic_book.name = title_nodes[0].strip()
                else:
                    # 如果 book_list_nodes 是 photo_part, 它本身没有标题，标题在它之前的h2
                    preceding_h2 = book.xpath('preceding-sibling::h2[1]/text()')
                    if preceding_h2:
                        comic_book.name = preceding_h2[0].strip()
                    else:
                        logger.warning(f'未找到明确的章节分组标题，使用默认名称 for {url}')
                        comic_book.name = f'默认卷 {(len(comic.books) + 1)}'
                logger.debug(f'处理章节分组: {comic_book.name}')

            # vol_list = vol_divs[index].xpath('ul/li')
            # 卷列表的Xpath，也需要灵活处理
            # 如果是 photo_part，卷列表在它的兄弟节点 cartoon_online_border 中
            # 如果是 cartoon_online_border，卷列表在它内部的 ul/li
            if not is_direct_chapter_list:
                vol_list_nodes = book.xpath(
                    './/ul[contains(@class,"list_con_li")]/li | .//div[contains(@class,"cartoon_online_border_other")]/ul/li | following-sibling::div[contains(@class,"cartoon_online_border")]/ul/li'
                )
                if (
                    not vol_list_nodes
                    and book.tag == 'div'
                    and 'photo_part' in book.get('class', '')
                ):  # 针对旧版 photo_part 结构
                    vol_list_nodes = book.xpath(
                        'following-sibling::div[contains(@class,"cartoon_online_border")][1]/ul/li'
                    )

                if not vol_list_nodes:
                    logger.warning(f"在章节分组 '{comic_book.name}' 下未找到卷列表: {url}")
                else:
                    for vol_node in vol_list_nodes:
                        a = vol_node.xpath('.//a')[0]
                        vol_name = a.text.strip()
                        vol_url_part = a.attrib.get('href')
                        if vol_url_part:
                            full_vol_url = (
                                self.base_url + vol_url_part
                                if not vol_url_part.startswith('http')
                                else vol_url_part
                            )
                            comic_book.vols.append(
                                ComicVolume(vol_name, full_vol_url, comic_book.name)
                            )
                            logger.debug(f'  找到卷: {vol_name} ({full_vol_url})')
                        else:
                            logger.warning(
                                f'未找到卷链接 for {vol_name} in {comic_book.name} ({url})'
                            )

            # 只有当 comic_book 包含有效的 vols 或者它是直接章节列表时才添加
            if comic_book.vols or is_direct_chapter_list:
                comic.books.append(comic_book)
            elif not is_direct_chapter_list:
                logger.warning(f"章节分组 '{comic_book.name}' 不包含任何有效卷，已跳过.")

        logger.info(f'动漫之家 动漫详细信息获取完成: {comic.name}, 共 {len(comic.books)} 个章节.')
        return comic

    def __parse_imgs__(self, url):
        logger.info(f'开始从 动漫之家 解析图片列表: {url}')
        try:
            self.driver.get(url)
            self.driver.implicitly_wait(10)
            imgs = self.execute_js_safely(self.driver, self.config['imgs_js'], [])
            if imgs and isinstance(imgs, list):
                logger.info(f'成功解析到 {len(imgs)} 张图片来自 {url}')
            else:
                logger.warning(f'未解析到图片链接: {url}')
            return imgs if isinstance(imgs, list) else []
        except Exception as e:
            logger.error(f'使用 Selenium 解析图片列表失败: {url}, 错误: {e}', exc_info=True)
            return []
