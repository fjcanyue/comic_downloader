import json
import re
from io import StringIO

from lxml import etree
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from time import sleep

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger

class DumanwuComic(ComicSource):
    name = '读漫屋'
    base_url = 'https://www.dumanwu.com'
    #base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5
    
    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        self.logger.info(f"开始在 {self.name} 搜索: {keyword}")
        search_url = '%s/s' % self.base_url
        arr = []
        try:
            root = self.__parse_html__(search_url, 'POST', {'k': keyword})
            if root is None:
                self.logger.error(f"搜索 '{keyword}' 失败，无法获取或解析页面: {search_url}")
                return arr
            main_nodes = root.xpath('//div[contains(@class,"view-item")]')
            if not main_nodes:
                self.logger.info(f"在 {self.name} 搜索 '{keyword}' 时未找到主要内容区域，可能无结果或页面结构变更.")
                return arr
            main = main_nodes[0]
            result_count_nodes = main.xpath('//div[@class="item-title"]/span/font')
            if len(result_count_nodes) > 1:
                result_text = result_count_nodes[1].text
                self.logger.info(f"共 {result_text} 条相关的结果")
            else:
                self.logger.info("未找到结果数量信息.")
        except Exception as e:
            self.logger.error(f"在 {self.name} 搜索 '{keyword}' 过程中发生错误: {e}", exc_info=True)
            return arr
        book_list = main.xpath('//div[@class="itemnar"]')
        for book in book_list:
            b = book.xpath('p/a')[0]
            comic = Comic()
            try:
                url_part = b.attrib.get('href')
                if not url_part:
                    self.logger.warning("解析到一个没有URL的漫画条目，已跳过。")
                    continue
                comic.url = '%s%s' % (self.base_url, url_part)
                # 作者信息似乎未在此处直接提供，设为未知
                comic.author = '未知作者'
                comic.name = b.attrib.get('title', '未知漫画')
                self.logger.debug(f"找到漫画: {comic.name}, 作者: {comic.author}, URL: {comic.url}")
                arr.append(comic)
            except Exception as e:
                self.logger.error(f"解析漫画条目时出错: {e}", exc_info=True)
                continue
        self.logger.info(f"{self.name} 搜索 '{keyword}' 完成, 共找到 {len(arr)} 条结果.")
        return arr

    def info(self, url):
        self.logger.info(f"开始获取 {self.name} 动漫详细信息: {url}")
        try:
            root = self.__parse_html__(url)
            if root is None:
                self.logger.error(f"获取动漫详细信息失败，无法获取或解析页面内容: {url}")
                return None
            comic = Comic()
            comic.url = url
            info_div_nodes = root.xpath('//div[contains(@class,"detinfo")]')
            if not info_div_nodes:
                self.logger.error(f"解析动漫信息失败，未找到 'detinfo' 区域: {url}")
                return None
            info_div = info_div_nodes[0]
            name_nodes = info_div.xpath('h1[contains(@class,"name_mh")]')
            if not name_nodes:
                self.logger.error(f"解析动漫名称失败: {url}")
                return None
            comic.name = name_nodes[0].text.strip()
            self.logger.debug(f"动漫名称: {comic.name}")
        except Exception as e:
            self.logger.error(f"获取 {self.name} 动漫详细信息时发生初始错误: {url}, 错误: {e}", exc_info=True)
            return None
        meta_table = info_div.xpath('p/span')
        for meta in meta_table:
            try:
                if meta.text:
                    kvs = meta.text.split('：', 1) # 最多分割一次
                    if len(kvs) == 2:
                        key = kvs[0].strip()
                        value = kvs[1].strip()
                        if key and value:
                            self.logger.debug(f"元数据: {key} - {value}")
                            comic.metadata.append({'k': key, 'v': value})
                        elif key:
                            self.logger.debug(f"元数据项 '{key}' 的值为空.")
                    else:
                        self.logger.warning(f"元数据格式不正确，无法分割键值对: {meta.text}")
                else:
                    self.logger.warning("空的元数据标签.")
            except Exception as e:
                self.logger.warning(f"解析元数据时出错: {etree.tostring(meta, encoding='unicode') if isinstance(meta, etree._Element) else meta}, 错误: {e}", exc_info=True)
                continue
        book_list = root.xpath('//div[contains(@class,"chapterlistload")]')
        book_index = 0
        for book in book_list:
            comic_book = ComicBook()
            comic_book.name = f'章节列表{book_index + 1}' # 为每个章节列表赋予唯一名称
            self.logger.debug(f"处理章节分组: {comic_book.name}")
            vol_list_nodes = book.xpath('ul/a')
            for vol_node in vol_list_nodes:
                try:
                    li_node = vol_node.xpath('li')
                    if not li_node:
                        self.logger.warning(f"卷信息缺少<li>标签: {etree.tostring(vol_node, encoding='unicode')}")
                        continue
                    vol_name = li_node[0].text.strip()
                    vol_url_part = vol_node.attrib.get('href')
                    if not vol_url_part:
                        self.logger.warning(f"卷 '{vol_name}' 的URL部分为空，跳过.")
                        continue
                    full_vol_url = self.base_url + vol_url_part
                    comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
                    self.logger.debug(f"  找到卷 (初始列表): {vol_name} ({full_vol_url})")
                except Exception as e:
                    self.logger.error(f"解析卷 '{vol_name if 'vol_name' in locals() else '未知卷'}' 时出错: {e}", exc_info=True)
            # comic_book.vols.reverse() # 初始列表通常是正序，按需反转
            comic.books.append(comic_book)
            book_index = book_index + 1
            # 加载更多章节的逻辑
            try:
                # 从URL中提取ID，例如 https://www.dumanwu.com/12345/ -> 12345
                # 或者 https://www.dumanwu.com/manhua/12345.html -> 12345
                match = re.search(r'/(\d+)/?$', url) or re.search(r'/(\d+)\.html$', url)
                if not match:
                    self.logger.warning(f"无法从URL {url} 中提取漫画ID以加载更多章节.")
                else:
                    comic_id = match.group(1)
                    payload = {'id': comic_id} # POST请求通常用data参数
                    headers = {
                        'Referer': url,
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest' # 模拟Ajax请求
                    }
                    more_chapters_url = '%s/morechapter' % self.base_url
                    self.logger.debug(f"尝试从 {more_chapters_url} 加载更多章节, ID: {comic_id}")
                    r = self.http.post(more_chapters_url, data=payload, headers=headers, timeout=30)
                    r.raise_for_status()
                    json_response = r.json() # 直接使用 .json() 方法解析
                    if json_response.get('code') == 200 and json_response.get('data'):
                        self.logger.info(f"成功加载了 {len(json_response.get('data'))} 个额外章节.")
                        for chapter_data in json_response.get('data'):
                            chap_name = chapter_data.get('chaptername')
                            chap_id = chapter_data.get('chapterid')
                            if chap_name and chap_id:
                                # 构造章节URL，需要确认是相对路径还是需要拼接
                                # 假设 chapterid 是路径的一部分，例如 /12345/67890.html
                                # 或者 chapterid 直接是完整的路径 /manga/chapter/xxxx.html
                                # 根据网站实际情况调整
                                chap_url = f"{self.base_url}/{comic_id}/{chap_id}.html" # 示例URL构造
                                # 或者如果 chapterid 是完整路径的一部分
                                # chap_url = self.base_url + chap_id if chap_id.startswith('/') else f"{self.base_url}/{chap_id}"
                                comic_book.vols.append(ComicVolume(chap_name, chap_url, comic_book.name))
                                self.logger.debug(f"  找到卷 (更多列表): {chap_name} ({chap_url})")
                    elif json_response.get('code') != 200:
                        self.logger.warning(f"加载更多章节失败: 服务器返回代码 {json_response.get('code')}, 消息: {json_response.get('msg')}")
                    else:
                        self.logger.info("加载更多章节未返回额外数据.")
            except requests.exceptions.RequestException as e:
                self.logger.error(f"请求更多章节失败: {e}", exc_info=True)
            except json.JSONDecodeError as e:
                self.logger.error(f"解析更多章节响应JSON失败: {e}, 响应文本: {r.text[:200]}", exc_info=True) # 只记录部分响应文本
            except Exception as e:
                self.logger.error(f"处理更多章节时发生未知错误: {e}", exc_info=True)
            
            # 确保章节列表是唯一的，并按某种顺序排列（例如，按URL或名称）
            # 这里简单地反转，如果需要更复杂的排序，可以在此实现
            comic_book.vols.reverse() # 反转整个列表（包括初始和更多加载的）
            if comic_book.vols:
                 comic.books.append(comic_book)
            else:
                self.logger.warning(f"章节分组 '{comic_book.name}' 不包含任何有效卷，已跳过.")
        self.logger.info(f"{self.name} 动漫详细信息获取完成: {comic.name}, 共 {len(comic.books)} 个章节分组.")
        return comic

    def __parse_imgs__(self, url):
        logger.info(f"开始从 {self.name} 解析图片列表 (Selenium): {url}")
        img_urls = []
        try:
            self.driver.get(url)
            self.logger.debug(f"页面加载完成, 等待 {self.download_interval} 秒以确保页面完全加载")
            
            # 等待页面初始加载完成的标志，例如某个关键元素出现
            # WebDriverWait(self.driver, 20).until(
            #     EC.presence_of_element_located((By.ID, "mhimg0")) # 假设第一张图片ID是mhimg0
            # )
            # 或者简单等待一段时间
            sleep(self.download_interval) # 使用配置的下载间隔作为初始等待
            
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            self.logger.debug(f"初始页面高度: {last_height}")
            
            scroll_attempts = 0
            max_attempts = 10  # 最大滚动尝试次数
            
            while scroll_attempts < max_attempts:
                # 滚动到页面底部
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.logger.debug(f"滚动到页面底部, 尝试次数: {scroll_attempts + 1}/{max_attempts}")
                
                # 等待页面加载，增加等待时间
                sleep(3)
                
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
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                self.logger.debug(f"新的页面高度: {new_height}")
                
                # 如果页面高度没有变化，并且已经尝试了足够多次，则退出
                if new_height == last_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0  # 如果高度变化，重置计数器
                    
                last_height = new_height
                
                # 每次滚动后检查图片加载状态
                try:
                    WebDriverWait(self.driver, 5).until(
                        lambda x: len([img for img in x.find_elements(By.TAG_NAME, "img") 
                                    if img.get_attribute('src') and 
                                    not img.get_attribute('src').endswith('load.gif') and
                                    img.get_attribute('complete')]) > 0
                    )
                except:
                    self.logger.debug("图片加载未完成，继续滚动.")
                    pass  # 继续滚动即使等待超时
            
            # 最后等待确保图片加载完成
            sleep(5)
            
            # 获取所有图片元素，使用更严格的筛选条件
            image_elements = [img for img in self.driver.find_elements(By.TAG_NAME, "img") 
                    if img.get_attribute('src') and 
                    not img.get_attribute('src').endswith('load.gif') and
                    img.get_attribute('complete') and
                    img.get_attribute('naturalWidth') != '0' and
                    'shimolife.com' in img.get_attribute('src')]

            if not image_elements:
                logger.warning(f"未找到任何图片元素，请检查XPath选择器或页面结构: {url}")
                return []

            logger.debug(f"找到 {len(image_elements)} 个潜在图片元素.")
            img_urls = [img.get_attribute('src') for img in image_elements]
            if img_urls:
                logger.info(f"成功从 {url} 解析到 {len(img_urls)} 张图片.")
            else:
                logger.warning(f"未能从 {url} 解析到任何有效图片链接. 请检查页面结构和懒加载机制.")

        except Exception as e:
            logger.error(f"使用 Selenium 解析图片列表失败: {url}, 错误: {e}", exc_info=True)
        return img_urls
