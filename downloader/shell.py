from __future__ import annotations

import cmd
import concurrent.futures
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from urllib3.util.retry import Retry

from downloader.browser_drivers import CloakBrowserDriver
from downloader.browser_modes import CLOAKBROWSER_MODE, normalize_browser_mode
from downloader.comic import Comic, ComicSource
from downloader.sources import load_source_classes

FULL_VOLUME_ARG_COUNT = 1
VOLUME_TO_ARG_COUNT = 2
VOLUME_RANGE_ARG_COUNT = 3


def parse_1_based_index(value: str, length: int, label: str) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'请输入正确的{label}序号！') from None
    if index < 1 or index > length:
        raise ValueError(f'请输入正确的{label}序号！')
    return index - 1


def parse_volume_slice(args: list[str], book_count: int, vol_count: int) -> tuple[int, slice]:
    if not args:
        raise ValueError('请输入动漫章节序号！')

    book_index = parse_1_based_index(args[0], book_count, '动漫章节')
    if len(args) == FULL_VOLUME_ARG_COUNT:
        return book_index, slice(None)
    if len(args) == VOLUME_TO_ARG_COUNT:
        vol_to = parse_1_based_index(args[1], vol_count, '截止')
        return book_index, slice(0, vol_to + 1)
    if len(args) == VOLUME_RANGE_ARG_COUNT:
        vol_from = parse_1_based_index(args[1], vol_count, '起始')
        vol_to = parse_1_based_index(args[2], vol_count, '截止')
        if vol_from > vol_to:
            raise ValueError('请输入正确的截止序号！')
        return book_index, slice(vol_from, vol_to + 1)
    raise ValueError('参数错误，请重新输入！')


@dataclass(frozen=True)
class SearchTask:
    source_name: str
    source_class: type[ComicSource]
    search_func: Callable[[str], list]
    uses_driver: bool
    display_name: str


@dataclass
class SearchOutcome:
    source_name: str
    results: list
    error_message: str | None
    duration: float


def _execute_search_task(
    task: SearchTask, keyword: str, per_source_limit: int, driver_lock: threading.Lock | None
) -> SearchOutcome:
    start = time.perf_counter()
    try:
        # Selenium driver 不是线程安全的，访问时强制串行化
        if task.uses_driver:
            if driver_lock is None:
                raise RuntimeError('浏览器驱动锁未初始化')
            with driver_lock:
                results = task.search_func(keyword)
        else:
            results = task.search_func(keyword)

        trimmed = []
        for comic in results:
            if len(trimmed) >= per_source_limit:
                break
            comic.source = task.source_name
            trimmed.append(comic)

        duration = time.perf_counter() - start
        return SearchOutcome(task.source_name, trimmed, None, duration)
    except Exception as e:
        duration = time.perf_counter() - start
        logger.exception('搜索任务失败: {source_name}', source_name=task.source_name)
        return SearchOutcome(task.source_name, [], str(e), duration)


def _run_search_serial(
    tasks: list[SearchTask],
    keyword: str,
    per_source_limit: int,
    driver_lock: threading.Lock | None,
) -> list[SearchOutcome]:
    return [_execute_search_task(task, keyword, per_source_limit, driver_lock) for task in tasks]


def _run_search_parallel(
    tasks: list[SearchTask],
    keyword: str,
    per_source_limit: int,
    driver_lock: threading.Lock | None,
    max_workers: int | None = None,
) -> list[SearchOutcome]:
    if not tasks:
        return []
    if max_workers is None:
        max_workers = min(8, len(tasks))
    if max_workers <= 1:
        return _run_search_serial(tasks, keyword, per_source_limit, driver_lock)

    # 并行执行后按完成顺序收集，再在外层按源顺序合并
    outcomes = []
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [
            executor.submit(_execute_search_task, task, keyword, per_source_limit, driver_lock)
            for task in tasks
        ]
        outcomes.extend(future.result() for future in concurrent.futures.as_completed(futures))
        executor.shutdown(wait=True)
    except (KeyboardInterrupt, SystemExit):
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    except Exception:
        executor.shutdown(wait=True)
        raise
    return outcomes


class Shell(cmd.Cmd):
    use_rawinput = False

    intro = """
    欢迎使用动漫下载器，输入 help 或者 ? 查看帮助。
    支持的命令有：
    * s: 搜索动漫，从所有支持的源中搜索。输入s <搜索关键字>。例如：输入 s 猎人
    * d: 全量下载动漫，输入d <搜索结果序号/动漫URL地址>。例如：输入 d 12，或者d https://www.maofly.com/manga/38316.html
    * i: 查看动漫详情，输入i <搜索结果序号/动漫URL地址>。例如：输入 i 12，或者i https://www.maofly.com/manga/13954.html
    * v: 按范围下载动漫，需要先执行查看动漫详情命令，根据详情的序号列表，指定下载范围。支持三种模式：
      - 输入v <章节序号>，下载该章节下的所有动漫。例如：输入 v 1。
      - 输入v <章节序号> <截止序号>，下载该章节下，从章节开始到截止序号的动漫。例如：输入 v 1 12
      - 输入v <章节序号> <起始序号> <截止序号>，下载该章节下，从起始位置到截止位置的动漫。例如：输入 v 1 12 18
    * source: 手动切换动漫下载网站源 (可选)。
    * q: 退出动漫下载器
    """
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(self, output_path, overwrite=False):
        super().__init__()
        self.console = Console()
        self.context = Context(self.console)
        self.context.create(output_path)
        self.overwrite = overwrite
        self.search_driver_lock = threading.Lock()
        self.current_source_name = None

        # 默认源排除 deprecated 站点；完整源用于直接 URL 匹配。
        self.all_source_map = self._discover_sources(include_deprecated=True)
        self.source_map = self._discover_sources()
        self.source_options = list(self.source_map.keys())  # 存储源名称列表，方便按索引访问
        self.sources = {}

    def _read_prompt_line(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip('\r\n')

    def _discover_sources(self, include_deprecated: bool = False):
        """加载已声明的 ComicSource 实现。"""
        try:
            return load_source_classes(include_deprecated=include_deprecated)
        except Exception as e:
            self.console.print(f'Failed to load comic sources: {e}', style='bold red')
            return {}

    def _ensure_driver(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> bool:
        """按需初始化当前漫画源需要的浏览器驱动。"""
        target = source_or_class or self.context.source
        if not self.context.ensure_driver(target):
            return False
        if isinstance(target, ComicSource):
            target.driver = self.context.driver
        return True

    def _ensure_source_download_ready(self) -> bool:
        if self.context.source is None:
            self.console.print('当前没有选中的动漫源！')
            return False
        if not self.context.source.uses_driver_for_download():
            return True
        if self._ensure_driver(self.context.source):
            self.context.source.driver = self.context.driver
            return True
        self.console.print('当前动漫源下载需要浏览器驱动，无法继续下载。', style='bold red')
        return False

    def _ensure_source_page_ready(self) -> bool:
        if self.context.source is None:
            self.console.print('当前没有选中的动漫源！')
            return False
        if not self.context.source.current_browser_mode_uses_driver():
            return True
        if self._ensure_driver(self.context.source):
            self.context.source.driver = self.context.driver
            return True
        self.console.print('当前动漫源页面解析需要浏览器驱动，无法继续。', style='bold red')
        return False

    def _match_source_for_url(self, url: str) -> str | None:
        for source_name, source_class in self.all_source_map.items():
            if hasattr(source_class, 'base_url') and url.startswith(source_class.base_url):
                return source_name
        return None

    def do_source(self, arg):
        """选择动漫下载网站源。输入 source  后，根据提示选择源序号。"""
        self.console.print('请选择动漫下载网站源:')
        for index, source_name in enumerate(self.source_options):
            self.console.print(f'{index + 1}. {source_name}')

        while True:
            try:
                source_index_str = self._read_prompt_line('请输入网站源序号: ')
                if not source_index_str:  # 用户直接回车，重新显示列表
                    self.console.print('请选择动漫下载网站源:')
                    for index, source_name in enumerate(self.source_options):
                        self.console.print(f'{index + 1}. {source_name}')
                    continue  # 继续下一次循环，等待用户输入
                source_index = int(source_index_str) - 1  # 序号从1开始，索引从0开始
                if 0 <= source_index < len(self.source_options):
                    source_name = self.source_options[source_index]
                    self.__switch_source(source_name)
                    break  # 选择成功，退出循环
                self.console.print(
                    f'无效的序号，请输入 1 到 {len(self.source_options)} 之间的序号。'
                )
            except EOFError:
                self.console.print()
                return
            except ValueError:
                self.console.print('请输入有效的数字序号。')

    def __switch_source(self, source_name):
        """切换动漫源"""
        if self.current_source_name == source_name:
            return
        self.console.print(f'正在切换到{source_name}动漫下载网站源...')

        if source_name not in self.sources:
            source_class = self.source_map.get(source_name) or self.all_source_map[source_name]
            self.sources[source_name] = source_class(
                self.context.output_path,
                self.context.http,
                self.context.get_driver(source_class),
                overwrite=self.overwrite,
            )

        self.context.source = self.sources[source_name]
        self.current_source_name = source_name
        # self.prompt = self.prefix + self.context.source.name + '> '

    def _build_search_func(self, source_class, uses_driver: bool) -> Callable[[str], list]:
        def _search(keyword: str) -> list:
            driver = None
            if uses_driver:
                if not self.context.ensure_driver(source_class):
                    raise RuntimeError('浏览器驱动未初始化')
                driver = self.context.driver
            http = self.context.create_http_session()
            source = source_class(
                self.context.output_path,
                http,
                driver,
                overwrite=self.overwrite,
            )
            return source.search(keyword)

        return _search

    def _build_search_tasks(self) -> list[SearchTask]:
        tasks = []
        for source_name in self.source_options:
            source_class = self.source_map[source_name]
            uses_driver = source_class.uses_driver_for_search()
            tasks.append(
                SearchTask(
                    source_name=source_name,
                    source_class=source_class,
                    search_func=self._build_search_func(source_class, uses_driver),
                    uses_driver=uses_driver,
                    display_name=getattr(source_class, 'name', source_name),
                )
            )

            if source_name not in self.sources:
                self.sources[source_name] = source_class(
                    self.context.output_path,
                    self.context.http,
                    self.context.get_driver(source_class),
                    overwrite=self.overwrite,
                )
        return tasks

    def _filter_ready_search_tasks(self, tasks: list[SearchTask]) -> list[SearchTask]:
        ready_tasks = []
        skipped_sources = set()
        for task in tasks:
            if not task.uses_driver or self.context.ensure_driver(task.source_class):
                ready_tasks.append(task)
            else:
                skipped_sources.add(task.source_name)
        if not skipped_sources:
            return ready_tasks
        self.console.print(
            f'已跳过需要浏览器驱动的搜索源: {", ".join(sorted(skipped_sources))}',
            style='bold yellow',
        )
        return ready_tasks

    def _merge_search_outcomes(self, outcomes: list[SearchOutcome]) -> None:
        outcomes_by_source = {outcome.source_name: outcome for outcome in outcomes}
        for source_name in self.source_options:
            outcome = outcomes_by_source.get(source_name)
            if not outcome:
                continue
            if outcome.error_message:
                self.console.print(
                    f'在 {source_name} 中搜索失败: {outcome.error_message}', style='bold red'
                )
            self.context.searched_results.extend(outcome.results)

    def _print_search_table(self, keyword: str, search_duration: float) -> None:
        if not self.context.searched_results:
            self.console.print(f'未找到与 "{keyword}" 相关的结果。', style='bold yellow')
            return

        table = Table(
            title=f'搜索结果 ({len(self.context.searched_results)} 条，用时 {search_duration:.1f}s)'
        )
        table.add_column('序号', justify='right', no_wrap=True)
        table.add_column('动漫源')
        table.add_column('作者')
        table.add_column('名称')
        table.add_column('URL', style='#75D7EC')

        for index, comic in enumerate(self.context.searched_results):
            source_obj = self.sources.get(comic.source)
            source_display = getattr(source_obj, 'name', comic.source)
            table.add_row(
                str(index + 1),
                source_display,
                comic.author if comic.author else 'N/A',
                comic.name if comic.name else 'N/A',
                comic.url if comic.url else 'N/A',
            )

        self.console.print(table)

    def do_s(self, arg):
        """搜索动漫，输入s <搜索关键字>，例如：s 猎人"""
        if not arg:
            self.console.print('请输入搜索关键字！')
            return

        self.context.reset_comic()
        self.context.searched_results = []
        tasks = self._filter_ready_search_tasks(self._build_search_tasks())

        task_lookup = {task.source_name: task for task in tasks}
        console_status = self.console.status('正在搜索...', spinner='dots')
        search_start = time.perf_counter()
        with console_status:
            outcomes = _run_search_parallel(
                tasks, arg, 10, self.search_driver_lock, max_workers=min(8, len(tasks))
            )

            for outcome in outcomes:
                task = task_lookup.get(outcome.source_name)
                if task:
                    console_status.update(f'完成 {task.display_name} 搜索')

        search_duration = time.perf_counter() - search_start
        self._merge_search_outcomes(outcomes)
        logger.info(
            '搜索完成: keyword={keyword}, sources={sources}, results={results}, duration={duration:.2f}s',
            keyword=arg,
            sources=len(tasks),
            results=len(self.context.searched_results),
            duration=search_duration,
        )
        self._print_search_table(arg, search_duration)

    def do_i(self, arg):
        """查看动漫详情，输入i <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/13954.html"""
        if not arg:
            self.console.print('请输入动漫URL地址或者搜索结果序号！')
            return

        url = self._resolve_info_url(arg)
        if url is None:
            return

        if not self.context.source:
            self.console.print('无法确定该动漫所属的源，请先搜索或手动选择源。')
            return
        if not self._ensure_source_page_ready():
            return

        with self.console.status('正在获取详情...', spinner='dots'):
            self.context.comic = self.context.source.info(url)

        if self.context.comic is None:
            self.console.print('未能获取动漫详情，请检查输入的地址或稍后重试。', style='bold red')
            return

        self._print_comic_info(self.context.comic)

    def _resolve_info_url(self, arg: str) -> str | None:
        if arg.isdigit():
            return self._resolve_search_result_url(arg)
        return self._resolve_direct_info_url(arg)

    def _resolve_search_result_url(self, arg: str) -> str | None:
        try:
            idx = parse_1_based_index(arg, len(self.context.searched_results), '搜索结果')
        except ValueError:
            self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
            return None
        if not self.context.searched_results:
            self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
            return None

        comic = self.context.searched_results[idx]
        if comic.source:
            self.__switch_source(comic.source)
        return comic.url

    def _resolve_direct_info_url(self, url: str) -> str | None:
        matched_source = self._match_source_for_url(url)
        if matched_source:
            self.__switch_source(matched_source)
            return url
        if (
            self.context.source
            and hasattr(self.context.source, 'base_url')
            and url.startswith(self.context.source.base_url)
        ):
            return url
        self.console.print('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
        return None

    def _print_comic_info(self, comic: Comic) -> None:
        md_content = f'# {comic.name}\n\n'

        if comic.metadata:
            md_content += '## Metadata\n'
            for meta in comic.metadata:
                md_content += f'- **{meta["k"]}**: {meta["v"]}\n'

        self.console.print(Markdown(md_content))
        self._print_chapter_tables(comic)

    def _print_chapter_tables(self, comic: Comic) -> None:
        for book_index, book in enumerate(comic.books):
            self.console.print(self._build_chapter_table(book_index, book))

    def _build_chapter_table(self, book_index: int, book) -> Table:
        table = Table(
            title=f'{book_index + 1}: {book.name}', show_header=False, box=None, padding=(0, 2)
        )

        columns = 3
        for _ in range(columns):
            table.add_column('Index', justify='right', style='cyan')
            table.add_column('Name', style='white')

        row_buffer = []
        for index, vol in enumerate(book.vols):
            row_buffer.extend([str(index + 1), vol.name])
            if len(row_buffer) == columns * 2:
                table.add_row(*row_buffer)
                row_buffer = []

        if row_buffer:
            while len(row_buffer) < columns * 2:
                row_buffer.extend(['', ''])
            table.add_row(*row_buffer)

        return table

    def do_v(self, arg):
        """下载动漫，输入v <章节序号> <起始序号> <截止序号>，例如：v 1 11 12"""
        if not self.context.source:
            self.console.print('请您先选择动漫下载网站源！')
            return
        if not arg:
            self.console.print('请输入动漫章节序号！')
            return
        if self.context.comic is None:
            self.console.print('请先查看动漫详情！')
            return

        args = arg.split()
        try:
            book_index = parse_1_based_index(args[0], len(self.context.comic.books), '动漫章节')
            book = self.context.comic.books[book_index]
            _, vol_slice = parse_volume_slice(args, len(self.context.comic.books), len(book.vols))
        except ValueError as e:
            self.console.print(str(e))
            return
        vols = book.vols[vol_slice]
        if not self._ensure_source_download_ready():
            return
        source = self.context.source
        if source is None:
            return
        summary = source.download_vols(
            self.context.comic.name or '未知漫画',
            book.name or '默认章节',
            vols,
        )
        self.__print_download_summary(summary)

    def _download_loaded_comic(self):
        if self.context.comic is None:
            self.console.print('请先查看动漫详情！')
            return None
        if not self.context.source:
            self.console.print('当前没有选中的动漫源！')
            return None
        if not self._ensure_source_download_ready():
            return None
        return self.context.source.download_full(self.context.comic)

    def _download_search_result(self, arg: str):
        comic = self._get_search_result(arg)
        if comic is None:
            return None
        if comic.source:
            self.__switch_source(comic.source)
        if not comic.url:
            self.console.print('搜索结果缺少下载地址，无法下载。')
            return None
        return self._download_current_source_url(comic.url)

    def _get_search_result(self, arg: str) -> Comic | None:
        try:
            idx = parse_1_based_index(arg, len(self.context.searched_results), '搜索结果')
        except ValueError:
            self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
            return None
        if not self.context.searched_results:
            self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
            return None

        return self.context.searched_results[idx]

    def _download_current_source_url(self, url: str):
        if not self.context.source:
            self.console.print('无法确定源，无法下载。')
            return None
        if not self._ensure_source_download_ready():
            return None
        source = self.context.source
        if source is None:
            return None
        return source.download_full_by_url(url)

    def _download_direct_url(self, arg: str):
        matched_source = self._match_source_for_url(arg)

        if matched_source:
            self.__switch_source(matched_source)
        elif (
            self.context.source
            and hasattr(self.context.source, 'base_url')
            and arg.startswith(self.context.source.base_url)
        ):
            pass
        else:
            self.console.print('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
            return None

        return self._download_current_source_url(arg)

    def do_d(self, arg):
        """全量下载动漫，输入d <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html"""
        if not arg:
            summary = self._download_loaded_comic()
        elif arg.isdigit():
            summary = self._download_search_result(arg)
        else:
            summary = self._download_direct_url(arg)

        # self.context.searched_results.clear() # Maybe don't clear results so user can download another one?
        if summary:
            self.__print_download_summary(summary)

    def __print_download_summary(self, summary):
        if summary.ok:
            self.console.print(
                f'下载完成：成功 {summary.downloaded}，跳过 {summary.skipped}',
                style='bold green',
            )
            return
        self.console.print(
            f'下载完成，但存在失败：成功 {summary.downloaded}，跳过 {summary.skipped}，'
            f'失败 {summary.failed}，部分失败 {summary.partial}',
            style='bold yellow',
        )

    def do_q(self, arg):
        """退出动漫下载器"""
        self.context.destroy()
        self.console.print('感谢使用，再会！')
        return True


class Context:
    """
    命令行上下文类。
    """

    def __init__(self, console):
        self.output_path: str = ''
        '本机存储路径'
        self.http: requests.Session = self.create_http_session()
        '本机存储路径'
        self.searched_results: list[Comic] = []
        '动漫搜索结果数组对象'
        self.comic: Comic | None = None
        '当前查看的动漫对象'
        self.source: ComicSource | None = None
        '动漫网站源'
        self.driver: Any | None = None
        self.drivers: dict[tuple[str, bool], Any] = {}
        '网页驱动'
        self.console = console
        self.reset()

    def create(self, output_path):
        self.output_path = output_path
        self.console.print(f'动漫文件本机存储路径为: {output_path}')
        self.http = self.create_http_session()

    def create_http_session(self):
        retry_strategy = Retry(
            total=3, status_forcelist=[400, 429, 500, 502, 503, 504], allowed_methods=['GET']
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.headers.update(
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            }
        )
        http.mount('https://', adapter)
        http.mount('http://', adapter)
        return http

    def ensure_driver(self, source_or_class: ComicSource | type[ComicSource] | None = None) -> bool:
        cache_key = self._driver_cache_key(source_or_class)
        driver = self.drivers.get(cache_key)
        if driver:
            self.driver = driver
            return True

        self.console.print('正在初始化浏览器驱动...', style='dim')
        if not self.init_driver(source_or_class):
            return False
        self.drivers[cache_key] = self.driver
        return True

    def get_driver(self, source_or_class: ComicSource | type[ComicSource] | None = None):
        return self.drivers.get(self._driver_cache_key(source_or_class))

    def init_driver(self, source_or_class: ComicSource | type[ComicSource] | None = None) -> bool:
        """Initialize a browser driver for the source's configured browser mode."""
        driver_mode = self._driver_mode_for_source(source_or_class)
        if driver_mode == CLOAKBROWSER_MODE:
            return self._try_init_cloakbrowser_driver(source_or_class)
        return self._try_init_selenium_driver()

    def _try_init_selenium_driver(self) -> bool:
        drivers = [
            ('Chrome', webdriver.Chrome, ChromeOptions),
            ('Firefox', webdriver.Firefox, FirefoxOptions),
            ('Edge', webdriver.Edge, EdgeOptions),
        ]

        for name, driver_cls, options_cls in drivers:
            if self._try_init_driver(name, driver_cls, options_cls):
                return True

        self.console.print(
            '所有浏览器驱动初始化失败，请确保已安装 Firefox/Chrome/Edge 及其对应驱动。',
            style='bold red',
        )
        return False

    def _try_init_driver(self, name, driver_cls, options_cls) -> bool:
        try:
            options = options_cls()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1280,2000')
            if name == 'Chrome':
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')

            self.driver = driver_cls(options=options)
            self.console.print(f'已初始化 {name} 浏览器驱动', style='green')
            return True
        except Exception as e:
            logger.debug('初始化 {driver_name} 驱动失败: {error}', driver_name=name, error=e)
            return False

    def _try_init_cloakbrowser_driver(
        self, source_or_class: ComicSource | type[ComicSource] | None
    ) -> bool:
        try:
            self.driver = CloakBrowserDriver(
                headless=self._source_browser_headless(source_or_class),
                humanize=self._source_cloakbrowser_humanize(source_or_class),
                timeout_seconds=self._source_browser_wait_seconds(source_or_class),
                launch_options=self._source_cloakbrowser_options(source_or_class),
            )
            self.console.print('已初始化 CloakBrowser 浏览器驱动', style='green')
            return True
        except Exception as e:
            logger.debug('初始化 CloakBrowser 驱动失败: {error}', error=e, exc_info=True)
            self.console.print(f'CloakBrowser 浏览器驱动初始化失败: {e}', style='bold red')
            return False

    def _driver_cache_key(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> tuple[str, bool]:
        driver_mode = self._driver_mode_for_source(source_or_class)
        if driver_mode == CLOAKBROWSER_MODE:
            return (driver_mode, self._source_browser_headless(source_or_class))
        return (driver_mode, True)

    def _driver_mode_for_source(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> str:
        if isinstance(source_or_class, type) and issubclass(source_or_class, ComicSource):
            browser_mode = source_or_class.configured_browser_mode()
        elif isinstance(source_or_class, ComicSource):
            browser_mode = source_or_class._source_browser_mode()
        else:
            browser_mode = normalize_browser_mode(None)
        if browser_mode == CLOAKBROWSER_MODE:
            return CLOAKBROWSER_MODE
        return 'selenium'

    def _source_browser_headless(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> bool:
        browser_headless = getattr(source_or_class, 'browser_headless', None)
        if browser_headless is not None:
            return bool(browser_headless)
        seleniumbase_headless = getattr(source_or_class, 'seleniumbase_headless', None)
        if seleniumbase_headless is not None:
            return bool(seleniumbase_headless)
        return True

    def _source_browser_wait_seconds(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> float:
        wait_seconds = getattr(source_or_class, 'browser_wait_seconds', None)
        if wait_seconds is None:
            wait_seconds = getattr(source_or_class, 'seleniumbase_wait_seconds', 30.0)
        return float(30.0 if wait_seconds is None else wait_seconds)

    def _source_cloakbrowser_humanize(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> bool:
        return bool(getattr(source_or_class, 'cloakbrowser_humanize', True))

    def _source_cloakbrowser_options(
        self, source_or_class: ComicSource | type[ComicSource] | None = None
    ) -> dict[str, Any] | None:
        options = getattr(source_or_class, 'cloakbrowser_options', None)
        return dict(options) if isinstance(options, dict) else None

    def _quit_driver(self, driver) -> None:
        try:
            driver.quit()
        except Exception as e:
            logger.debug('关闭浏览器驱动失败: {error}', error=e)

    def destroy(self):
        for driver in set(self.drivers.values()):
            self._quit_driver(driver)
        self.drivers.clear()
        self.driver = None

    def reset(self):
        self.source = None
        self.reset_comic()

    def reset_comic(self):
        self.comic = None
        self.reset_result()

    def reset_result(self):
        self.searched_results = []
