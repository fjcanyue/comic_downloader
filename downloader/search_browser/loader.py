from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from queue import SimpleQueue
from typing import Any

import requests
from loguru import logger

from downloader.browser.manager import DriverManager
from downloader.models import Comic
from downloader.search_browser.state import SearchItem
from downloader.sources.profiles import SourceBinding


class PreviewCancelledError(Exception):
    pass


class PreviewPresenter:
    """Driver messages go to the file log, never Rich's live terminal renderer."""

    def print(self, message: Any = '', style: str | None = None) -> None:
        logger.bind(browser_preview=True).info(str(message))


class DetailLoader:
    def __init__(
        self,
        bindings: dict[str, SourceBinding],
        output_path: str,
        session_factory: Callable[[], requests.Session],
    ) -> None:
        self.bindings = bindings
        self.output_path = output_path
        self.session_factory = session_factory

    def __call__(self, item: SearchItem, stopping: threading.Event) -> Comic:
        binding = self.bindings.get(item.source)
        if binding is None or not item.url:
            raise ValueError('来源或漫画地址不可用，请重新搜索。')
        if stopping.is_set():
            raise PreviewCancelledError
        manager = DriverManager(PreviewPresenter())
        with logger.contextualize(browser_preview=True):
            try:
                with self.session_factory() as http:
                    original_request = http.request

                    def request(*args, **kwargs):
                        if stopping.is_set():
                            raise PreviewCancelledError
                        return original_request(*args, **kwargs)

                    http.request = request
                    if binding.profile.browser_mode_uses_driver() and not manager.ensure_driver(
                        binding.profile
                    ):
                        raise ValueError('浏览器未能启动，请检查安装或来源配置后按 r 重试。')
                    if stopping.is_set():
                        raise PreviewCancelledError
                    source = binding.source_class(
                        self.output_path,
                        http,
                        manager.current_driver,
                        overwrite=False,
                        profile=binding.profile,
                    )
                    original_context = source._seleniumbase_context

                    def browser_context():
                        if stopping.is_set():
                            raise PreviewCancelledError
                        return original_context()

                    source._seleniumbase_context = browser_context
                    comic = source.info(item.url)
                    if stopping.is_set():
                        raise PreviewCancelledError
                    if comic is None:
                        result = getattr(source, 'last_page_load_result', None)
                        reason = getattr(result, 'error_message', None) or '页面未返回可用详情'
                        raise ValueError(f'{reason}；可按 r 重试，或检查验证码及来源状态。')
                    return comic
            finally:
                # Both configured drivers and HTTP fallback contexts are owned by this thread.
                manager.destroy()


@dataclass(frozen=True)
class PreviewResult:
    token: int
    item: SearchItem
    comic: Comic | None = None
    error: str = ''
    cancelled: bool = False


class PreviewWorker:
    """One running request and one replaceable pending request; no executor backlog."""

    def __init__(self, load: Callable[[SearchItem, threading.Event], Comic]) -> None:
        self.load = load
        self.results: SimpleQueue[PreviewResult] = SimpleQueue()
        self.stopping = threading.Event()
        self.condition = threading.Condition()
        self.pending: tuple[int, SearchItem] | None = None
        self.active: tuple[int, SearchItem] | None = None
        self.sequence = 0
        self.thread: threading.Thread | None = None

    def submit(self, item: SearchItem) -> int:
        with self.condition:
            if self.stopping.is_set():
                raise RuntimeError('详情加载器已关闭')
            for request in (self.active, self.pending):
                if request and request[1].key == item.key:
                    return request[0]
            self.sequence += 1
            if self.pending:
                self.results.put(PreviewResult(*self.pending, cancelled=True))
            self.pending = (self.sequence, item)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='comic-preview', daemon=False)
                self.thread.start()
            self.condition.notify()
            return self.sequence

    def stop(self) -> None:
        with self.condition:
            self.stopping.set()
            if self.pending:
                self.results.put(PreviewResult(*self.pending, cancelled=True))
                self.pending = None
            self.condition.notify()

    @property
    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def join(self) -> None:
        interrupted = False
        while self.alive:
            try:
                if self.thread:
                    self.thread.join(timeout=0.1)
            except KeyboardInterrupt:  # noqa: PERF203 - wait for owned resources before propagating
                interrupted = True
                self.stop()
        if interrupted:
            raise KeyboardInterrupt

    def _run(self) -> None:
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.stopping.is_set())
                if self.stopping.is_set():
                    return
                request = self.pending
                self.pending = None
                self.active = request
            if request is None:
                continue
            token, item = request
            try:
                comic = self.load(item, self.stopping)
                result = PreviewResult(token, item, comic=comic)
            except PreviewCancelledError:
                result = PreviewResult(token, item, cancelled=True)
            except Exception as exc:
                logger.bind(browser_preview=True).exception('详情预览失败：{}', item.url)
                result = PreviewResult(token, item, error=str(exc) or type(exc).__name__)
            with self.condition:
                self.active = None
                self.results.put(result)
