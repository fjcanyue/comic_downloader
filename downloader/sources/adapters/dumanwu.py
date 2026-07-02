import json
from time import sleep
from urllib.parse import urlparse

import requests
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger

METADATA_PAIR_LENGTH = 2


class DumanwuComic(ComicSource):
    name = '读漫屋'
    base_url = 'https://www.dumanwu.com'
    # base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5
    page_load_wait_seconds = 5
    scroll_wait_seconds = 3
    max_scroll_attempts = 5
    download_requires_driver = True
    config_file = 'dumanwu.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True, *, profile=None):
        super().__init__(output_dir, http, driver, overwrite, profile=profile)

    def search(self, keyword):
        self.logger.info(
            '开始在 {source_name} 搜索: {keyword}', source_name=self.name, keyword=keyword
        )
        search_url = f'{self.base_url}/s'
        arr = []
        try:
            root = self.__parse_html__(search_url, 'POST', {'k': keyword})
            if root is None:
                self.logger.error(
                    "搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}",
                    keyword=keyword,
                    search_url=search_url,
                )
                return arr
            main_nodes = root.xpath('//div[contains(@class,"view-item")]')
            if not main_nodes:
                self.logger.info(
                    "在 {source_name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更.",
                    source_name=self.name,
                    keyword=keyword,
                )
                return arr
            main = main_nodes[0]
            result_count_nodes = main.xpath('//div[@class="item-title"]/span/font')
            if len(result_count_nodes) > 1:
                result_text = result_count_nodes[1].text
                self.logger.info('共 {result_text} 条相关的结果', result_text=result_text)
            else:
                self.logger.info('未找到结果数量信息.')
        except Exception:
            self.logger.exception(
                '在 {source_name} 搜索 "{keyword}" 过程中发生错误',
                source_name=self.name,
                keyword=keyword,
            )
            return arr
        book_list = main.xpath('//div[@class="itemnar"]')
        for book in book_list:
            b = book.xpath('p/a')[0]
            comic = Comic()
            try:
                url_part = b.attrib.get('href')
                if not url_part:
                    self.logger.warning('解析到一个没有URL的漫画条目，已跳过。')
                    continue
                comic.url = f'{self.base_url}{url_part}'
                # 作者信息未在此处直接提供，设为空
                comic.author = ''
                comic.name = b.attrib.get('title', '未知漫画')
                self.logger.debug(
                    '找到漫画: {comic_name}, 作者: {author}, URL: {url}',
                    comic_name=comic.name,
                    author=comic.author,
                    url=comic.url,
                )
                arr.append(comic)
            except Exception as e:
                self.logger.exception('解析漫画条目时出错: {ex}', ex=e)
                continue
        self.logger.info(
            "{source_name} 搜索 '{keyword}' 完成, 共找到 {len} 条结果.",
            source_name=self.name,
            keyword=keyword,
            len=len(arr),
        )
        return arr

    def info(self, url):
        self.logger.info(
            '开始获取 {source_name} 动漫详细信息: {url}', source_name=self.name, url=url
        )
        root = self.__parse_html__(url)
        if root is None:
            self.logger.error('获取动漫详细信息失败，无法获取或解析页面内容: {url}', url=url)
            return None

        comic = self._parse_comic_header(root, url)
        if comic is None:
            return None
        self._append_metadata(root, comic)
        self._append_books(root, comic, url)
        self.logger.info(
            '{source_name} 动漫详细信息获取完成: {comic_name}, 共 {count} 个章节分组.',
            source_name=self.name,
            comic_name=comic.name,
            count=len(comic.books),
        )
        return comic

    def _parse_comic_header(self, root, url):
        try:
            comic = Comic()
            comic.url = url
            info_div_nodes = root.xpath('//div[contains(@class,"detinfo")]')
            if not info_div_nodes:
                self.logger.error("解析动漫信息失败，未找到 'detinfo' 区域: {url}", url=url)
                return None
            info_div = info_div_nodes[0]
            name_nodes = info_div.xpath('h1[contains(@class,"name_mh")]')
            if not name_nodes:
                self.logger.error('解析动漫名称失败: {url}', url=url)
                return None
            comic.name = name_nodes[0].text.strip()
            self.logger.debug('动漫名称: {comic_name}', comic_name=comic.name)
        except Exception as e:
            self.logger.exception(
                '获取 {source_name} 动漫详细信息时发生初始错误: {url}, 错误: {ex}',
                source_name=self.name,
                url=url,
                ex=e,
            )
            return None

        return comic

    def _append_metadata(self, root, comic):
        info_div_nodes = root.xpath('//div[contains(@class,"detinfo")]')
        if not info_div_nodes:
            self.logger.warning('未找到元数据区域.')
            return
        info_div = info_div_nodes[0]
        meta_table = info_div.xpath('p/span')
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            if not meta.text:
                self.logger.warning('空的元数据标签.')
                return
            kvs = meta.text.split('：', 1)
            if len(kvs) != METADATA_PAIR_LENGTH:
                self.logger.warning(
                    '元数据格式不正确，无法分割键值对: {meta_text}', meta_text=meta.text
                )
                return

            key = kvs[0].strip()
            value = kvs[1].strip()
            if key and value:
                self.logger.debug('元数据: {key} - {value}', key=key, value=value)
                comic.metadata.append({'k': key, 'v': value})
            elif key:
                self.logger.debug("元数据项 '{key}' 的值为空.", key=key)
        except Exception as e:
            self.logger.warning(
                '解析元数据时出错: {meta}, 错误: {error}',
                meta=etree.tostring(meta, encoding='unicode')
                if isinstance(meta, etree._Element)
                else meta,
                error=e,
                exc_info=True,
            )

    def _append_books(self, root, comic, url):
        book_list = root.xpath('//div[contains(@class,"chapterlistload")]')
        for book_index, book in enumerate(book_list):
            comic_book = ComicBook()
            comic_book.name = f'章节列表{book_index + 1}'
            self.logger.debug('处理章节分组: %s', comic_book.name)
            self._append_initial_volumes(book, comic_book)
            self._append_more_chapters(book, comic_book, url)
            comic_book.vols.reverse()
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                self.logger.warning(
                    "章节分组 '{book_name}' 不包含任何有效卷，已跳过.", book_name=comic_book.name
                )

    def _append_initial_volumes(self, book, comic_book):
        vol_list_nodes = book.xpath('ul/a')
        for vol_node in vol_list_nodes:
            vol_name = '未知卷'
            try:
                li_node = vol_node.xpath('li')
                if not li_node:
                    self.logger.warning(
                        '卷信息缺少<li>标签: {node}',
                        node=etree.tostring(vol_node, encoding='unicode'),
                    )
                    continue
                li_text = li_node[0].text
                if not li_text:
                    self.logger.warning(
                        '卷名称文本为空: {node}',
                        node=etree.tostring(vol_node, encoding='unicode'),
                    )
                    continue
                vol_name = li_text.strip()
                vol_url_part = vol_node.attrib.get('href')
                if not vol_url_part:
                    self.logger.warning("卷 '{vol_name}' 的URL部分为空，跳过.", vol_name=vol_name)
                    continue
                full_vol_url = self.base_url + vol_url_part
                comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
                self.logger.debug(
                    '  找到卷 (初始列表): {vol_name} ({full_vol_url})',
                    vol_name=vol_name,
                    full_vol_url=full_vol_url,
                )
            except Exception as e:
                self.logger.exception(
                    "解析卷 '{vol_name}' 时出错: {error}", vol_name=vol_name, error=e
                )

    def _append_more_chapters(self, book, comic_book, url):
        response = None
        try:
            more_div = book.xpath('//div[contains(@class,"chaplist-more")]')
            if not more_div:
                self.logger.warning('未找到加载更多章节入口: {url}', url=url)
                return

            parsed_url = urlparse(url)
            comic_id = parsed_url.path.strip('/')
            payload = {'id': comic_id}
            headers = {
                'Referer': url,
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
            }
            more_chapters_url = f'{self.base_url}/morechapter'
            self.logger.debug(
                '尝试从 {more_chapters_url} 加载更多章节, ID: {comic_id}',
                more_chapters_url=more_chapters_url,
                comic_id=comic_id,
            )
            response = self.http.post(more_chapters_url, data=payload, headers=headers, timeout=30)
            response.raise_for_status()
            json_response = response.json()
            self._append_more_chapter_response(comic_book, comic_id, json_response)
        except requests.exceptions.RequestException as e:
            self.logger.exception('请求更多章节失败: {ex}', ex=e)
        except json.JSONDecodeError as e:
            self.logger.exception(
                '解析更多章节响应JSON失败: {ex}, 响应文本: {text}',
                ex=e,
                text=response.text[:200] if response is not None else 'N/A',
            )
        except Exception as e:
            self.logger.exception('处理更多章节时发生未知错误: {ex}', ex=e)

    def _append_more_chapter_response(self, comic_book, comic_id, json_response):
        if json_response.get('code') == '200' and json_response.get('data'):
            chapters = json_response.get('data', [])
            self.logger.info('成功加载了 {count} 个章节', count=len(chapters))
            for chapter_data in chapters:
                chap_name = chapter_data.get('chaptername')
                chap_id = chapter_data.get('chapterid')
                if chap_name and chap_id:
                    chap_url = f'{self.base_url}/{comic_id}/{chap_id}.html'
                    comic_book.vols.append(ComicVolume(chap_name, chap_url, comic_book.name))
                    self.logger.debug(
                        '  找到卷 (更多列表): {chap_name} ({chap_url})',
                        chap_name=chap_name,
                        chap_url=chap_url,
                    )
        elif json_response.get('code') != '200':
            self.logger.warning(
                '加载更多章节失败: 服务器返回代码 {code}, 消息: {msg}',
                code=json_response.get('code'),
                msg=json_response.get('msg'),
            )
        else:
            self.logger.info('加载更多章节未返回额外数据.')

    def __parse_imgs__(self, url):
        logger.info(
            '开始从 {source_name} 解析图片列表 (Selenium): {url}', source_name=self.name, url=url
        )
        img_urls = []
        try:
            self.driver.get(url)
            page_load_wait_seconds = self._page_load_wait_seconds_value(
                default=self.download_interval
            )
            scroll_wait_seconds = self._scroll_wait_seconds_value(default=3)
            max_attempts = self._max_scroll_attempts_value(default=5)
            self.logger.debug(
                '页面加载完成, 等待 {page_load_wait_seconds} 秒以确保页面完全加载',
                page_load_wait_seconds=page_load_wait_seconds,
            )

            # 等待页面初始加载完成的标志，例如某个关键元素出现
            # WebDriverWait(self.driver, 20).until(
            #     EC.presence_of_element_located((By.ID, "mhimg0")) # 假设第一张图片ID是mhimg0
            # )
            # 或者简单等待一段时间
            sleep(page_load_wait_seconds)

            last_height = self.driver.execute_script('return document.body.scrollHeight')
            self.logger.debug('初始页面高度: {last_height}', last_height=last_height)

            scroll_attempts = 0
            while scroll_attempts < max_attempts:
                # 滚动到页面底部
                self.driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                self.logger.debug(
                    '滚动到页面底部, 尝试次数: {scroll_attempts}/{max_attempts}',
                    scroll_attempts=scroll_attempts + 1,
                    max_attempts=max_attempts,
                )

                # 等待页面加载，增加等待时间
                sleep(scroll_wait_seconds)

                # 检查懒加载的图片是否已加载
                self.driver.execute_script("""
                    var images = document.getElementsByTagName('img');
                    for (var i = 0; i < images.length; i++) {
                        var img = images[i];
                        if (img.getAttribute('data-src')) {
                            img.src = img.getAttribute('data-src');
                        }
                    }
                """)

                # 计算新的页面高度
                new_height = self.driver.execute_script('return document.body.scrollHeight')
                self.logger.debug('新的页面高度: {new_height}', new_height=new_height)

                # 如果页面高度没有变化，并且已经尝试了足够多次，则退出
                if new_height == last_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0  # 如果高度变化，重置计数器

                last_height = new_height

                # 每次滚动后检查图片加载状态
                try:
                    WebDriverWait(self.driver, 5).until(
                        lambda x: len(
                            [
                                img
                                for img in x.find_elements(By.TAG_NAME, 'img')
                                if img.get_attribute('src')
                                and not img.get_attribute('src').endswith('load.gif')
                                and img.get_attribute('complete')
                            ]
                        )
                        > 0
                    )
                except Exception:
                    self.logger.debug('图片加载未完成，继续滚动.')
                    # 继续滚动即使等待超时

            # 最后等待确保图片加载完成
            sleep(page_load_wait_seconds)

            # 获取所有图片元素，使用更严格的筛选条件
            image_elements = [
                img
                for img in self.driver.find_elements(By.TAG_NAME, 'img')
                if img.get_attribute('src')
                and not img.get_attribute('src').endswith('load.gif')
                and img.get_attribute('complete')
                and img.get_attribute('naturalWidth') != '0'
                and 'shimolife.com' in img.get_attribute('src')
            ]

            if not image_elements:
                logger.warning('未找到任何图片元素，请检查XPath选择器或页面结构: {url}', url=url)
                return []

            logger.debug('找到 {len} 个潜在图片元素.', len=len(image_elements))
            img_urls = [img.get_attribute('src') for img in image_elements]
            if img_urls:
                logger.info('成功从 {url} 解析到 {len} 张图片.', url=url, len=len(img_urls))
            else:
                logger.warning(
                    '未能从 {} 解析到任何有效图片链接. 请检查页面结构和懒加载机制.', url, url=url
                )

        except Exception as e:
            logger.error('使用 Selenium 解析图片列表失败: {ex}', ex=e, exc_info=True)
        return img_urls
