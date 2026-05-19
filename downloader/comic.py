import concurrent.futures
import json
import os
import re
import shutil
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

import requests
from loguru import logger
from lxml import etree
from rich.progress import BarColumn, Progress, TextColumn


class ComicVolume:
    def __init__(self, name: str, url: str, book_name: str | None = None) -> None:
        self.name: str = name
        self.url: str = url
        self.book_name: str | None = book_name


class ComicBook:
    def __init__(self) -> None:
        self.name: str | None = None
        self.vols: list[ComicVolume] = []


class Comic:
    def __init__(self) -> None:
        self.name: str | None = None
        self.author: str | None = None
        self.url: str | None = None
        self.source: str | None = None
        self.metadata: list[dict[str, str]] = []
        self.books: list[ComicBook] = []


@dataclass(frozen=True)
class ImageDownloadFailure:
    index: int
    url: str
    file_path: str
    error: str


@dataclass
class VolumeDownloadResult:
    name: str
    url: str
    status: str
    image_count: int = 0
    downloaded_count: int = 0
    failed_images: list[ImageDownloadFailure] = field(default_factory=list)
    archive_path: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {'downloaded', 'skipped'}


@dataclass
class DownloadSummary:
    volume_results: list[VolumeDownloadResult] = field(default_factory=list)

    def add(self, result: VolumeDownloadResult) -> None:
        self.volume_results.append(result)

    @property
    def total_volumes(self) -> int:
        return len(self.volume_results)

    @property
    def downloaded(self) -> int:
        return sum(1 for result in self.volume_results if result.status == 'downloaded')

    @property
    def skipped(self) -> int:
        return sum(1 for result in self.volume_results if result.status == 'skipped')

    @property
    def failed(self) -> int:
        return sum(1 for result in self.volume_results if result.status == 'failed')

    @property
    def partial(self) -> int:
        return sum(1 for result in self.volume_results if result.status == 'partial')

    @property
    def ok(self) -> bool:
        return self.total_volumes > 0 and self.failed == 0 and self.partial == 0


filter_dir_re = re.compile(r'[\/:*?"<>|]')


def filter_dir_name(name: str) -> str:
    return re.sub(filter_dir_re, '-', name)


class ComicSource(ABC):
    base_url: str = ''
    base_img_url: str = ''
    config_file: str | None = None
    download_interval: float = 0
    image_retry_count: int = 1
    max_download_workers: int = 5
    enable: bool = True

    def __init__(
        self, output_dir: str, http: requests.Session, driver: Any, overwrite: bool = True
    ) -> None:
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
        config_file = self.config_file
        if not config_file:
            self.config = {}
            return

        if getattr(sys, 'frozen', False):
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            meipass = getattr(sys, '_MEIPASS', None)
            base_path = Path(meipass) if meipass else Path(__file__).parent.parent
        else:
            # comic.py is in downloader/ directory. Project root is one level up.
            base_path = Path(__file__).parent.parent

        config_path = base_path / 'configs' / config_file

        try:
            with open(config_path, encoding='utf-8') as f:
                self.config = json.load(f)
            self.logger.debug(f'Loaded config from {config_path}')
        except FileNotFoundError:
            self.logger.error(f'Config file not found: {config_path}')
            self.config = {}
        except json.JSONDecodeError as e:
            self.logger.error(f'Error decoding JSON from {config_path}: {e}')
            self.config = {}
        except Exception as e:
            self.logger.error(f'Unexpected error loading config {config_path}: {e}')
            self.config = {}

    @abstractmethod
    def search(self, keyword: str) -> list[Comic]:
        """搜索动漫

        Args:
            keyword: 搜索关键字

        Returns:
            搜索结果列表
        """

    @abstractmethod
    def info(self, url: str) -> Comic | None:
        """查看动漫详细信息

        Args:
            url: 动漫URL地址
        """

    def download_full_by_url(self, url: str) -> DownloadSummary:
        """全量下载指定动漫

        Args:
            url: 动漫URL地址
        """
        self.logger.debug(f'开始全量下载动漫: {url}')
        summary = DownloadSummary()
        try:
            comic_info = self.info(url)
            if comic_info:
                summary = self.download_full(comic_info)
                if summary.ok:
                    logger.info(f'动漫 {comic_info.name} 全量下载完成')  # 直接使用全局 logger
                else:
                    logger.warning(
                        f'动漫 {comic_info.name} 下载完成但存在失败: '
                        f'失败 {summary.failed}, 部分失败 {summary.partial}'
                    )
            else:
                logger.error(f'获取动漫信息失败: {url}')
                summary.add(
                    VolumeDownloadResult(
                        name=url,
                        url=url,
                        status='failed',
                        message='获取动漫信息失败',
                    )
                )
        except Exception as e:
            logger.error(f'全量下载动漫失败: {url}, 错误: {e}', exc_info=True)
            summary.add(
                VolumeDownloadResult(name=url, url=url, status='failed', message=str(e))
            )
        return summary

    def download_full(self, comic: Comic) -> DownloadSummary:
        """全量下载指定动漫

        Args:
            comic: 动漫对象
        """
        path = os.path.join(self.output_dir, filter_dir_name(comic.name or '未知动漫'))
        logger.info(f'创建动漫目录: {path}')
        os.makedirs(path, exist_ok=True)
        summary = DownloadSummary()

        with Progress(
            TextColumn('[progress.description]{task.description}'),
            BarColumn(),
            '[progress.percentage]{task.percentage:>3.0f}%',
        ) as progress:
            for book in comic.books:
                book_path = os.path.join(path, filter_dir_name(book.name or '默认章节'))
                logger.info(f'处理章节: {book.name}')

                # 创建一个针对该书的任务
                task_id = progress.add_task(description=f'下载 {book.name}', total=len(book.vols))

                for vol in book.vols:
                    try:
                        result = self.__download_vol__(book_path, vol.name, vol.url, progress)
                    except Exception as e:
                        logger.error(
                            f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True
                        )
                        result = VolumeDownloadResult(
                            name=vol.name,
                            url=vol.url,
                            status='failed',
                            message=str(e),
                        )
                    summary.add(result)
                    progress.advance(task_id)

                # 任务完成后移除或保留? 一般保留显示完成状态
                progress.update(task_id, description=f'{book.name} 完成')
        return summary

    @abstractmethod
    def __parse_imgs__(self, url) -> list[str]:
        """从动漫卷/话页面解析动漫图片URL地址数组

        Args:
            url (str): 动漫卷/话URL地址

        Returns:
            array: 图片URL地址数组
        """

    def download_vols(
        self, comic_name: str, book_name: str, vols: list[ComicVolume]
    ) -> DownloadSummary:
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
        summary = DownloadSummary()

        with Progress(
            TextColumn('[progress.description]{task.description}'),
            BarColumn(),
            '[progress.percentage]{task.percentage:>3.0f}%',
        ) as progress:
            task_id = progress.add_task(description=f'下载 {book_name}', total=len(vols))
            for vol in vols:
                try:
                    result = self.__download_vol__(path, vol.name, vol.url, progress)
                except Exception as e:
                    logger.error(f'下载卷/话失败: {vol.name} ({vol.url}), 错误: {e}', exc_info=True)
                    result = VolumeDownloadResult(
                        name=vol.name,
                        url=vol.url,
                        status='failed',
                        message=str(e),
                    )
                summary.add(result)
                progress.advance(task_id)
        return summary

    def __download_vol__(
        self, path: str, vol_name: str, url: str, parent_progress: Progress | None = None
    ) -> VolumeDownloadResult:
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
                return VolumeDownloadResult(
                    name=vol_name,
                    url=url,
                    status='skipped',
                    archive_path=target_zip_path,
                    message='文件已存在',
                )

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
                        return VolumeDownloadResult(
                            name=vol_name,
                            url=url,
                            status='skipped',
                            archive_path=padded_path,
                            message='文件已存在',
                        )

        # 添加解析提示任务
        parse_task_id = None
        if parent_progress:
            parse_task_id = parent_progress.add_task(
                description=f'[yellow]正在解析 {vol_name} 图片...', total=None
            )
        else:
            print(f'正在解析 {vol_name} 图片...')

        try:
            imgs = self.__parse_imgs__(url)

            # 解析完成后移除解析任务
            if parent_progress and parse_task_id is not None:
                parent_progress.remove_task(parse_task_id)
                parse_task_id = None  # 防止在 except 块中再次移除

            if not imgs:
                logger.warning(f'未解析到任何图片: {vol_name} ({url})')
                return VolumeDownloadResult(
                    name=vol_name,
                    url=url,
                    status='failed',
                    message='未解析到任何图片',
                )
            target_path = os.path.join(path, filter_dir_name(vol_name))
            result = self.__download_vol_images__(
                target_path, vol_name, url, imgs, parent_progress
            )
            if result.ok:
                logger.info(f'卷/话 {vol_name} 下载完成.')
            else:
                logger.warning(
                    f'卷/话 {vol_name} 下载未完全成功: 状态={result.status}, '
                    f'成功图片={result.downloaded_count}/{result.image_count}'
                )
            return result
        except Exception as e:
            # 异常发生时也要清理任务，并确保不会重复移除
            if parent_progress and parse_task_id is not None:
                try:
                    parent_progress.remove_task(parse_task_id)
                except KeyError:
                    pass  # 任务可能已经被移除了，忽略错误

            logger.error(f'处理卷/话失败: {vol_name} ({url}), 错误: {e}', exc_info=True)
            return VolumeDownloadResult(name=vol_name, url=url, status='failed', message=str(e))

    def __download_vol_images__(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        imgs: list[str],
        progress: Progress | None = None,
    ) -> VolumeDownloadResult:
        """下载图片"""
        logger.info(f'开始下载图片到目录: {path} (共 {len(imgs)} 张)')
        os.makedirs(path, exist_ok=True)
        use_uri = hasattr(self, 'base_img_url')
        failed_images: list[ImageDownloadFailure] = []
        rate_lock = threading.Lock()
        http_lock = threading.Lock()
        last_request_at = [0.0]

        def wait_for_download_slot() -> None:
            interval = getattr(self, 'download_interval', 0)
            if interval <= 0:
                return
            with rate_lock:
                now = time.monotonic()
                elapsed = now - last_request_at[0]
                if last_request_at[0] > 0 and elapsed < interval:
                    time.sleep(interval - elapsed)
                last_request_at[0] = time.monotonic()

        def build_image_url(img_url_part: str) -> str:
            if use_uri and not img_url_part.startswith('http'):
                if img_url_part.startswith('/'):
                    return self.base_img_url + img_url_part
                return self.base_img_url + '/' + img_url_part
            return img_url_part

        def download_image(args):
            index, img_url_part = args
            file_path = os.path.join(path, f'{index + 1:04d}.jpg')
            tmp_path = file_path + '.tmp'
            full_img_url = build_image_url(img_url_part)
            retry_count = getattr(self, 'image_retry_count', 1)
            last_error = ''

            logger.debug(f'下载图片: {full_img_url} 到 {file_path}')
            for attempt in range(1, retry_count + 2):
                response = None
                try:
                    wait_for_download_slot()
                    headers = {'referer': self.base_url}
                    with http_lock:
                        response = self.http.get(
                            full_img_url,
                            timeout=30,
                            headers=headers,
                            stream=True,
                        )
                    response.raise_for_status()
                    with open(tmp_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                f.write(chunk)
                    os.replace(tmp_path, file_path)
                    logger.debug(f'图片 {file_path} 下载成功.')
                    return None
                except (requests.exceptions.RequestException, OSError) as e:
                    last_error = str(e)
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            logger.warning(f'清理临时文件失败: {tmp_path}', exc_info=True)
                    if attempt <= retry_count:
                        logger.warning(
                            f'下载图片失败，将重试: {full_img_url}, '
                            f'第 {attempt}/{retry_count + 1} 次, 错误: {e}'
                        )
                    else:
                        logger.error(f'下载图片失败: {full_img_url}, 错误: {e}')
                finally:
                    if response is not None and hasattr(response, 'close'):
                        response.close()
            return ImageDownloadFailure(index + 1, full_img_url, file_path, last_error)

        max_workers = getattr(self, 'max_download_workers', 5)

        task_id = None
        if progress:
            task_id = progress.add_task(description=f'  [cyan]{vol_name}', total=len(imgs))

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [
                executor.submit(download_image, (index, img_url_part))
                for index, img_url_part in enumerate(imgs)
            ]

            for future in concurrent.futures.as_completed(futures):
                failure = future.result()
                if failure:
                    failed_images.append(failure)
                if progress and task_id is not None:
                    progress.advance(task_id)
            executor.shutdown(wait=True)
        except (KeyboardInterrupt, SystemExit):
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        except:
            executor.shutdown(wait=True)
            raise
        finally:
            if progress and task_id is not None:
                progress.remove_task(task_id)

        if os.path.exists(path) and os.listdir(
            path
        ):  # 仅当目录存在且非空，图片数量相同时创建压缩文件
            # 检查实际下载的图片数量是否与预期相同
            actual_files = sorted(os.listdir(path))
            expected_count = len(imgs)
            actual_count = len(actual_files)
            downloaded_count = expected_count - len(failed_images)

            if expected_count == actual_count and not failed_images:
                logger.info(f'开始压缩目录: {path}')
                try:
                    archive_path = shutil.make_archive(path, 'zip', path)
                    logger.info(f'目录 {path} 压缩完成.')
                    return VolumeDownloadResult(
                        name=vol_name,
                        url=source_url,
                        status='downloaded',
                        image_count=expected_count,
                        downloaded_count=downloaded_count,
                        archive_path=archive_path,
                    )
                except Exception as e:
                    logger.error(f'压缩目录失败: {path}, 错误: {e}', exc_info=True)
                    return VolumeDownloadResult(
                        name=vol_name,
                        url=source_url,
                        status='failed',
                        image_count=expected_count,
                        downloaded_count=downloaded_count,
                        failed_images=failed_images,
                        message=f'压缩目录失败: {e}',
                    )
            else:
                # 计算缺少的文件
                missing_files = []
                for i in range(1, expected_count + 1):
                    expected_filename = f'{i:04d}.jpg'
                    if expected_filename not in actual_files:
                        missing_files.append(expected_filename)

                logger.warning(
                    f'目录 {path} 图片数量不匹配，跳过压缩. '
                    f'预期 {expected_count} 张，实际 {actual_count} 张. '
                    f'缺少文件: {missing_files}'
                )
                status = 'partial' if downloaded_count > 0 else 'failed'
                return VolumeDownloadResult(
                    name=vol_name,
                    url=source_url,
                    status=status,
                    image_count=expected_count,
                    downloaded_count=downloaded_count,
                    failed_images=failed_images,
                    message='图片数量不匹配，跳过压缩',
                )
        elif not os.path.exists(path):
            logger.warning(f'目录 {path} 不存在, 跳过压缩.')
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='failed',
                image_count=len(imgs),
                downloaded_count=0,
                failed_images=failed_images,
                message='目录不存在',
            )
        else:
            logger.warning(f'目录 {path} 为空, 跳过压缩.')
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='failed',
                image_count=len(imgs),
                downloaded_count=0,
                failed_images=failed_images,
                message='目录为空',
            )

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
