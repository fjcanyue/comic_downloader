import concurrent.futures
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from io import StringIO
from time import sleep
from typing import List, Dict, Optional, Any, Union

import requests
from loguru import logger
from lxml import etree
from tqdm import tqdm

# 配置 loguru 日志记录器
# loguru 默认会输出到 stderr，并且包含时间、级别、模块、行号等信息
# 可以根据需要添加或移除 sink，或修改格式
# logger.add("comic_downloader.log", rotation="500 MB") # 输出到文件，并按大小轮转
# logger.remove() # 移除默认的 stderr 输出
# logger.add(sys.stderr, format="{time} {level} {message}") # 添加自定义格式的 stderr 输出


class ComicVolume:
    def __init__(self, name: str, url: str, book_name: Optional[str] = None) -> None:
        self.name: str = name
        self.url: str = url
        self.book_name: Optional[str] = book_name


class ComicBook:
    def __init__(self) -> None:
        self.name: Optional[str] = None
        self.vols: List[ComicVolume] = []


class Comic:
    def __init__(self) -> None:
        self.name: Optional[str] = None
        self.author: Optional[str] = None
        self.url: Optional[str] = None
        self.source: Optional[str] = None
        self.metadata: List[Dict[str, str]] = []
        self.books: List[ComicBook] = []


filter_dir_re = re.compile(r'[\/:*?"<>|]')


def filter_dir_name(name: str) -> str:
    return re.sub(filter_dir_re, '-', name)


class ComicSource(ABC):
    def __init__(self, output_dir: str, http: requests.Session, driver: Any) -> None:
        """动漫源构造函数

        Args:
            output_dir: 下载根目录
            http: requests 会话对象
            driver: Selenium 网页驱动对象
        """
        self.output_dir: str = output_dir
        """下载根目录"""
        self.http: requests.Session = http
        """requests 会话对象"""
        self.driver: Any = driver
        """Selenium 网页驱动对象"""

        self.http.headers.update({'referer': self.base_url})

        self.parser: etree.HTMLParser = etree.HTMLParser()
        self.logger = logger

        # Load configuration if config_file is specified
        if hasattr(self, 'config_file') and self.config_file:
            self.load_config()
        elif hasattr(self, 'config') and self.config:
             # Already has config (maybe hardcoded), do nothing or validate
             pass
        else:
             self.config = {}

    def load_config(self):
        """Load configuration from the configs directory."""
        # Assuming configs are stored in 'configs/' directory at the project root
        # We can find the project root relative to this file

        # comic.py is in downloader/ directory. Project root is one level up.
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        config_path = os.path.join(project_root, 'configs', self.config_file)

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.logger.debug(f"Loaded config from {config_path}")
        except FileNotFoundError:
            self.logger.error(f"Config file not found: {config_path}")
            self.config = {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from {config_path}: {e}")
            self.config = {}
        except Exception as e:
             self.logger.error(f"Unexpected error loading config {config_path}: {e}")
             self.config = {}


    @abstractmethod
    def search(self, keyword: str) -> List[Comic]:
        """搜索动漫

        Args:
            keyword: 搜索关键字

        Returns:
            搜索结果列表
        """

    @abstractmethod
    def info(self, url: str) -> Optional[Comic]:
        """查看动漫详细信息

        Args:
            url: 动漫URL地址
        """

    def download_full_by_url(self, url: str) -> None:
        """全量下载指定动漫

        Args:
            url: 动漫URL地址
        """
        self.logger.debug(f'开始全量下载动漫: {url}')
        try:
            comic_info = self.info(url)
            if comic_info:
                self.download_full(comic_info)
                logger.info(f'动漫 {comic_info.name} 全量下载完成')  # 直接使用全局 logger
            else:
                logger.error(f'获取动漫信息失败: {url}')
        except Exception as e:
            logger.error(f'全量下载动漫失败: {url}, 错误: {e}', exc_info=True)

    def download_full(self, comic: Comic) -> None:
        """全量下载指定动漫

        Args:
            comic: 动漫对象
        """
        path = os.path.join(self.output_dir, filter_dir_name(comic.name))
        logger.info(f'创建动漫目录: {path}')
        os.makedirs(path, exist_ok=True)
        for book in comic.books:
            book_path = os.path.join(path, filter_dir_name(book.name))
            logger.info(f'处理章节: {book.name}')
            for vol in tqdm(book.vols, desc=book.name):
                try:
                    self.__download_vol__(book_path, vol.name, vol.url)
                except Exception as e:
                    logger.error(f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True)

    @abstractmethod
    def __parse_imgs__(self, url):
        """从动漫卷/话页面解析动漫图片URL地址数组

        Args:
            url (str): 动漫卷/话URL地址

        Returns:
            array: 图片URL地址数组
        """

    def download_vols(self, comic_name: str, book_name: str, vols: List[ComicVolume]) -> None:
        """按指定范围下载动漫

        Args:
            comic_name: 动漫名称
            book_name: 动漫章节名称
            vols: 待下载的动漫卷/话列表
        """
        path = os.path.join(
            self.output_dir, filter_dir_name(comic_name), filter_dir_name(book_name)
        )
        logger.info(f'创建章节目录: {path} 用于下载指定卷/话')
        os.makedirs(path, exist_ok=True)
        for vol in tqdm(vols, desc=book_name):
            try:
                self.__download_vol__(path, vol.name, vol.url)
            except Exception as e:
                logger.error(f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True)

    def __download_vol__(self, path: str, vol_name: str, url: str) -> None:
        """下载动漫卷/话

        Args:
            path: 下载路径
            vol_name: 动漫卷/话名称
            url: 动漫卷/话URL地址
        """
        logger.info(f'开始下载卷/话: {vol_name} 从 {url}')
        try:
            imgs = self.__parse_imgs__(url)
            if not imgs:
                logger.warning(f'未解析到任何图片: {vol_name} ({url})')
                return
            target_path = os.path.join(path, filter_dir_name(vol_name))
            self.__download_vol_images__(target_path, vol_name, imgs)
            logger.info(f'卷/话 {vol_name} 下载完成.')
        except Exception as e:
            logger.error(f'处理卷/话失败: {vol_name} ({url}), 错误: {e}', exc_info=True)
            raise  # 将异常继续向上抛出，以便上层调用者知道下载失败

    def __download_vol_images__(self, path, vol_name, imgs):
        """下载图片"""
        logger.info(f'开始下载图片到目录: {path} (共 {len(imgs)} 张)')
        os.makedirs(path, exist_ok=True)
        use_uri = hasattr(self, 'base_img_url')

        def download_image(args):
            index, img_url_part = args
            sleep(self.download_interval)  # 保持下载间隔，避免对服务器造成过大压力
            file_path = '%s/%04d.jpg' % (path, (index + 1))
            full_img_url = ''
            if use_uri and not img_url_part.startswith('http'):
                if img_url_part.startswith('/'):
                    full_img_url = self.base_img_url + img_url_part
                else:
                    full_img_url = self.base_img_url + '/' + img_url_part
            else:
                full_img_url = img_url_part

            logger.debug(f'下载图片: {full_img_url} 到 {file_path}')
            try:
                # 注意：requests.Session 不是线程安全的，如果 http 对象是 Session，并发下载时需要为每个线程创建独立的 Session
                # 或者使用线程安全的 HTTP 客户端库。此处假设 self.http.get 是线程安全的，或者不是 Session 对象。
                # 如果 self.http 是 requests.Session()，则需要调整为在 download_image 内部创建 session
                # import requests
                # r = requests.get(full_img_url, timeout=30, headers=getattr(self.http, 'headers', {}))
                r = self.http.get(full_img_url, timeout=30)
                r.raise_for_status()
                with open(file_path, 'wb') as f:
                    f.write(r.content)
                logger.debug(f'图片 {file_path} 下载成功.')
                return True, full_img_url
            except requests.exceptions.RequestException as e:
                logger.error(f'下载图片失败: {full_img_url}, 错误: {e}')
                return False, full_img_url
            except OSError as e:
                logger.error(f'写入图片文件失败: {file_path}, 错误: {e}')
                return False, full_img_url

        # 使用 ThreadPoolExecutor 进行并发下载，可以根据需要调整 max_workers
        # 例如，如果 self.http 是 requests.Session，则 max_workers 应该较小，或者在 download_image 中创建新的 Session
        # 默认的 max_workers 通常是 os.cpu_count() * 5
        # 对于IO密集型任务，可以设置稍大一些的 worker 数量
        # 考虑到下载间隔，worker 数量不宜过大，以免实际并发效果不佳或被目标网站限制
        # 假设一个合理的并发数为 5 到 10，具体取决于 self.download_interval 的值
        # 如果 download_interval 较大，则并发数意义不大
        # 如果 download_interval 较小或为0，则可以适当增加并发数
        # 这里暂时设置为5，可以根据实际情况调整
        max_workers = getattr(self, 'max_download_workers', 5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 使用 tqdm 显示进度
            futures = [
                executor.submit(download_image, (index, img_url_part))
                for index, img_url_part in enumerate(imgs)
            ]
            for future in tqdm(
                concurrent.futures.as_completed(futures), total=len(imgs), desc=vol_name
            ):
                success, url = future.result()
                # 可以在这里处理下载失败的情况，例如记录失败的URL列表

        if os.path.exists(path) and os.listdir(path):  # 仅当目录存在且非空时创建压缩文件
            logger.info(f'开始压缩目录: {path}')
            try:
                shutil.make_archive(path, 'zip', path)
                logger.info(f'目录 {path} 压缩完成.')
            except Exception as e:
                logger.error(f'压缩目录失败: {path}, 错误: {e}', exc_info=True)
        elif not os.path.exists(path):
            logger.warning(f'目录 {path} 不存在, 跳过压缩.')
        else:
            logger.warning(f'目录 {path} 为空, 跳过压缩.')

    def parse_xpath_list(self, root, xpath, extract_map):
        """通用XPath列表解析方法

        Args:
            root: etree根元素
            xpath (str): XPath表达式
            extract_map (dict): 提取映射，如 {'name': './@title', 'url': './@href'}

        Returns:
            list: 提取的数据字典列表
        """
        results = []
        try:
            nodes = root.xpath(xpath)
            for node in nodes:
                item = {}
                for key, expr in extract_map.items():
                    try:
                        if expr.startswith('./@'):
                            vals = node.xpath(expr)
                            item[key] = vals[0] if vals else None
                        elif expr == './text()':
                            item[key] = node.text.strip() if node.text else None
                        else:
                            vals = node.xpath(expr)
                            if vals:
                                text_node = vals[0]
                                item[key] = (
                                    text_node.text.strip()
                                    if hasattr(text_node, 'text') and text_node.text
                                    else text_node
                                )
                            else:
                                item[key] = None
                    except Exception as e:
                        self.logger.debug(f'提取 {key} 时出错: {e}')
                        item[key] = None
                results.append(item)
        except Exception as e:
            self.logger.error(f'XPath解析失败: {xpath}, 错误: {e}')
        return results

    def execute_js_safely(self, driver, js_code, fallback=None):
        """安全执行JavaScript代码

        Args:
            driver: Selenium WebDriver
            js_code (str): JS代码
            fallback: 默认返回值

        Returns:
            执行结果或fallback
        """
        try:
            # 简单验证JS代码，避免明显注入
            if not js_code or 'eval(' in js_code:
                self.logger.warning(f'潜在不安全JS代码: {js_code}')
                return fallback
            result = driver.execute_script(js_code)
            return result
        except Exception as e:
            self.logger.error(f'JS执行失败: {js_code}, 错误: {e}')
            return fallback

    def __parse_html__(self, url, method='GET', data=None, encoding='utf-8'):
        """解析HTML

        Args:
            url (str): 动漫卷/话URL地址

        Returns:
            array: 根元素
        """
        self.logger.debug(f'开始解析HTML: {url}, 方法: {method}')
        try:
            if method == 'GET':
                r = self.http.get(url, timeout=30)  # 增加超时
            elif method == 'POST':
                r = self.http.post(url, data=data, timeout=30)  # 增加超时
            else:
                logger.error(f'不支持的HTTP方法: {method}')
                return None
            r.raise_for_status()  # 如果请求失败则抛出HTTPError异常
            r.encoding = encoding
            return etree.parse(StringIO(r.text), self.parser)
        except requests.exceptions.RequestException as e:
            logger.error(f'请求HTML页面失败: {url}, 方法: {method}, 错误: {e}', exc_info=True)
            return None
        except Exception as e:
            logger.error(f'处理HTML页面时发生未知错误: {url}, 错误: {e}', exc_info=True)
            return None
