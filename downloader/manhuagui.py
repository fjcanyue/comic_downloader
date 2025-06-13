import re
from io import StringIO

from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger

class ManhuaguiComic(ComicSource):
    name = '看漫画'
    base_url = 'https://www.manhuagui.com/'
    #base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5
    
    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        logger.info(f"开始在 看漫画 搜索: {keyword}")
        search_url = '%s/s/%s.html' % (self.base_url, keyword)
        root = self.__parse_html__(search_url)
        arr = []
        if root is None:
            logger.error(f"搜索失败，无法获取页面内容: {search_url}")
            return arr

        main_nodes = root.xpath('//div[contains(@class,"book-result")]/ul')
        if not main_nodes:
            logger.warning(f"没有找到页面关键元素 (book-result)，搜索可能无结果或页面结构已更改: {search_url}")
            # 尝试查找是否有提示信息，例如 "没有找到xxx相关的漫画"
            no_result_nodes = root.xpath('//div[contains(@class, "no-result")] | //div[contains(text(),"没有找到")]')
            if no_result_nodes:
                no_result_text = no_result_nodes[0].text_content().strip() if hasattr(no_result_nodes[0], 'text_content') else "未找到明确的无结果提示"
                logger.info(f"搜索 '{keyword}' 无结果: {no_result_text}")
            return arr
        
        main = main_nodes[0]
        #result = main.xpath('//em[@class="c_6"]')[0].text
        #print('共 %s 条相关的结果' % result)
        book_list = main.xpath('li')
        for book in book_list:
            b = book.xpath('div/a')[0]
            comic = Comic()
            comic.url = '%s/%s' % (self.base_url, b.attrib.get('href'))
            author_list = book.xpath('div[contains(@class,"book-detail")]/dl/dd[3]/span/a')
            authors = []
            for author in author_list:
                authors.append(author.text)
            comic.author = ', '.join(authors)
            comic.name = b.attrib.get('title')
            logger.debug(f"找到漫画: {comic.name}, 作者: {comic.author}, URL: {comic.url}")
            arr.append(comic)
        logger.info(f"看漫画 搜索 '{keyword}' 完成, 共找到 {len(arr)} 条结果.")
        return arr

    def info(self, url):
        logger.info(f"开始获取 看漫画 动漫详细信息: {url}")
        root = self.__parse_html__(url)
        if root is None:
            logger.error(f"获取动漫详细信息失败，无法获取页面内容: {url}")
            return None
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//div[contains(@class,"book-title")]/h1')[0].text.strip()
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
            logger.debug(f"元数据: {kvs[0]} - {value.strip()}")
            comic.metadata.append({'k': kvs[0], 'v': value.strip()})
        
        book_list_nodes = root.xpath('//div[contains(@class,"chapter-list")]')
        if not book_list_nodes:
            logger.warning(f"未找到章节列表元素: {url}, 页面结构可能已更改或无章节信息.")
            # 即使没有章节列表，也返回已获取的漫画基本信息
            return comic

        book_index = 0
        for book_node in book_list_nodes:
            comic_book = ComicBook()
            try:
                # 尝试更稳健地获取章节标题
                title_node = book_node.xpath('preceding-sibling::h4[1]/span | self::div/h4/span')
                if title_node:
                    comic_book.name = title_node[0].text.strip()
                else: # 如果特定结构找不到，尝试通用一些的父/兄节点标题
                    # 这是一个备用逻辑，可能需要根据实际页面调整
                    fallback_title_nodes = book_node.xpath('../h4/span | ../../h4/span | preceding-sibling::div[contains(@class, "title")]/h4/span')
                    if fallback_title_nodes:
                         comic_book.name = fallback_title_nodes[0].text.strip()
                    else:
                        comic_book.name = f"章节卷 {book_index + 1}" # 默认名称
                logger.debug(f"处理章节: {comic_book.name}")
            except IndexError:
                logger.warning(f"解析章节名称失败，使用默认名称: 章节卷 {book_index + 1} ({url})")
                comic_book.name = f"章节卷 {book_index + 1}"
            vol_list = book.xpath('ul/li')
            for vol in vol_list:
                v = vol.xpath('a')[0]
                comic_book.vols.append(ComicVolume(v.xpath('span')[0].text.strip(), self.base_url + '/' + v.attrib.get('href'), comic_book.name))
            comic_book.vols.reverse() # 保持原有反转逻辑
            comic.books.append(comic_book)
            book_index += 1
        logger.info(f"看漫画 动漫详细信息获取完成: {comic.name}, 共 {len(comic.books)} 个章节.")
        return comic

    def __parse_imgs__(self, url):
        logger.info(f"开始从 看漫画 解析图片列表: {url}")
        try:
            self.driver.get(url)
            # 增加一些等待，确保JS执行环境准备好
            self.driver.implicitly_wait(5) # 隐式等待
            imgs = self.driver.execute_script(
                'var _page = 1;var images = [];while(true) {SMH.utils.goPage(_page);if (pVars.page != _page) {break;}images.push(pVars.curFile);_page++;}return images;')
            if imgs:
                logger.info(f"成功解析到 {len(imgs)} 张图片来自 {url}")
            else:
                logger.warning(f"未解析到任何图片链接来自 {url}, 可能是页面结构变化或JS执行问题.")
            return imgs
        except Exception as e:
            logger.error(f"使用 Selenium 解析图片列表失败: {url}, 错误: {e}", exc_info=True)
            return [] # 返回空列表表示失败
