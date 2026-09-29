from __future__ import annotations

import cmd
import concurrent.futures
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from downloader.browser.manager import DriverManager
from downloader.comic import Comic, ComicSource
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume, run_download_job
from downloader.runtime_config import RuntimeConfig
from downloader.sources import load_source_bindings
from downloader.sources.profiles import SourceBinding, SourceProfile
from downloader.tui import TerminalPresenter

FULL_VOLUME_ARG_COUNT = 1
VOLUME_TO_ARG_COUNT = 2
VOLUME_RANGE_ARG_COUNT = 3


def url_belongs_to_source(url: str, base_url: str) -> bool:
    """Match a supported host and port without accepting lookalikes or credentials."""
    try:
        target, base = urlsplit(url), urlsplit(base_url)
        default_ports = {'http': 80, 'https': 443}
        target_port = target.port
        base_port = base.port
        if target_port == default_ports.get(target.scheme):
            target_port = None
        if base_port == default_ports.get(base.scheme):
            base_port = None
        return bool(
            target.scheme in {'http', 'https'}
            and target.hostname
            and target.hostname == base.hostname
            and target_port == base_port
            and target.username is None
            and target.password is None
        )
    except ValueError:
        return False


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
    profile: SourceProfile
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
    # 欢迎界面由 preloop 渲染（Panel 形式），不再使用 cmd 的纯文本 intro。
    intro: str | None = None
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(
        self,
        output_path,
        overwrite=False,
        runtime_config: RuntimeConfig | None = None,
    ):
        super().__init__()
        self.presenter = TerminalPresenter()
        self.console = self.presenter.console
        self.context = Context(self.presenter)
        self.context.create(output_path)
        self.job_store = JobStore(output_path)
        self.overwrite = overwrite
        self.runtime_config = runtime_config
        self.search_driver_lock = threading.Lock()
        self.current_source_name = None
        self.prompt = self.presenter.prompt(self.current_source_name)

        # 默认源排除 deprecated 站点；完整源用于直接 URL 匹配。
        self.all_source_bindings = self._discover_source_bindings(include_deprecated=True)
        self.source_bindings = self._discover_source_bindings()
        self.all_source_map = {
            source_name: binding.source_class
            for source_name, binding in self.all_source_bindings.items()
        }
        self.source_map = {
            source_name: binding.source_class
            for source_name, binding in self.source_bindings.items()
        }
        self.source_options = list(self.source_bindings.keys())  # 存储源名称列表，方便按索引访问
        self.sources = {}
        self.last_command_ok = True

    def emptyline(self) -> bool:
        """空行不重复执行上一条下载命令。"""
        return False

    def default(self, line: str) -> None:
        self.last_command_ok = False
        self.presenter.warn(f'未知命令：{line}。输入 help 查看命令和示例。')

    def onecmd(self, line: str):
        try:
            return super().onecmd(line)
        except Exception as exc:
            self.last_command_ok = False
            logger.exception('命令执行失败: {}', line)
            self.presenter.error(f'操作失败：{exc}。可重试；详细信息见 comic_downloader.log。')
            return False

    def do_EOF(self, arg):  # noqa: N802 - cmd.Cmd dispatches the literal EOF command
        """输入结束时退出（Windows: Ctrl+Z 回车；Unix: Ctrl+D）。"""
        return self.do_q(arg)

    def do_help(self, arg):
        """显示命令速查；help v 查看范围下载用法。"""
        if not arg.strip():
            self.presenter.welcome(self.source_options)
            return
        handler = getattr(self, f'do_{arg.strip()}', None)
        if handler and handler.__doc__:
            self.presenter.info(handler.__doc__)
        else:
            self.presenter.warn('没有该命令的帮助。输入 help 查看命令速查。')

    def do_status(self, arg):
        """查看保存路径、当前源、漫画、搜索结果数和覆盖模式。"""
        self.presenter.session_status(
            self.context.output_path,
            self.current_source_name,
            self.context.comic,
            len(self.context.searched_results),
            self.overwrite,
        )

    def do_tasks(self, arg):
        """tasks [任务ID]：列出当前保存路径中的下载任务，或查看某个任务的章节与错误。"""
        self.last_command_ok = False
        if arg.strip():
            self.presenter.download_job(self.job_store.load(arg.strip()))
            self.last_command_ok = True
            return
        jobs, errors = self.job_store.list_jobs()
        self.presenter.download_jobs(jobs)
        for error in errors:
            self.presenter.warn(f'无法读取任务记录：{error}')
        self.last_command_ok = not errors

    def do_retry(self, arg):
        """retry <任务ID>：继续失败、部分失败或尚未开始的章节；保留已成功的章节。"""
        self.last_command_ok = False
        if not arg.strip():
            self.presenter.warn('请输入任务 ID；使用 tasks 查看可恢复的任务。')
            return
        job = self.job_store.load(arg.strip())
        if not job.remaining:
            run_download_job(self.job_store, job.id, None)
            self.presenter.success('该任务已全部完成，无需重试。')
            self.last_command_ok = True
            return
        if job.source_name not in self.all_source_bindings:
            self.presenter.warn(f'任务使用的源 {job.source_name} 不可用，请检查源配置。')
            return
        self.__switch_source(job.source_name)
        summary = self._execute_job(job)
        if summary is not None:
            self.__print_download_summary(summary)

    def preloop(self) -> None:
        """交互式 shell 启动时渲染一次欢迎界面。子命令模式不经过 cmdloop，不会触发。"""
        self.presenter.welcome(self.source_options)

    def _read_prompt_line(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip('\r\n')

    def _discover_source_bindings(self, include_deprecated: bool = False):
        """加载已声明的 ComicSource 实现。"""
        try:
            return load_source_bindings(
                include_deprecated=include_deprecated,
                runtime_config=self.runtime_config,
            )
        except Exception as e:
            self.presenter.error(f'Failed to load comic sources: {e}')
            return {}

    def _ensure_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
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
            self.presenter.warn('当前没有选中的动漫源！')
            return False
        profile = getattr(self.context.source, 'profile', None)
        uses_driver = (
            profile.uses_driver_for_download()
            if isinstance(profile, SourceProfile)
            else self.context.source.uses_driver_for_download()
        )
        if not uses_driver:
            return True
        if self._ensure_driver(self.context.source):
            self.context.source.driver = self.context.driver
            return True
        self.presenter.error('当前动漫源下载需要浏览器驱动，无法继续下载。')
        return False

    def _ensure_source_page_ready(self) -> bool:
        if self.context.source is None:
            self.presenter.warn('当前没有选中的动漫源！')
            return False
        if not self.context.source.current_browser_mode_uses_driver():
            return True
        if self._ensure_driver(self.context.source):
            self.context.source.driver = self.context.driver
            return True
        self.presenter.error('当前动漫源页面解析需要浏览器驱动，无法继续。')
        return False

    def _match_source_for_url(self, url: str) -> str | None:
        for source_name, binding in self.all_source_bindings.items():
            base_url = binding.profile.base_url
            if base_url and url_belongs_to_source(url, base_url):
                return source_name
        return None

    def do_source(self, arg):
        """source [源名/序号]：切换下载源；无参数时显示菜单，回车或 q 取消。搜索仍覆盖所有启用源。"""
        self.last_command_ok = False
        if not self.source_options:
            self.presenter.warn('没有启用的动漫源，请检查运行配置文件。')
            return
        if arg.strip():
            self._select_source(arg.strip())
            return
        self.presenter.source_options(
            self.source_options, self.source_bindings, self.current_source_name
        )
        try:
            while True:
                selection = self._read_prompt_line('请输入源名或序号（回车 / q 取消）: ').strip()
                if not selection or selection.lower() == 'q':
                    self.presenter.info('已取消源选择。')
                    return
                if self._select_source(selection):
                    return
        except (EOFError, KeyboardInterrupt):
            self.presenter.print()

    def _select_source(self, selection: str) -> bool:
        if selection in self.source_bindings:
            source_name = selection
        else:
            try:
                index = parse_1_based_index(selection, len(self.source_options), '源')
            except ValueError:
                self.presenter.warn(f'请输入源名或 1 到 {len(self.source_options)} 的序号。')
                return False
            source_name = self.source_options[index]
        self.__switch_source(source_name)
        self.last_command_ok = True
        self.presenter.success(f'当前下载源：{source_name}。使用 i <序号/URL> 查看详情。')
        return True

    def __switch_source(self, source_name):
        """切换动漫源"""
        if self.current_source_name == source_name:
            return
        self.presenter.source_switching(source_name)

        if source_name not in self.sources:
            binding = self.source_bindings.get(source_name) or self.all_source_bindings[source_name]
            source_class = binding.source_class
            self.sources[source_name] = source_class(
                self.context.output_path,
                self.context.http,
                self.context.get_driver(binding.profile),
                overwrite=self.overwrite,
                profile=binding.profile,
            )

        self.context.comic = None
        self.context.source = self.sources[source_name]
        self.current_source_name = source_name
        self.prompt = self.presenter.prompt(self.current_source_name)

    def _build_search_func(
        self, binding: SourceBinding, uses_driver: bool
    ) -> Callable[[str], list]:
        def _search(keyword: str) -> list:
            driver = None
            if uses_driver:
                if not self.context.ensure_driver(binding.profile):
                    raise RuntimeError('Browser driver was not initialized')
                driver = self.context.driver
            with self.context.create_http_session() as http:
                source = binding.source_class(
                    self.context.output_path,
                    http,
                    driver,
                    overwrite=self.overwrite,
                    profile=binding.profile,
                )
                return source.search(keyword)

        return _search

    def _build_search_tasks(self) -> list[SearchTask]:
        tasks = []
        for source_name in self.source_options:
            binding = self.source_bindings[source_name]
            source_class = binding.source_class
            uses_driver = binding.profile.uses_driver_for_search()
            tasks.append(
                SearchTask(
                    source_name=source_name,
                    source_class=source_class,
                    profile=binding.profile,
                    search_func=self._build_search_func(binding, uses_driver),
                    uses_driver=uses_driver,
                    display_name=getattr(source_class, 'name', source_name),
                )
            )

            if source_name not in self.sources:
                self.sources[source_name] = source_class(
                    self.context.output_path,
                    self.context.http,
                    self.context.get_driver(binding.profile),
                    overwrite=self.overwrite,
                    profile=binding.profile,
                )
        return tasks

    def _filter_ready_search_tasks(self, tasks: list[SearchTask]) -> list[SearchTask]:
        ready_tasks = []
        skipped_sources = set()
        for task in tasks:
            if not task.uses_driver or self.context.ensure_driver(task.profile):
                ready_tasks.append(task)
            else:
                skipped_sources.add(task.source_name)
        if not skipped_sources:
            return ready_tasks
        self.presenter.warn(f'已跳过需要浏览器驱动的搜索源: {", ".join(sorted(skipped_sources))}')
        return ready_tasks

    def _merge_search_outcomes(self, outcomes: list[SearchOutcome]) -> None:
        outcomes_by_source = {outcome.source_name: outcome for outcome in outcomes}
        for source_name in self.source_options:
            outcome = outcomes_by_source.get(source_name)
            if not outcome:
                continue
            if outcome.error_message:
                self.presenter.error(f'在 {source_name} 中搜索失败: {outcome.error_message}')
            self.context.searched_results.extend(outcome.results)

    def _print_search_table(self, keyword: str, search_duration: float) -> None:
        source_display_names = {
            source_name: getattr(source_obj, 'name', source_name)
            for source_name, source_obj in self.sources.items()
        }
        self.presenter.search_results(
            keyword,
            self.context.searched_results,
            source_display_names,
            search_duration,
        )

    def do_s(self, arg):
        """搜索动漫，输入s <搜索关键字>，例如：s 猎人"""
        self.last_command_ok = False
        arg = arg.strip()
        if not arg:
            self.presenter.warn('请输入搜索关键字！')
            return

        self.context.reset_comic()
        self.context.searched_results = []
        tasks = self._filter_ready_search_tasks(self._build_search_tasks())
        if not tasks:
            self.presenter.warn('没有可用于搜索的源，请检查源配置或浏览器驱动。')
            return

        task_lookup = {task.source_name: task for task in tasks}
        console_status = self.presenter.status('正在搜索...', spinner='dots')
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
        self.last_command_ok = any(outcome.error_message is None for outcome in outcomes)
        if not self.last_command_ok:
            self.presenter.error('所有搜索源均失败，请检查网络或使用 --debug 查看原因后重试。')
            return
        logger.info(
            '搜索完成: keyword={keyword}, sources={sources}, results={results}, duration={duration:.2f}s',
            keyword=arg,
            sources=len(tasks),
            results=len(self.context.searched_results),
            duration=search_duration,
        )
        self._print_search_table(arg, search_duration)

    def do_i(self, arg):
        """i <搜索结果序号/URL>：查看动漫详情和分组，例如 i 1。"""
        self.last_command_ok = False
        self.context.comic = None
        arg = arg.strip()
        if not arg:
            self.presenter.warn('请输入动漫URL地址或者搜索结果序号！')
            return

        url = self._resolve_info_url(arg)
        if url is None:
            return

        if not self.context.source:
            self.presenter.warn('无法确定该动漫所属的源，请先搜索或手动选择源。')
            return
        if not self._ensure_source_page_ready():
            return

        with self.presenter.status('正在获取详情...', spinner='dots'):
            self.context.comic = self.context.source.info(url)

        if self.context.comic is None:
            self.presenter.error('未能获取动漫详情，请检查输入的地址或稍后重试。')
            return

        self._print_comic_info(self.context.comic)
        self.last_command_ok = True

    def _resolve_info_url(self, arg: str) -> str | None:
        if arg.isdigit():
            return self._resolve_search_result_url(arg)
        return self._resolve_direct_info_url(arg)

    def _resolve_search_result_url(self, arg: str) -> str | None:
        try:
            idx = parse_1_based_index(arg, len(self.context.searched_results), '搜索结果')
        except ValueError:
            self.presenter.warn('请先搜索动漫，或输入正确的搜索结果序号！')
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
            and url_belongs_to_source(url, self.context.source.base_url)
        ):
            return url
        self.presenter.warn('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
        return None

    def _print_comic_info(self, comic: Comic) -> None:
        self.presenter.comic_info(comic)

    def _print_chapter_tables(self, comic: Comic) -> None:
        for book_index, book in enumerate(comic.books):
            self.presenter.print(self._build_chapter_table(book_index, book))

    def _build_chapter_table(self, book_index: int, book):
        return self.presenter.chapter_table(book_index, book)

    def do_v(self, arg):
        """v <分组> [截止] 或 v <分组> <起始> <截止>：序号从 1 开始，含截止话。例如 v 1 5 10。不填范围则下载该分组全部话。"""
        self.last_command_ok = False
        if not self.context.source:
            self.presenter.warn('请您先选择动漫下载网站源！')
            return
        if not arg.strip():
            self.presenter.warn('请输入动漫章节序号！')
            return
        if self.context.comic is None:
            self.presenter.warn('请先查看动漫详情！')
            return

        args = arg.split()
        try:
            book_index = parse_1_based_index(args[0], len(self.context.comic.books), '动漫章节')
            book = self.context.comic.books[book_index]
            _, vol_slice = parse_volume_slice(args, len(self.context.comic.books), len(book.vols))
        except ValueError as e:
            self.presenter.warn(str(e))
            return
        vols = book.vols[vol_slice]
        if not vols:
            self.presenter.warn('该分组没有可下载的话，请选择其他分组。')
            return
        summary = self._start_job(
            self.context.comic,
            [JobVolume(book.name or '默认章节', vol.name, vol.url) for vol in vols],
        )
        if summary is not None:
            self.__print_download_summary(summary)

    def _download_loaded_comic(self):
        if self.context.comic is None:
            self.presenter.warn('请先查看动漫详情！')
            return None
        if not self.context.source:
            self.presenter.warn('当前没有选中的动漫源！')
            return None
        return self._start_job(
            self.context.comic,
            [
                JobVolume(book.name or '默认章节', vol.name, vol.url)
                for book in self.context.comic.books
                for vol in book.vols
            ],
        )

    def _start_job(self, comic: Comic, volumes: list[JobVolume]):
        if not volumes:
            self.presenter.warn('没有可下载章节，未创建任务。')
            return None
        if not self.current_source_name:
            self.presenter.warn('无法确定下载源，请重新查看漫画详情。')
            return None
        job = DownloadJob(
            self.current_source_name,
            comic.name or '未知漫画',
            comic.url or '',
            volumes,
        )
        self.job_store.save(job)
        self.presenter.info(f'下载任务已保存：{job.id[:12]}，共 {len(volumes)} 话。')
        return self._execute_job(job)

    def _execute_job(self, job: DownloadJob):
        self.presenter.info(
            f'任务 {job.id[:12]}：剩余 {len(job.remaining)}/{len(job.volumes)} 话。'
            f'中断或失败后使用 retry {job.id[:12]} 继续。'
        )
        if not self._ensure_source_download_ready() or self.context.source is None:
            return None
        result = run_download_job(self.job_store, job.id, self.context.source)
        self.presenter.info(f'任务 {result.id[:12]} 已保存；tasks {result.id[:12]} 查看详情。')
        self.presenter.info('以下为任务累计结果，包含此前已完成的章节。')
        return result.summary

    def _download_search_result(self, arg: str):
        comic = self._get_search_result(arg)
        if comic is None:
            return None
        if comic.source:
            self.__switch_source(comic.source)
        if not comic.url:
            self.presenter.warn('搜索结果缺少下载地址，无法下载。')
            return None
        return self._download_current_source_url(comic.url)

    def _get_search_result(self, arg: str) -> Comic | None:
        try:
            idx = parse_1_based_index(arg, len(self.context.searched_results), '搜索结果')
        except ValueError:
            self.presenter.warn('请先搜索动漫，或输入正确的搜索结果序号！')
            return None
        if not self.context.searched_results:
            self.presenter.warn('请先搜索动漫，或输入正确的搜索结果序号！')
            return None

        return self.context.searched_results[idx]

    def _download_current_source_url(self, url: str):
        if not self.context.source:
            self.presenter.warn('无法确定源，无法下载。')
            return None
        self.context.comic = None
        if not self._ensure_source_page_ready():
            return None
        source = self.context.source
        if source is None:
            return None
        with self.presenter.status('正在获取下载计划...', spinner='dots'):
            self.context.comic = source.info(url)
        if self.context.comic is None:
            self.presenter.error('未能获取动漫详情，无法创建下载任务。')
            return None
        self.context.comic.url = url
        return self._download_loaded_comic()

    def _download_direct_url(self, arg: str):
        matched_source = self._match_source_for_url(arg)

        if matched_source:
            self.__switch_source(matched_source)
        elif (
            self.context.source
            and hasattr(self.context.source, 'base_url')
            and url_belongs_to_source(arg, self.context.source.base_url)
        ):
            pass
        else:
            self.presenter.warn('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
            return None

        return self._download_current_source_url(arg)

    def do_d(self, arg):
        """全量下载动漫，输入d <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html"""
        self.last_command_ok = False
        arg = arg.strip()
        if not arg:
            summary = self._download_loaded_comic()
        elif arg.isdigit():
            summary = self._download_search_result(arg)
        else:
            summary = self._download_direct_url(arg)

        if summary:
            self.__print_download_summary(summary)

    def __print_download_summary(self, summary):
        self.presenter.download_summary(summary)
        self.last_command_ok = summary.ok

    def do_q(self, arg):
        """退出动漫下载器"""
        self.context.destroy()
        self.presenter.farewell()
        return True


class Context:
    """
    命令行上下文类。
    """

    def __init__(self, presenter_or_console):
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
        if isinstance(presenter_or_console, TerminalPresenter):
            self.presenter = presenter_or_console
        else:
            self.presenter = TerminalPresenter(presenter_or_console)
        self.console = self.presenter.console
        self.driver_manager = DriverManager(self.presenter)
        self.reset()

    @property
    def driver(self):
        return self.driver_manager.current_driver

    @driver.setter
    def driver(self, value) -> None:
        self.driver_manager.current_driver = value

    @property
    def drivers(self):
        return self.driver_manager.drivers

    @drivers.setter
    def drivers(self, value) -> None:
        self.driver_manager.drivers = value

    def create(self, output_path):
        self.output_path = output_path
        self.presenter.output_path(output_path)

    def create_http_session(self):
        retry_strategy = Retry(
            total=3,
            status_forcelist=[400, 429, 500, 502, 503, 504],
            allowed_methods=['GET'],
            raise_on_status=False,
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

    def ensure_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        return self.driver_manager.ensure_driver(source_or_class)

    def get_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ):
        return self.driver_manager.get_driver(source_or_class)

    def init_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        return self.driver_manager.init_driver(source_or_class)

    def _driver_cache_key(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> tuple[str, bool]:
        return self.driver_manager.driver_cache_key(source_or_class)

    def _driver_mode_for_source(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> str:
        return self.driver_manager._driver_mode_for_source(source_or_class)

    def _profile_for_source(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None
    ) -> SourceProfile | None:
        return self.driver_manager._profile_for_source(source_or_class)

    def _source_browser_headless(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        return self.driver_manager._source_browser_headless(source_or_class)

    def _source_browser_wait_seconds(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> float:
        return self.driver_manager._source_browser_wait_seconds(source_or_class)

    def _source_cloakbrowser_humanize(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        return self.driver_manager._source_cloakbrowser_humanize(source_or_class)

    def _source_cloakbrowser_options(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> dict[str, Any] | None:
        return self.driver_manager._source_cloakbrowser_options(source_or_class)

    def destroy(self):
        self.driver_manager.destroy()
        self.http.close()

    def reset(self):
        self.source = None
        self.reset_comic()

    def reset_comic(self):
        self.comic = None
        self.reset_result()

    def reset_result(self):
        self.searched_results = []
