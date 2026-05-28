from urllib.parse import quote

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser_modes import REQUESTS_MODE
from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class TukuComic(ComicSource):
    name = '图库漫画'
    base_url = 'https://www.tuku.cc'
    browser_mode = REQUESTS_MODE
    download_interval = 2
    config_file = 'tuku.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    @staticmethod
    def _text_content(node):
        """获取节点的全部文本内容（兼容 lxml.etree._Element，不依赖 text_content()）"""
        return ''.join(node.itertext()) if hasattr(node, 'itertext') else (node.text or '')

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/search?title={quote(keyword)}&language=1&f=2'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error("搜索 '{}' 失败，无法获取或解析页面: {}", keyword, search_url)
                return arr

            items = self.parse_xpath_list(
                root, self.config['search_xpath'], self.config['search_extract']
            )
            if not items:
                logger.info(
                    "在 {} 搜索 '{}' 时未找到结果，可能无结果或页面结构变更.",
                    self.name,
                    keyword,
                )
                return arr

            for item in items:
                comic = Comic()
                try:
                    url_part = item.get('url')
                    if not url_part:
                        logger.warning('解析到一个没有URL的漫画条目，已跳过。')
                        continue
                    comic.url = self.base_url + url_part if url_part.startswith('/') else url_part
                    comic.name = item.get('name') or '未知漫画'
                    comic.author = ''
                    logger.debug('找到漫画: {}, URL: {}', comic.name, comic.url)
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
            name_nodes = root.xpath(self.config['info_name_xpath'])
            if not name_nodes:
                logger.error('解析动漫名称失败: {}, 页面结构可能已更改.', url)
                return None
            name_text = name_nodes[0].text
            if not name_text:
                name_text = self._text_content(name_nodes[0])
            comic.name = name_text.strip()
            if not comic.name:
                logger.error('解析动漫名称为空: {}', url)
                return None
            logger.debug('动漫名称: {}', comic.name)
        except Exception as e:
            logger.error(
                '获取 {} 动漫详细信息时发生初始错误: {}, 错误: {}', self.name, url, e, exc_info=True
            )
            return None
        return comic

    def _append_metadata(self, root, comic):
        # 解析作者
        author_nodes = root.xpath(self.config['info_author_xpath'])
        if author_nodes:
            author_text = author_nodes[0].text
            if author_text:
                comic.metadata.append({'k': '作者', 'v': author_text.strip()})
                logger.debug('元数据: 作者 - {}', author_text.strip())

        # 解析状态
        status_nodes = root.xpath(self.config['info_status_xpath'])
        if status_nodes:
            status_full = self._text_content(status_nodes[0]).strip()
            if '状态：' in status_full:
                status_value = status_full.split('状态：', 1)[1].strip()
            elif '状态:' in status_full:
                status_value = status_full.split('状态:', 1)[1].strip()
            else:
                status_value = status_full
            if status_value:
                comic.metadata.append({'k': '状态', 'v': status_value})
                logger.debug('元数据: 状态 - {}', status_value)

        # 解析题材
        genre_nodes = root.xpath(self.config['info_genre_xpath'])
        if genre_nodes:
            genres = []
            for node in genre_nodes:
                genre_text = node.text
                if genre_text:
                    genres.append(genre_text.strip())
            if genres:
                genre_value = ' | '.join(genres)
                comic.metadata.append({'k': '题材', 'v': genre_value})
                logger.debug('元数据: 题材 - {}', genre_value)

    def _append_books(self, root, comic, url):
        comic_book = ComicBook()
        comic_book.name = '连载'

        chapter_nodes = root.xpath(self.config['info_chapters_xpath'])
        if not chapter_nodes:
            logger.warning('未找到章节列表: {}, 页面结构可能已更改.', url)
            return

        for chapter_node in chapter_nodes:
            try:
                # 提取章节名称
                name_nodes = chapter_node.xpath(self.config['info_chapter_extract']['name'])
                vol_name = ''
                if name_nodes:
                    vol_name = name_nodes[0].text.strip() if name_nodes[0].text else ''
                    if not vol_name:
                        vol_name = self._text_content(name_nodes[0]).strip()

                # 提取章节URL
                href = chapter_node.get('href', '')
                if not href:
                    href_nodes = chapter_node.xpath(self.config['info_chapter_extract']['url'])
                    if href_nodes:
                        href = href_nodes[0]

                if not href:
                    logger.warning(
                        '卷信息不完整: {}',
                        etree.tostring(chapter_node, encoding='unicode')[:200],
                    )
                    continue

                if not vol_name:
                    # 尝试从 title 属性获取
                    vol_name = chapter_node.get('title', '').strip()
                if not vol_name:
                    vol_name = '未知章节'

                full_vol_url = (
                    self.base_url + href
                    if href.startswith('/')
                    else href
                    if href.startswith('http')
                    else f'{self.base_url}/{href}'
                )

                comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
                logger.debug('  找到卷: {} ({})', vol_name, full_vol_url)
            except Exception:
                logger.warning(
                    '解析章节条目时出错: {}',
                    etree.tostring(chapter_node, encoding='unicode')[:200]
                    if hasattr(chapter_node, 'getroottree')
                    else str(chapter_node),
                    exc_info=True,
                )
                continue

        comic_book.vols.reverse()
        if comic_book.vols:
            comic.books.append(comic_book)
        else:
            logger.warning('章节分组不包含任何有效卷，已跳过: {}', url)

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片列表: {}', self.name, url)
        try:
            root = self.__parse_html__(url)
            if root is None:
                logger.error('解析图片页面失败，无法获取或解析页面: {}', url)
                return []

            img_urls = root.xpath(self.config['imgs_xpath'])
            if not img_urls:
                logger.warning('未能从页面 {} 解析到任何图片.', url)
                return []

            processed_imgs = [
                img_url
                for img_url in img_urls
                if img_url and isinstance(img_url, str) and img_url.startswith('http')
            ]
            logger.info('成功从 {} 解析并处理了 {} 张图片.', url, len(processed_imgs))
            return processed_imgs
        except Exception as e:
            logger.error('解析图片列表时发生错误: {}, 错误: {}', url, e, exc_info=True)
            return []
