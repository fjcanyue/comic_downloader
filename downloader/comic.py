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
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from rich.progress import BarColumn, Progress, TextColumn
from seleniumbase import SB


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
class ImageDownloadContext:
    path: str
    use_base_img_url: bool
    rate_lock: threading.Lock = field(default_factory=threading.Lock)
    http_lock: threading.Lock = field(default_factory=threading.Lock)
    last_request_at: list[float] = field(default_factory=lambda: [0.0])


@dataclass(frozen=True)
class VolumeFileState:
    downloaded_count: int
    failed_images: list[ImageDownloadFailure]
    actual_files: list[str]
    actual_count: int


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
    download_requires_driver: bool = False
    image_retry_count: int = 1
    max_download_workers: int = 5
    enable: bool = True
    seleniumbase_headless: bool | None = None
    seleniumbase_wait_selector: str | None = None
    seleniumbase_wait_seconds: float = 20.0

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
            self.logger.debug('Loaded config from {config_path}', config_path=config_path)
        except FileNotFoundError:
            self.logger.error('Config file not found: {config_path}', config_path=config_path)
            self.config = {}
        except json.JSONDecodeError as e:
            self.logger.error(
                'Error decoding JSON from {config_path}: {error}',
                config_path=config_path,
                error=e,
            )
            self.config = {}
        except Exception as e:
            self.logger.error(
                'Unexpected error loading config {config_path}: {error}',
                config_path=config_path,
                error=e,
            )
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
        self.logger.debug('开始全量下载动漫: {url}', url=url)
        summary = DownloadSummary()
        try:
            comic_info = self.info(url)
            if comic_info:
                summary = self.download_full(comic_info)
                if summary.ok:
                    logger.info('动漫 {} 全量下载完成', comic_info.name)  # 直接使用全局 logger
                else:
                    logger.warning(
                        '动漫 {} 下载完成但存在失败: 失败 {}, 部分失败 {}',
                        comic_info.name,
                        summary.failed,
                        summary.partial,
                    )
            else:
                logger.error('获取动漫信息失败: {}', url)
                summary.add(
                    VolumeDownloadResult(
                        name=url,
                        url=url,
                        status='failed',
                        message='获取动漫信息失败',
                    )
                )
        except Exception as e:
            logger.error('全量下载动漫失败: {}, 错误: {}', url, e, exc_info=True)
            summary.add(VolumeDownloadResult(name=url, url=url, status='failed', message=str(e)))
        return summary

    def download_full(self, comic: Comic) -> DownloadSummary:
        """全量下载指定动漫

        Args:
            comic: 动漫对象
        """
        path = os.path.join(self.output_dir, filter_dir_name(comic.name or '未知动漫'))
        logger.info('创建动漫目录: {}', path)
        os.makedirs(path, exist_ok=True)
        summary = DownloadSummary()

        with Progress(
            TextColumn('[progress.description]{task.description}'),
            BarColumn(),
            '[progress.percentage]{task.percentage:>3.0f}%',
        ) as progress:
            for book in comic.books:
                book_path = os.path.join(path, filter_dir_name(book.name or '默认章节'))
                logger.info('处理章节: {}', book.name)

                # 创建一个针对该书的任务
                task_id = progress.add_task(description=f'下载 {book.name}', total=len(book.vols))

                for vol in book.vols:
                    try:
                        result = self.__download_vol__(book_path, vol.name, vol.url, progress)
                    except Exception as e:
                        logger.error(
                            '下载卷/话失败: {} ({}), 错误: {}', vol.name, vol.url, e, exc_info=True
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
        logger.info('创建章节目录: {} 用于下载指定卷/话', path)
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
                    logger.error(
                        '下载卷/话失败: {} ({}), 错误: {}', vol.name, vol.url, e, exc_info=True
                    )
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
        logger.info('开始下载卷/话: {} 从 {}', vol_name, url)

        # 检查文件是否已存在
        existing_archive_path = self._find_existing_archive(path, vol_name)
        if existing_archive_path:
            logger.info('文件已存在，跳过: {}', existing_archive_path)
            return VolumeDownloadResult(
                name=vol_name,
                url=url,
                status='skipped',
                archive_path=existing_archive_path,
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
                logger.warning('未解析到任何图片: {} ({})', vol_name, url)
                return VolumeDownloadResult(
                    name=vol_name,
                    url=url,
                    status='failed',
                    message='未解析到任何图片',
                )
            target_path = os.path.join(path, filter_dir_name(vol_name))
            result = self.__download_vol_images__(target_path, vol_name, url, imgs, parent_progress)
            if result.ok:
                logger.info('卷/话 {} 下载完成.', vol_name)
            else:
                logger.warning(
                    '卷/话 {} 下载未完全成功: 状态={}, 成功图片={}/{}',
                    vol_name,
                    result.status,
                    result.downloaded_count,
                    result.image_count,
                )
            return result
        except Exception as e:
            # 异常发生时也要清理任务，并确保不会重复移除
            self._remove_progress_task(parent_progress, parse_task_id)

            logger.error('处理卷/话失败: {} ({}), 错误: {}', vol_name, url, e, exc_info=True)
            return VolumeDownloadResult(name=vol_name, url=url, status='failed', message=str(e))

    def _find_existing_archive(self, path: str, vol_name: str) -> str | None:
        if self.overwrite:
            return None

        target_zip_name = filter_dir_name(vol_name) + '.zip'
        target_zip_path = os.path.join(path, target_zip_name)
        if os.path.exists(target_zip_path):
            return target_zip_path

        base_name = filter_dir_name(vol_name)
        match = re.match(r'^(\d+)(.*)$', base_name)
        if not match:
            return None

        num_part = match.group(1)
        rest_part = match.group(2)
        for i in range(1, 3):
            padded_num = num_part.zfill(len(num_part) + i)
            padded_path = os.path.join(path, padded_num + rest_part + '.zip')
            if os.path.exists(padded_path):
                logger.info('文件已存在(补零匹配)，跳过: {}', padded_path)
                return padded_path
        return None

    def _remove_progress_task(self, progress: Progress | None, task_id) -> None:
        if progress is None or task_id is None:
            return
        try:
            progress.remove_task(task_id)
        except KeyError:
            logger.debug('进度任务已被移除: {task_id}', task_id=task_id)

    def __download_vol_images__(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        imgs: list[str],
        progress: Progress | None = None,
    ) -> VolumeDownloadResult:
        """下载图片"""
        logger.info('开始下载图片到目录: {} (共 {} 张)', path, len(imgs))
        os.makedirs(path, exist_ok=True)
        context = ImageDownloadContext(path=path, use_base_img_url=hasattr(self, 'base_img_url'))
        failed_images = self._run_image_downloads(context, imgs, progress, vol_name)
        return self._finalize_volume_download(path, vol_name, source_url, len(imgs), failed_images)

    def _run_image_downloads(
        self,
        context: ImageDownloadContext,
        imgs: list[str],
        progress: Progress | None,
        vol_name: str,
    ) -> list[ImageDownloadFailure]:
        failed_images: list[ImageDownloadFailure] = []
        max_workers = max(1, min(getattr(self, 'max_download_workers', 5), len(imgs)))
        task_id = (
            progress.add_task(description=f'  [cyan]{vol_name}', total=len(imgs))
            if progress
            else None
        )
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [
                executor.submit(self._download_image, context, index, img_url_part)
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
        except Exception:
            executor.shutdown(wait=True)
            raise
        finally:
            self._remove_progress_task(progress, task_id)
        return failed_images

    def _download_image(
        self, context: ImageDownloadContext, index: int, img_url_part: str
    ) -> ImageDownloadFailure | None:
        file_path = os.path.join(context.path, f'{index + 1:04d}.jpg')
        tmp_path = file_path + '.tmp'
        full_img_url = self._build_image_url(img_url_part, context.use_base_img_url)
        retry_count = getattr(self, 'image_retry_count', 1)
        last_error = ''

        if self._can_reuse_image(file_path):
            logger.debug('图片已存在，跳过: {file_path}', file_path=file_path)
            return None

        logger.debug('下载图片: {} 到 {}', full_img_url, file_path)
        for attempt in range(1, retry_count + 2):
            response = None
            try:
                self._wait_for_download_slot(context)
                response = self._request_image(full_img_url, context)
                self._write_image_response(response, tmp_path, file_path)
                logger.debug('图片 {} 下载成功.', file_path)
                return None
            except (requests.exceptions.RequestException, OSError) as e:
                last_error = str(e)
                self._handle_image_download_error(tmp_path, full_img_url, attempt, retry_count, e)
            finally:
                if response is not None and hasattr(response, 'close'):
                    response.close()
        return ImageDownloadFailure(index + 1, full_img_url, file_path, last_error)

    def _can_reuse_image(self, file_path: str) -> bool:
        return not self.overwrite and os.path.exists(file_path) and os.path.getsize(file_path) > 0

    def _build_image_url(self, img_url_part: str, use_base_img_url: bool) -> str:
        if use_base_img_url and not img_url_part.startswith('http'):
            if img_url_part.startswith('/'):
                return self.base_img_url + img_url_part
            return self.base_img_url + '/' + img_url_part
        return img_url_part

    def _wait_for_download_slot(self, context: ImageDownloadContext) -> None:
        interval = getattr(self, 'download_interval', 0)
        if interval <= 0:
            return
        with context.rate_lock:
            now = time.monotonic()
            elapsed = now - context.last_request_at[0]
            if context.last_request_at[0] > 0 and elapsed < interval:
                time.sleep(interval - elapsed)
            context.last_request_at[0] = time.monotonic()

    def _request_image(self, full_img_url: str, context: ImageDownloadContext):
        headers = {'referer': self.base_url}
        with context.http_lock:
            response = self.http.get(full_img_url, timeout=30, headers=headers, stream=True)
        response.raise_for_status()
        return response

    def _write_image_response(self, response, tmp_path: str, file_path: str) -> None:
        with open(tmp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)
        os.replace(tmp_path, file_path)

    def _handle_image_download_error(
        self,
        tmp_path: str,
        full_img_url: str,
        attempt: int,
        retry_count: int,
        error: Exception,
    ) -> None:
        self._remove_tmp_file(tmp_path)
        if attempt <= retry_count:
            logger.warning(
                '下载图片失败，将重试: {}, 第 {}/{} 次, 错误: {}',
                full_img_url,
                attempt,
                retry_count + 1,
                error,
            )
        else:
            logger.error('下载图片失败: {}, 错误: {}', full_img_url, error)

    def _remove_tmp_file(self, tmp_path: str) -> None:
        if not os.path.exists(tmp_path):
            return
        try:
            os.remove(tmp_path)
        except OSError:
            logger.warning('清理临时文件失败: {}', tmp_path, exc_info=True)

    def _finalize_volume_download(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
    ) -> VolumeDownloadResult:
        if not os.path.exists(path):
            return self._failed_volume_result(
                vol_name, source_url, expected_count, failed_images, '目录不存在'
            )
        if not os.listdir(path):
            return self._failed_volume_result(
                vol_name, source_url, expected_count, failed_images, '目录为空'
            )
        return self._finalize_existing_download_dir(
            path, vol_name, source_url, expected_count, failed_images
        )

    def _finalize_existing_download_dir(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
    ) -> VolumeDownloadResult:
        actual_files = sorted(os.listdir(path))
        actual_count = len(actual_files)
        downloaded_count = expected_count - len(failed_images)
        if expected_count == actual_count and not failed_images:
            return self._archive_volume(
                path, vol_name, source_url, expected_count, downloaded_count
            )
        return self._partial_volume_result(
            path,
            vol_name,
            source_url,
            expected_count,
            VolumeFileState(
                downloaded_count=downloaded_count,
                failed_images=failed_images,
                actual_files=actual_files,
                actual_count=actual_count,
            ),
        )

    def _archive_volume(
        self, path: str, vol_name: str, source_url: str, expected_count: int, downloaded_count: int
    ) -> VolumeDownloadResult:
        logger.info('开始压缩目录: {}', path)
        try:
            archive_path = shutil.make_archive(path, 'zip', path)
            logger.info('目录 {} 压缩完成.', path)
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='downloaded',
                image_count=expected_count,
                downloaded_count=downloaded_count,
                archive_path=archive_path,
            )
        except Exception as e:
            logger.error('压缩目录失败: {}, 错误: {}', path, e, exc_info=True)
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='failed',
                image_count=expected_count,
                downloaded_count=downloaded_count,
                message=f'压缩目录失败: {e}',
            )

    def _partial_volume_result(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        file_state: VolumeFileState,
    ) -> VolumeDownloadResult:
        missing_files = self._missing_image_files(expected_count, file_state.actual_files)
        logger.warning(
            '目录 {} 图片数量不匹配，跳过压缩. 预期 {} 张，实际 {} 张. 缺少文件: {}',
            path,
            expected_count,
            file_state.actual_count,
            missing_files,
        )
        status = 'partial' if file_state.downloaded_count > 0 else 'failed'
        return VolumeDownloadResult(
            name=vol_name,
            url=source_url,
            status=status,
            image_count=expected_count,
            downloaded_count=file_state.downloaded_count,
            failed_images=file_state.failed_images,
            message='图片数量不匹配，跳过压缩',
        )

    def _missing_image_files(self, expected_count: int, actual_files: list[str]) -> list[str]:
        return [
            f'{index:04d}.jpg'
            for index in range(1, expected_count + 1)
            if f'{index:04d}.jpg' not in actual_files
        ]

    def _failed_volume_result(
        self,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
        message: str,
    ) -> VolumeDownloadResult:
        logger.warning('{}, 跳过压缩.', message)
        return VolumeDownloadResult(
            name=vol_name,
            url=source_url,
            status='failed',
            image_count=expected_count,
            downloaded_count=0,
            failed_images=failed_images,
            message=message,
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
            results.extend(self._extract_xpath_item(node, extract_map) for node in nodes)
        except Exception as e:
            self.logger.error('XPath解析失败: {xpath}, 错误: {error}', xpath=xpath, error=e)
        return results

    def _extract_xpath_item(self, node, extract_map):
        item = {}
        for key, expr in extract_map.items():
            item[key] = self._extract_xpath_value(node, key, expr)
        return item

    def _extract_xpath_value(self, node, key, expr):
        try:
            if expr.startswith('./@'):
                vals = node.xpath(expr)
                return vals[0] if vals else None
            if expr == './text()':
                return node.text.strip() if node.text else None
            vals = node.xpath(expr)
            if not vals:
                return None
            text_node = vals[0]
            return (
                text_node.text.strip()
                if hasattr(text_node, 'text') and text_node.text
                else text_node
            )
        except Exception as e:
            self.logger.debug('提取 {key} 时出错: {error}', key=key, error=e)
            return None

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
                self.logger.warning('潜在不安全JS代码: {js_code}', js_code=js_code)
                return fallback
            return driver.execute_script(js_code)
        except Exception as e:
            self.logger.error('JS执行失败: {js_code}, 错误: {error}', js_code=js_code, error=e)
            return fallback

    def _seleniumbase_context(self):
        kwargs = {
            "uc": True,
            "test": True,
            "locale": "zh-CN",
            "headed": True,
        }
        return SB(**kwargs)

    def _wait_for_seleniumbase_html(self, sb):
        if self.seleniumbase_wait_selector:
            try:
                sb.cdp.find(
                    self.seleniumbase_wait_selector,
                    timeout=self.seleniumbase_wait_seconds,
                )
            except Exception as e:
                self.logger.debug(
                    'SeleniumBase 等待选择器超时: {selector}, 错误: {error}',
                    selector=self.seleniumbase_wait_selector,
                    error=e,
                )
            return

        if self.seleniumbase_wait_seconds > 0:
            sb.cdp.sleep(self.seleniumbase_wait_seconds)

    def _parse_html_with_seleniumbase(self, url, method='GET'):
        if method.upper() != 'GET':
            logger.error('SeleniumBase CDP HTML 解析仅支持 GET 请求: {}', method)
            return None

        try:
            with self._seleniumbase_context() as sb:
                sb.activate_cdp_mode(url)
                sb.sleep(10)
                sb.solve_captcha()
                # sb.wait_for_element_absent("input[disabled]")
                sb.sleep(10)
                self._wait_for_seleniumbase_html(sb)
                html = sb.cdp.get_page_source()
                return etree.parse(StringIO(html), self.parser)
        except Exception as e:
            logger.error(
                'SeleniumBase CDP 解析 HTML 页面失败: {}, 错误: {}',
                url,
                e,
                exc_info=True,
            )
            return None

    def __parse_html__(
        self,
        url,
        method='GET',
        data=None,
        encoding='utf-8',
        headers=None,
    ):
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
        self.logger.debug('开始解析HTML: {url}, 方法: {method}', url=url, method=method)

        method_name = method.upper()
        if method_name == 'SELENIUMBASE':
            return self._parse_html_with_seleniumbase(url)

        request_headers = {'referer': self.base_url}
        if headers:
            request_headers.update(headers)

        try:
            if method_name == 'GET':
                r = self.http.get(url, timeout=30, headers=request_headers)  # 增加超时
            elif method_name == 'POST':
                r = self.http.post(url, data=data, timeout=30, headers=request_headers)  # 增加超时
            else:
                logger.error('不支持的HTTP方法: {}', method)
                return None
            r.raise_for_status()  # 如果请求失败则抛出HTTPError异常
            r.encoding = encoding
            return etree.parse(StringIO(r.text), self.parser)
        except requests.exceptions.RequestException as e:
            logger.error('请求HTML页面失败: {}, 方法: {}, 错误: {}', url, method, e, exc_info=True)
            return None
        except Exception as e:
            logger.error('处理HTML页面时发生未知错误: {}, 错误: {}', url, e, exc_info=True)
            return None
