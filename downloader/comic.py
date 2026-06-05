import concurrent.futures  # re-exported for tests that monkeypatch downloader.comic.concurrent
import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests
from loguru import logger
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from rich.progress import BarColumn, Progress, TextColumn

from downloader.archive import ArchiveMixin
from downloader.browser_modes import (
    REQUESTS_MODE,
    BrowserModeName,
    is_driver_backed_browser_mode,
    normalize_browser_mode,
)
from downloader.html_parser import HtmlParsingMixin
from downloader.image_downloader import ImageDownloadMixin
from downloader.models import (
    Comic,
    ComicBook,
    ComicVolume,
    DownloadSummary,
    HtmlParseOptions,
    ImageDownloadCancelledError,
    ImageDownloadContext,
    ImageDownloadFailure,
    VolumeDownloadResult,
    VolumeFileState,
    filter_dir_name,
)
from downloader.source_config import SOURCE_CONFIG_ATTRIBUTE_KEYS
from downloader.source_profiles import (
    PROFILE_MIRROR_ATTRIBUTE_KEYS,
    SourceProfile,
    mutable_site_config,
)

__all__ = [
    'Comic',
    'ComicBook',
    'ComicSource',
    'ComicVolume',
    'DownloadSummary',
    'HtmlParseOptions',
    'ImageDownloadCancelledError',
    'ImageDownloadContext',
    'ImageDownloadFailure',
    'VolumeDownloadResult',
    'VolumeFileState',
    'concurrent',
    'filter_dir_name',
    'logger',
]


class ComicSource(ImageDownloadMixin, ArchiveMixin, HtmlParsingMixin, ABC):
    base_url: str = ''
    base_img_url: str = ''
    browser_mode: BrowserModeName = REQUESTS_MODE
    browser_wait_selector: str | None = None
    browser_wait_seconds: float | None = None
    browser_headless: bool | None = None
    cloakbrowser_humanize: bool = True
    cloakbrowser_options: dict[str, Any] | None = None
    config_file: str | None = None
    download_interval: float = 0
    image_request_interval: float | None = None
    page_load_wait_seconds: float | None = None
    scroll_wait_seconds: float | None = None
    max_scroll_attempts: int | None = None
    download_requires_driver: bool = False
    image_retry_count: int = 1
    max_download_workers: int = 5
    enable: bool = True
    seleniumbase_headless: bool | None = None
    seleniumbase_wait_selector: str | None = None
    seleniumbase_wait_seconds: float = 20.0

    @classmethod
    def configured_browser_mode(cls) -> BrowserModeName:
        config_mode = cls._configured_browser_mode_from_file()
        return normalize_browser_mode(config_mode or getattr(cls, 'browser_mode', REQUESTS_MODE))

    @classmethod
    def _configured_browser_mode_from_file(cls) -> str | None:
        config_file = getattr(cls, 'config_file', None)
        if not config_file:
            return None
        base_path = Path(__file__).parent.parent
        config_path = base_path / 'configs' / config_file
        try:
            with open(config_path, encoding='utf-8') as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        browser_mode = config.get('browser_mode')
        return str(browser_mode) if browser_mode else None

    @classmethod
    def browser_mode_uses_driver(cls) -> bool:
        return is_driver_backed_browser_mode(cls.configured_browser_mode())

    @classmethod
    def uses_driver_for_search(cls) -> bool:
        return bool(getattr(cls, 'search_requires_driver', False)) or cls.browser_mode_uses_driver()

    @classmethod
    def uses_driver_for_download(cls) -> bool:
        return (
            bool(getattr(cls, 'download_requires_driver', False)) or cls.browser_mode_uses_driver()
        )

    def current_browser_mode_uses_driver(self) -> bool:
        return is_driver_backed_browser_mode(self._source_browser_mode())

    def _page_load_wait_seconds_value(self, default: float = 0) -> float:
        configured = getattr(self, 'page_load_wait_seconds', None)
        if configured is None:
            configured = default
        return float(configured or 0)

    def _scroll_wait_seconds_value(self, default: float = 3) -> float:
        configured = getattr(self, 'scroll_wait_seconds', None)
        if configured is None:
            configured = default
        return float(configured or 0)

    def _max_scroll_attempts_value(self, default: int = 5) -> int:
        configured = getattr(self, 'max_scroll_attempts', None)
        if configured is None:
            configured = default
        return max(1, int(configured))

    def __init__(
        self,
        output_dir: str,
        http: requests.Session,
        driver: Any,
        overwrite: bool = True,
        *,
        profile: SourceProfile | None = None,
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
        self.profile: SourceProfile | None = profile

        self.parser: etree.HTMLParser = etree.HTMLParser()
        self.logger = logger

        # Load configuration if config_file is specified
        if profile is not None:
            self.config = mutable_site_config(profile)
            self._apply_source_profile(profile)
        elif hasattr(self, 'config_file') and self.config_file:
            self.load_config()
        elif hasattr(self, 'config') and self.config:
            # Already has config (maybe hardcoded), do nothing or validate
            pass
        else:
            self.config = {}

    def _apply_source_profile(self, profile: SourceProfile) -> None:
        for key in PROFILE_MIRROR_ATTRIBUTE_KEYS:
            setattr(self, key, getattr(profile, key))
        self.browser_mode = normalize_browser_mode(profile.browser_mode)

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
            self._apply_source_config()
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

    def _apply_source_config(self) -> None:
        for key in SOURCE_CONFIG_ATTRIBUTE_KEYS:
            if key in self.config:
                setattr(self, key, self.config[key])
        self.browser_mode = normalize_browser_mode(getattr(self, 'browser_mode', REQUESTS_MODE))

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
