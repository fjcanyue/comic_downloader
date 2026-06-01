from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from downloader.browser_modes import BrowserModeName


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


class ImageDownloadCancelledError(Exception):
    pass


@dataclass
class ImageDownloadContext:
    path: str
    use_base_img_url: bool
    session_factory: Callable[[], Any] | None = None
    rate_lock: threading.Lock = field(default_factory=threading.Lock)
    http_lock: threading.Lock = field(default_factory=threading.Lock)
    session_lock: threading.Lock = field(default_factory=threading.Lock)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    last_request_at: list[float] = field(default_factory=lambda: [0.0])
    thread_local: threading.local = field(default_factory=threading.local)
    sessions: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class VolumeFileState:
    downloaded_count: int
    failed_images: list[ImageDownloadFailure]
    actual_files: list[str]
    actual_count: int


@dataclass(frozen=True)
class HtmlParseOptions:
    browser_mode: BrowserModeName
    http_method: str
    encoding: str


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
