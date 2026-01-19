import concurrent.futures
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from io import StringIO
from pathlib import Path
from time import sleep
from typing import List, Dict, Optional, Any, Union

import requests
from loguru import logger
from lxml import etree
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn


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
    def __init__(self, output_dir: str, http: requests.Session, driver: Any, overwrite: bool = True) -> None:
        """动漫源构造函数

        Args:
            output_dir: 下载根目录
            http: requests 会话对象
            driver: Selenium 网页驱动对象
            overwrite: 是否覆盖已存在的文件
        """
        self.output_dir: str = output_dir
        """下载根目录"""
        self.http: requests.Session = http
        """requests 会话对象"""
        self.driver: Any = driver
        """Selenium 网页驱动对象"""
        self.overwrite: bool = overwrite
        """是否覆盖已存在的文件"""

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

        # comic.py is in downloader/ directory. Project root is one level up.
        current_file = Path(__file__)
        project_root = current_file.parent.parent
        config_path = project_root / 'configs' / self.config_file

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

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeRemainingColumn(),
        ) as progress:
            for book in comic.books:
                book_path = os.path.join(path, filter_dir_name(book.name))
                logger.info(f'处理章节: {book.name}')

                # 创建一个针对该书的任务
                task_id = progress.add_task(description=f"下载 {book.name}", total=len(book.vols))

                for vol in book.vols:
                    try:
                        self.__download_vol__(book_path, vol.name, vol.url, progress)
                        progress.advance(task_id)
                    except Exception as e:
                        logger.error(f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True)

                # 任务完成后移除或保留? 一般保留显示完成状态
                progress.update(task_id, description=f"{book.name} 完成")

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

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeRemainingColumn(),
        ) as progress:
             task_id = progress.add_task(description=f"下载 {book_name}", total=len(vols))
             for vol in vols:
                try:
                    self.__download_vol__(path, vol.name, vol.url, progress)
                    progress.advance(task_id)
                except Exception as e:
                    logger.error(f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True)

    def __download_vol__(self, path: str, vol_name: str, url: str, parent_progress: Optional[Progress] = None) -> None:
        """下载动漫卷/话

        Args:
            path: 下载路径
            vol_name: 动漫卷/话名称
            url: 动漫卷/话URL地址
            parent_progress: 父级进度条对象，用于嵌套显示图片下载进度
        """
        logger.info(f'开始下载卷/话: {vol_name} 从 {url}')

        # 检查文件是否已存在
        if not self.overwrite:
            target_zip_name = filter_dir_name(vol_name) + '.zip'
            target_zip_path = os.path.join(path, target_zip_name)

            # Check basic existence
            if os.path.exists(target_zip_path):
                logger.info(f'文件已存在，跳过: {target_zip_path}')
                return

            # Check padding logic
            # 如果文件名前面是数字，可以补最多两个0，如果补0后有对应zip文件也跳过
            base_name = filter_dir_name(vol_name)
            match = re.match(r'^(\d+)(.*)$', base_name)
            if match:
                num_part = match.group(1)
                rest_part = match.group(2)

                # Try padding with 1 or 2 zeros
                for i in range(1, 3):
                     padded_num = num_part.zfill(len(num_part) + i)
                     padded_name = padded_num + rest_part + '.zip'
                     padded_path = os.path.join(path, padded_name)
                     if os.path.exists(padded_path):
                         logger.info(f'文件已存在(补零匹配)，跳过: {padded_path}')
                         return

        # 添加解析提示任务
        parse_task_id = None
        if parent_progress:
            parse_task_id = parent_progress.add_task(description=f"[yellow]正在解析 {vol_name} 图片...", total=None)
        else:
            print(f"正在解析 {vol_name} 图片...")

        try:
            imgs = self.__parse_imgs__(url)

            # 解析完成后移除解析任务
            if parent_progress and parse_task_id is not None:
                parent_progress.remove_task(parse_task_id)
                parse_task_id = None # 防止在 except 块中再次移除

            if not imgs:
                logger.warning(f'未解析到任何图片: {vol_name} ({url})')
                return
            target_path = os.path.join(path, filter_dir_name(vol_name))
            self.__download_vol_images__(target_path, vol_name, imgs, parent_progress)
            logger.info(f'卷/话 {vol_name} 下载完成.')
        except Exception as e:
            # 异常发生时也要清理任务，并确保不会重复移除
            if parent_progress and parse_task_id is not None:
                 try:
                    parent_progress.remove_task(parse_task_id)
                 except KeyError:
                    pass # 任务可能已经被移除了，忽略错误

            logger.error(f'处理卷/话失败: {vol_name} ({url}), 错误: {e}', exc_info=True)
            raise  # 将异常继续向上抛出，以便上层调用者知道下载失败

    def __download_vol_images__(self, path, vol_name, imgs, progress: Optional[Progress] = None):
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
                # 使用临时 headers，避免修改共享 session
                headers = {'referer': self.base_url}
                # 注意：requests.Session 本身是线程安全的，但如果多个线程同时修改 headers 会有问题。
                # 这里我们调用 get 时不修改 session 的 headers，而是通过参数传入。
                r = self.http.get(full_img_url, timeout=30, headers=headers)
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

        max_workers = getattr(self, 'max_download_workers', 5)

        task_id = None
        if progress:
            task_id = progress.add_task(description=f"  [cyan]{vol_name}", total=len(imgs))

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(download_image, (index, img_url_part))
                    for index, img_url_part in enumerate(imgs)
                ]

                for future in concurrent.futures.as_completed(futures):
                    success, url = future.result()
                    if progress and task_id is not None:
                         progress.advance(task_id)
        finally:
            if progress and task_id is not None:
                 progress.remove_task(task_id)


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

    def __parse_html__(self, url, method='GET', data=None, encoding='utf-8', headers=None):
        """解析HTML

        Args:
            url (str): 动漫卷/话URL地址
            method (str): HTTP方法
            data (dict): POST数据
            encoding (str): 编码
            headers (dict): 请求头

        Returns:
            array: 根元素
        """
        self.logger.debug(f'开始解析HTML: {url}, 方法: {method}')

        request_headers = {'referer': self.base_url}
        if headers:
            request_headers.update(headers)

        try:
            if method == 'GET':
                r = self.http.get(url, timeout=30, headers=request_headers)  # 增加超时
            elif method == 'POST':
                r = self.http.post(url, data=data, timeout=30, headers=request_headers)  # 增加超时
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
