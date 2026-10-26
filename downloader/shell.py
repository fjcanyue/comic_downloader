from __future__ import annotations

import cmd
import concurrent.futures
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse, urlsplit

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from downloader.browser.manager import DriverManager
from downloader.comic import Comic, ComicSource
from downloader.download.job_archive import parse_archive_query
from downloader.download.job_browser import (
    TASK_PAGE_SIZE,
    TASK_VOLUME_PAGE_SIZE,
    TaskQuery,
    matching_jobs,
    matching_volumes,
    parse_task_query,
    unique_job_prefixes,
)
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume, run_download_job
from downloader.download.tasks import DownloadTask, DownloadTaskStore, DownloadTaskStoreError
from downloader.models import (
    DownloadSummary,
    SearchOutcome,
    SourceSearchResult,
    VolumeDownloadResult,
)
from downloader.runtime_config import RuntimeConfig
from downloader.sources import load_source_bindings
from downloader.sources.metadata import SourceVerification
from downloader.sources.profiles import SourceBinding, SourceProfile
from downloader.sources.verification import (
    SourceVerificationStore,
    SourceVerificationStoreError,
    verify_source_connectivity,
)
from downloader.tui import (
    CHAPTER_PAGE_SIZE,
    SEARCH_PAGE_SIZE,
    RetryTaskView,
    SourceCheckView,
    SourceStat,
    SourceView,
    TerminalPresenter,
)

FULL_VOLUME_ARG_COUNT = 1
VOLUME_TO_ARG_COUNT = 2
VOLUME_RANGE_ARG_COUNT = 3
MIN_JOB_ID_PREFIX_LENGTH = 4


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


def url_matches_base(url: str, base_url: str) -> bool:
    try:
        target = urlparse(url)
        base = urlparse(base_url)
        target_port = target.port
        base_port = base.port
    except ValueError:
        return False
    if target.scheme not in {'http', 'https'} or target.scheme != base.scheme:
        return False
    if not target.hostname or target.hostname.casefold() != (base.hostname or '').casefold():
        return False
    if target_port != base_port:
        return False
    base_path = base.path.rstrip('/')
    return not base_path or target.path == base_path or target.path.startswith(f'{base_path}/')


@dataclass(frozen=True)
class SearchTask:
    source_name: str
    source_class: type[ComicSource]
    profile: SourceProfile
    search_func: Callable[[str], list | SourceSearchResult]
    uses_driver: bool
    display_name: str
    unavailable_reason: str | None = None


class SearchUnavailableError(RuntimeError):
    pass


def _execute_search_task(
    task: SearchTask, keyword: str, per_source_limit: int | None, driver_lock: threading.Lock | None
) -> SearchOutcome:
    start = time.perf_counter()
    if task.unavailable_reason:
        return SearchOutcome(task.source_name, [], task.unavailable_reason, 0, skipped=True)
    try:
        # Selenium driver 不是线程安全的，访问时强制串行化
        if task.uses_driver:
            if driver_lock is None:
                raise RuntimeError('浏览器驱动锁未初始化')
            with driver_lock:
                results = task.search_func(keyword)
        else:
            results = task.search_func(keyword)

        response = (
            results if isinstance(results, SourceSearchResult) else SourceSearchResult(results)
        )
        trimmed = []
        for comic in response.comics:
            if per_source_limit is not None and len(trimmed) >= per_source_limit:
                break
            comic.source = task.source_name
            trimmed.append(comic)

        duration = time.perf_counter() - start
        return SearchOutcome(
            task.source_name,
            trimmed,
            response.error_message,
            duration,
            total_count=len(response.comics),
        )
    except SearchUnavailableError as e:
        return SearchOutcome(
            task.source_name, [], str(e), time.perf_counter() - start, skipped=True
        )
    except Exception as e:
        duration = time.perf_counter() - start
        logger.exception('搜索任务失败: {source_name}', source_name=task.source_name)
        return SearchOutcome(task.source_name, [], str(e) or type(e).__name__, duration)


def _run_search_serial(
    tasks: list[SearchTask],
    keyword: str,
    per_source_limit: int | None,
    driver_lock: threading.Lock | None,
    on_complete: Callable[[SearchOutcome], None] | None = None,
) -> list[SearchOutcome]:
    outcomes = []
    for task in tasks:
        outcome = _execute_search_task(task, keyword, per_source_limit, driver_lock)
        outcomes.append(outcome)
        if on_complete is not None:
            on_complete(outcome)
    return outcomes


def _run_search_parallel(  # noqa: PLR0913 - compatibility with the existing search runner
    tasks: list[SearchTask],
    keyword: str,
    per_source_limit: int | None,
    driver_lock: threading.Lock | None,
    max_workers: int | None = None,
    on_complete: Callable[[SearchOutcome], None] | None = None,
) -> list[SearchOutcome]:
    if not tasks:
        return []
    if max_workers is None:
        max_workers = min(8, len(tasks))
    if max_workers <= 1:
        return _run_search_serial(tasks, keyword, per_source_limit, driver_lock, on_complete)

    # 并行执行后按完成顺序收集，再在外层按源顺序合并
    outcomes = []
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [
            executor.submit(_execute_search_task, task, keyword, per_source_limit, driver_lock)
            for task in tasks
        ]
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            if on_complete is not None:
                on_complete(outcome)
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
        self.task_store = DownloadTaskStore(output_path)
        self.verification_store = SourceVerificationStore(output_path)
        self._verification_store_error: str | None = None
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
        self.search_keyword = ''
        self.search_duration = 0.0
        self.search_outcomes: list[SearchOutcome] = []
        self.search_filter = ''
        self.search_result_indices: list[int] | None = None
        self.search_page = 1
        self.chapter_pages: dict[int, int] = {}
        self.task_query: TaskQuery | None = None
        self.paginate_output = True

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
        if self.search_outcomes:
            self.presenter.search_report(self.search_outcomes)
        if self.search_keyword:
            self.presenter.search_position(
                self.search_filter,
                self._search_result_count(),
                len(self.context.searched_results),
                self.search_page,
            )

    def _search_result_count(self) -> int:
        if self.search_result_indices is None:
            return len(self.context.searched_results)
        return len(self.search_result_indices)

    def do_f(self, arg):
        """f [关键词]：在缓存中筛选名称、作者、源代码或源名称；空格分词且全部匹配，忽略大小写。单独输入 f 清除筛选，序号不变。"""
        self.last_command_ok = False
        if not self.search_keyword:
            self.presenter.warn('请先使用 s <关键词> 搜索。')
            return
        self.search_filter = arg.strip()
        terms = self.search_filter.casefold().split()
        self.search_result_indices = None
        if terms:
            self.search_result_indices = []
            for index, comic in enumerate(self.context.searched_results):
                fields = [comic.name, comic.author, comic.source]
                if comic.source:
                    fields.append(self._source_display_name(comic.source))
                haystack = ' '.join(field or '' for field in fields).casefold()
                if all(term in haystack for term in terms):
                    self.search_result_indices.append(index)
        self.search_page = 1
        self._print_search_table(self.search_keyword, self.search_duration)
        self.last_command_ok = True

    def do_p(self, arg):
        """p [页码/next/prev]：翻看缓存搜索结果，每页 20 条；无参数重显当前页，支持筛选，序号不变。"""
        self.last_command_ok = False
        if not self.search_keyword:
            self.presenter.warn('请先使用 s <关键词> 搜索。')
            return
        try:
            page = self._read_page(
                arg, self._search_result_count(), SEARCH_PAGE_SIZE, self.search_page
            )
        except ValueError as exc:
            self.presenter.warn(str(exc))
            return
        self._print_search_table(self.search_keyword, self.search_duration, page=page)
        self.search_page = page
        self.last_command_ok = True

    def do_ch(self, arg):
        """ch <分组> [页码/next/prev]：翻看章节，每页 60 话；无页码重显该分组当前页，下载使用原话序号。"""
        self.last_command_ok = False
        if self.context.comic is None:
            self.presenter.warn('请先使用 i <序号/URL> 查看漫画详情。')
            return
        args = arg.split()
        if not 1 <= len(args) <= VOLUME_TO_ARG_COUNT:
            self.presenter.warn('用法：ch <分组> [页码]，例如 ch 1 2。')
            return
        try:
            book_index = parse_1_based_index(args[0], len(self.context.comic.books), '分组')
            book = self.context.comic.books[book_index]
            page = self._read_page(
                args[1] if len(args) == VOLUME_TO_ARG_COUNT else '',
                len(book.vols),
                CHAPTER_PAGE_SIZE,
                self.chapter_pages.get(book_index, 1),
            )
        except ValueError as exc:
            self.presenter.warn(str(exc))
            return
        self.presenter.chapter_page(book_index, book, page)
        self.chapter_pages[book_index] = page
        self.last_command_ok = True

    @staticmethod
    def _read_page(arg: str, total: int, page_size: int, current: int = 1) -> int:
        pages = max(1, (total + page_size - 1) // page_size)
        value = arg.strip().casefold()
        if value == 'next':
            if current >= pages:
                raise ValueError(f'已是最后一页（第 {current}/{pages} 页）。')
            return current + 1
        if value == 'prev':
            if current <= 1:
                raise ValueError(f'已是第一页（共 {pages} 页）。')
            return current - 1
        try:
            return parse_1_based_index(value or str(current), pages, '页码') + 1
        except ValueError:
            raise ValueError(f'页码必须是 1～{pages} 的整数，或 next / prev。') from None

    def do_tasks(self, arg):
        """tasks [状态] [页码] 或 tasks <任务ID> [状态] [页码]；tasks [状态] [页码] find <关键词> 查找漫画名、源代码或 ID；tasks next/prev 保留条件翻页。状态：all/unfinished/failed/completed/pending，列表另支持 running/interrupted。tasks 返回全部任务首页；查找不改变 retry all 的范围。"""
        self.last_command_ok = False
        try:
            query = parse_task_query(arg.split(), self.task_query)
            if query.job_id:
                query = self._show_task_detail(query)
            else:
                self._show_task_list(query)
        except ValueError as exc:
            self.presenter.warn(str(exc))
            return
        self.task_query = query

    def _show_task_list(self, query: TaskQuery) -> None:
        jobs, errors = self.job_store.list_summaries()
        matches = matching_jobs(jobs, query.status, query.keyword)
        self._read_page(str(query.page), len(matches), TASK_PAGE_SIZE)
        start = (query.page - 1) * TASK_PAGE_SIZE
        self.presenter.task_overview(jobs, unreadable=len(errors))
        self.presenter.task_position(query, len(matches), len(jobs), TASK_PAGE_SIZE)
        self.presenter.download_jobs(
            matches[start : start + TASK_PAGE_SIZE], prefixes=unique_job_prefixes(jobs)
        )
        self.presenter.task_navigation(
            query, len(matches), TASK_PAGE_SIZE, interactive=self.paginate_output
        )
        for error in errors:
            self.presenter.warn(f'无法读取任务记录：{error}')
        self.last_command_ok = not errors

    def _show_task_detail(self, query: TaskQuery) -> TaskQuery:
        job = self.job_store.load(query.job_id or '')
        query = replace(query, job_id=job.id)
        indices = matching_volumes(job, query.status)
        self._read_page(str(query.page), len(indices), TASK_VOLUME_PAGE_SIZE)
        start = (query.page - 1) * TASK_VOLUME_PAGE_SIZE
        self.presenter.task_position(query, len(indices), len(job.volumes), TASK_VOLUME_PAGE_SIZE)
        self.presenter.download_job(
            job, volume_indices=indices[start : start + TASK_VOLUME_PAGE_SIZE]
        )
        self.presenter.task_navigation(
            query, len(indices), TASK_VOLUME_PAGE_SIZE, interactive=self.paginate_output
        )
        self.last_command_ok = True
        return query

    def do_archive(self, arg):
        """archive [list [页码]] 查看归档；archive <任务ID> 归档已完成计划；archive show <任务ID> [页码] 查看详情；archive restore <任务ID> 恢复。仅移动计划记录，不改变漫画文件。"""
        self.last_command_ok = False
        try:
            query = parse_archive_query(arg.split())
            if query.action in {'archive', 'restore'}:
                operation = (
                    self.job_store.archive if query.action == 'archive' else self.job_store.restore
                )
                job = operation(query.job_id or '')
                label = '已归档' if query.action == 'archive' else '已恢复到任务列表'
                self.presenter.success(f'{label}：{job.comic_name}（{job.id}）')
                self.presenter.info(
                    f'archive restore {job.id} 可恢复；archive 查看归档。'
                    if query.action == 'archive'
                    else f'tasks {job.id} 查看详情。'
                )
                self.last_command_ok = True
            else:
                self._show_archive(query.job_id, query.page)
        except (ValueError, OSError) as exc:
            self.presenter.warn(str(exc))

    def _show_archive(self, job_id: str | None, page: int) -> None:
        store = self.job_store.archive_view()
        if job_id:
            job = store.load(job_id)
            count = len(job.volumes)
            size = TASK_VOLUME_PAGE_SIZE
            self._read_page(str(page), count, size)
            start = (page - 1) * size
            self.presenter.download_job(
                job, volume_indices=list(range(start, min(start + size, count))), archived=True
            )
            command = f'archive show {job.id}'
            errors = []
        else:
            jobs, errors = store.list_summaries()
            count = len(jobs)
            size = TASK_PAGE_SIZE
            self._read_page(str(page), count, size)
            start = (page - 1) * size
            self.presenter.download_jobs(
                jobs[start : start + size], prefixes=unique_job_prefixes(jobs), archived=True
            )
            command = 'archive list'
        self.presenter.archive_navigation(command, page, count, size)
        for error in errors:
            self.presenter.warn(f'无法读取归档记录：{error}')
        self.last_command_ok = not errors

    def do_retry(self, arg):
        """retry [序号/任务ID/all]：查看或恢复下载；tasks 中的计划使用任务 ID，章节记录支持序号。"""
        self.last_command_ok = False
        selection = arg.strip().casefold()
        jobs, errors = self.job_store.list_jobs()
        if selection and selection != 'all':
            matches = [
                job
                for job in jobs
                if len(selection) >= MIN_JOB_ID_PREFIX_LENGTH and job.id.startswith(selection)
            ]
            if matches:
                self._retry_job(selection)
                return
            self._retry_chapter_tasks(selection)
            return
        for error in errors:
            self.presenter.warn(f'无法读取任务记录：{error}')
        pending_jobs = [job for job in jobs if job.remaining]
        if not selection:
            if pending_jobs:
                self.presenter.download_jobs(pending_jobs)
            self._retry_chapter_tasks('')
            self.last_command_ok = self.last_command_ok and not errors
            return
        ok = not errors
        for job in pending_jobs:
            self._retry_job(job.id)
            ok = self.last_command_ok and ok
        # A chapter may also belong to a saved plan. Do not retry it twice in one command.
        covered = {(job.source_name, vol.url) for job in pending_jobs for vol in job.volumes}
        tasks = self._pending_download_tasks()
        if tasks is None:
            self.last_command_ok = False
            return
        summary = DownloadSummary()
        for task in tasks:
            if (task.source_name, task.source_url) not in covered:
                summary.add(self._retry_download_task(task))
        if summary.volume_results:
            self.__print_download_summary(summary)
            ok = self.last_command_ok and ok
        self.last_command_ok = ok

    def _retry_job(self, arg):
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
        base_url = self.all_source_bindings[job.source_name].profile.base_url
        if any(not url_matches_base(volume.url, base_url) for volume in job.remaining):
            self.presenter.warn('任务 URL 不属于记录的动漫源。')
            return
        self.__switch_source(job.source_name)
        summary = self._execute_job(job)
        if summary is not None:
            self.__print_download_summary(summary)

    def preloop(self) -> None:
        """交互式 shell 启动时渲染一次欢迎界面。子命令模式不经过 cmdloop，不会触发。"""
        self.presenter.welcome(self._source_display_names())

    def _source_display_names(self) -> list[str]:
        """按源顺序解析展示用中文名（读漫屋、摩锐漫画…），缺失时回退到源代码名。"""
        return [self._source_display_name(source_name) for source_name in self.source_options]

    def _source_display_name(self, source_name: str) -> str:
        binding = self.source_bindings.get(source_name) or self.all_source_bindings.get(source_name)
        if binding is None:
            return source_name
        return getattr(binding.source_class, 'name', source_name)

    def _source_views(self) -> list[SourceView]:
        verifications = self._load_source_verifications()
        views: list[SourceView] = []
        for index, source_name in enumerate(self.source_options, start=1):
            binding = self.source_bindings[source_name]
            verification = verifications.get(source_name, SourceVerification())
            views.append(
                SourceView(
                    index=index,
                    source_name=source_name,
                    display_name=self._source_display_name(source_name),
                    browser_mode=binding.profile.browser_mode,
                    search_uses_driver=binding.profile.uses_driver_for_search(),
                    download_uses_driver=binding.profile.uses_driver_for_download(),
                    selected=source_name == self.current_source_name,
                    supports_search=binding.profile.capabilities.search,
                    supports_info=binding.profile.capabilities.info,
                    supports_download=binding.profile.capabilities.download,
                    verification_status=verification.status,
                    last_verified_at=verification.checked_at,
                )
            )
        return views

    def _load_source_verifications(self) -> dict[str, SourceVerification]:
        try:
            results = self.verification_store.load_all()
            self._verification_store_error = None
            return results
        except SourceVerificationStoreError as exc:
            logger.warning('无法读取来源验证记录: {}', exc)
            self._verification_store_error = str(exc)
            return {}

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
            bindings = load_source_bindings(
                include_deprecated=include_deprecated,
                runtime_config=self.runtime_config,
            )
        except Exception as e:
            logger.error('Failed to load comic sources: {}', e, exc_info=True)
            self.presenter.error(f'Failed to load comic sources: {e}')
            return {}
        if not bindings and not include_deprecated:
            logger.warning('No comic sources were loaded')
            self.presenter.warn('未加载到任何动漫源，请检查配置。')
        return bindings

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

    def do_sources(self, arg):
        """查看已启用动漫源的加载方式与浏览器依赖。"""
        self.presenter.source_catalog(self._source_views())
        if self._verification_store_error:
            self.presenter.source_verification_store_error(self._verification_store_error)
        self.last_command_ok = self._verification_store_error is None

    def do_check(self, arg):
        """显式检查动漫源连通性；支持 check <序号/代码名/all>。"""
        self.last_command_ok = False
        selection = arg.strip()
        if not selection:
            self.do_sources('')
            self.presenter.info('输入 check <序号/代码名> 检查单个来源，或 check all 检查全部。')
            return
        if not self.source_options:
            self.presenter.source_catalog([])
            return

        if selection.casefold() == 'all':
            source_names = list(self.source_options)
        else:
            source_name = self._resolve_source_selection(selection)
            if source_name is None:
                self.presenter.source_not_found(selection, len(self.source_options))
                return
            source_names = [source_name]

        if not source_names:
            self.presenter.source_catalog([])
            return

        self.presenter.source_check_started(len(source_names))
        results = self._run_source_checks(source_names)
        persisted = True
        try:
            self.verification_store.save_all(results)
            self._verification_store_error = None
        except SourceVerificationStoreError as exc:
            persisted = False
            self._verification_store_error = str(exc)
            self.presenter.source_verification_store_error(str(exc))
        self.presenter.source_check_summary(
            self._source_check_views(source_names, results),
            persisted=persisted,
        )
        self.last_command_ok = persisted and all(
            result.status == 'healthy' for result in results.values()
        )

    def _run_source_checks(self, source_names: list[str]) -> dict[str, SourceVerification]:
        max_workers = min(4, len(source_names))
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_sources = {
                executor.submit(self._check_source, source_name): source_name
                for source_name in source_names
            }
            results = {
                future_sources[future]: future.result()
                for future in concurrent.futures.as_completed(future_sources)
            }
            executor.shutdown(wait=True)
            return results
        except (KeyboardInterrupt, SystemExit):
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        except Exception:
            executor.shutdown(wait=True)
            raise

    def _check_source(self, source_name: str) -> SourceVerification:
        http = self.context.create_http_session(retry_total=0)
        try:
            return verify_source_connectivity(self.source_bindings[source_name].profile, http)
        finally:
            http.close()

    def _source_check_views(
        self,
        source_names: list[str],
        results: dict[str, SourceVerification],
    ) -> list[SourceCheckView]:
        views: list[SourceCheckView] = []
        for source_name in source_names:
            result = results[source_name]
            views.append(
                SourceCheckView(
                    index=self.source_options.index(source_name) + 1,
                    source_name=source_name,
                    display_name=self._source_display_name(source_name),
                    status=result.status,
                    checked_at=result.checked_at or '',
                    latency_seconds=result.latency_seconds,
                    http_status=result.http_status,
                    message=result.message,
                    final_url=result.final_url,
                    error_type=result.error_type,
                )
            )
        return views

    def do_source(self, arg):
        """source [源名/序号]：切换下载源；无参数时显示菜单，回车或 q 取消。搜索仍覆盖所有启用源。"""
        self.last_command_ok = False
        if not self.source_options:
            self.presenter.warn('没有启用的动漫源，请检查运行配置文件。')
            return
        if arg.strip():
            self._select_source(arg.strip())
            return
        self.presenter.source_catalog(self._source_views(), selection_mode=True)
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
        source_name = self._resolve_source_selection(selection)
        if source_name is None:
            self.presenter.source_not_found(selection, len(self.source_options))
            return False
        self.__switch_source(source_name)
        self.last_command_ok = True
        return True

    def _retry_chapter_tasks(self, arg):
        """查看或重试未完成下载任务；支持 retry <序号/任务ID/all>。"""
        self.last_command_ok = False
        tasks = self._pending_download_tasks()
        if tasks is None:
            return
        selection = arg.strip()
        if not selection:
            self.presenter.retry_tasks(self._retry_task_views(tasks))
            self.last_command_ok = True
            return

        selected_tasks = self._resolve_retry_tasks(selection, tasks)
        if selected_tasks is None:
            self.presenter.retry_selection_not_found(selection)
            return

        summary = DownloadSummary()
        for task in selected_tasks:
            summary.add(self._retry_download_task(task))
        self.__print_download_summary(summary)

    def _pending_download_tasks(self) -> list[DownloadTask] | None:
        try:
            return self.task_store.list_pending()
        except DownloadTaskStoreError as exc:
            self.presenter.retry_store_error(str(exc))
            return None

    def _retry_task_views(self, tasks: list[DownloadTask]) -> list[RetryTaskView]:
        return [
            RetryTaskView(
                index=index,
                task_id=task.task_id,
                source_name=self._source_display_name(task.source_name),
                volume_name=task.volume_name,
                status=task.status,
                attempts=task.attempts,
                updated_at=task.updated_at,
                message=task.message,
            )
            for index, task in enumerate(tasks, start=1)
        ]

    def _resolve_retry_tasks(
        self, selection: str, tasks: list[DownloadTask]
    ) -> list[DownloadTask] | None:
        if selection.casefold() == 'all':
            return tasks
        if selection.isdigit():
            try:
                index = parse_1_based_index(selection, len(tasks), '下载任务')
            except ValueError:
                return None
            return [tasks[index]]
        matches = [task for task in tasks if task.task_id.startswith(selection.casefold())]
        return matches if len(matches) == 1 else None

    def _retry_download_task(self, task: DownloadTask) -> VolumeDownloadResult:
        binding = self.source_bindings.get(task.source_name)
        if binding is None:
            return VolumeDownloadResult(
                name=task.volume_name,
                url=task.source_url,
                status='failed',
                message=f'动漫源 {task.source_name} 当前未启用',
            )
        if not url_matches_base(task.source_url, binding.profile.base_url):
            return VolumeDownloadResult(
                name=task.volume_name,
                url=task.source_url,
                status='failed',
                message='任务 URL 不属于记录的动漫源',
            )
        try:
            self.__switch_source(task.source_name)
            if not self._ensure_source_page_ready() or not self._ensure_source_download_ready():
                return VolumeDownloadResult(
                    name=task.volume_name,
                    url=task.source_url,
                    status='failed',
                    message='动漫源所需浏览器未就绪',
                )
            source = self.context.source
            if source is None:
                raise DownloadTaskStoreError('未能创建任务所属动漫源。')
            return source.retry_download_task(task)
        except Exception as exc:
            logger.error('重试下载任务失败: {}', task.task_id, exc_info=True)
            return VolumeDownloadResult(
                name=task.volume_name,
                url=task.source_url,
                status='failed',
                message=str(exc),
            )

    def _resolve_source_selection(self, selection: str) -> str | None:
        if selection.isdigit():
            try:
                index = parse_1_based_index(selection, len(self.source_options), '动漫源')
            except ValueError:
                return None
            return self.source_options[index]

        normalized = selection.casefold()
        for source_name in self.source_options:
            if normalized in {
                source_name.casefold(),
                self._source_display_name(source_name).casefold(),
            }:
                return source_name
        return None

    def __switch_source(self, source_name):
        """切换动漫源"""
        display_name = self._source_display_name(source_name)
        if self.current_source_name == source_name:
            self.presenter.source_unchanged(display_name)
            return

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
        self.prompt = self.presenter.prompt(display_name)
        self.presenter.source_selected(display_name, source_name)

    def _build_search_func(
        self, binding: SourceBinding, uses_driver: bool
    ) -> Callable[[str], SourceSearchResult]:
        def _search(keyword: str) -> SourceSearchResult:
            # Browser APIs may require creation, use and cleanup on the same thread.
            manager = DriverManager(self.presenter) if uses_driver else None
            try:
                if self.context._closed.is_set():
                    raise SearchUnavailableError('搜索已取消')
                if manager is not None and not manager.ensure_driver(binding.profile):
                    raise SearchUnavailableError('浏览器驱动未就绪，请检查安装或源配置。')
                if self.context._closed.is_set():
                    raise SearchUnavailableError('搜索已取消')
                with self.context.create_http_session() as http:
                    source = binding.source_class(
                        self.context.output_path,
                        http,
                        manager.current_driver if manager is not None else None,
                        overwrite=self.overwrite,
                        profile=binding.profile,
                    )
                    return source.search_with_diagnostics(keyword)
            finally:
                if manager is not None:
                    manager.destroy()

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
                    unavailable_reason=getattr(source_class, 'search_unavailable_reason', None),
                )
            )

        return tasks

    def _merge_search_outcomes(self, outcomes: list[SearchOutcome]) -> None:
        outcomes_by_source = {outcome.source_name: outcome for outcome in outcomes}
        for source_name in self.source_options:
            outcome = outcomes_by_source.get(source_name)
            if not outcome:
                continue
            self.context.searched_results.extend(outcome.results)

    def _print_search_table(
        self,
        keyword: str,
        search_duration: float,
        source_stats: list[SourceStat] | None = None,
        *,
        page: int = 1,
    ) -> None:
        source_display_names = {
            source_name: getattr(binding.source_class, 'name', source_name)
            for source_name, binding in self.source_bindings.items()
        }
        self.presenter.search_results(
            keyword,
            self.context.searched_results,
            source_display_names,
            search_duration,
            page=page,
            page_size=SEARCH_PAGE_SIZE if self.paginate_output else None,
            source_stats=source_stats,
            result_indices=self.search_result_indices,
            filter_text=self.search_filter,
        )

    def _build_source_stats(
        self, outcomes: list[SearchOutcome], task_lookup: dict[str, SearchTask]
    ) -> list[SourceStat]:
        """把各源搜索结果汇总为 SourceStat 列表，按用户可见的源顺序排列。"""
        outcome_by_source = {outcome.source_name: outcome for outcome in outcomes}
        stats: list[SourceStat] = []
        for source_name in self.source_options:
            outcome = outcome_by_source.get(source_name)
            task = task_lookup.get(source_name)
            display_name = task.display_name if task else source_name
            if outcome is None:
                continue
            stats.append(
                SourceStat(
                    display_name=display_name,
                    ok=outcome.error_message is None,
                    duration=outcome.duration,
                    error=outcome.error_message,
                )
            )
        return stats

    def do_s(self, arg):
        """搜索动漫，输入s <搜索关键字>，例如：s 猎人"""
        self.last_command_ok = False
        arg = arg.strip()
        if not arg:
            self.presenter.warn('请输入搜索关键字！')
            return

        self.context.reset_comic()
        self.context.searched_results = []
        self.search_keyword = arg
        self.search_duration = 0
        self.search_outcomes = []
        self.search_filter = ''
        self.search_result_indices = None
        self.search_page = 1
        tasks = self._build_search_tasks()
        if not tasks:
            self.presenter.warn('没有可用于搜索的源，请检查源配置或浏览器驱动。')
            return

        console_status = self.presenter.status(f'正在搜索 0/{len(tasks)} 个源...', spinner='dots')
        search_start = time.perf_counter()

        def completed(outcome: SearchOutcome) -> None:
            self.search_outcomes.append(outcome)
            console_status.update(
                self.presenter.search_progress(outcome, len(self.search_outcomes), len(tasks))
            )

        with console_status:
            outcomes = _run_search_parallel(
                tasks,
                arg,
                None,
                self.search_driver_lock,
                max_workers=min(8, len(tasks)),
                on_complete=completed,
            )

        search_duration = time.perf_counter() - search_start
        self.search_duration = search_duration
        outcome_map = {outcome.source_name: outcome for outcome in outcomes}
        self.search_outcomes = [
            outcome_map[name] for name in self.source_options if name in outcome_map
        ]
        self._merge_search_outcomes(outcomes)
        self.presenter.search_report(self.search_outcomes)
        self.last_command_ok = any(outcome.ok for outcome in outcomes)
        if self.last_command_ok and any(not outcome.ok for outcome in outcomes):
            self.presenter.warn('部分源未参与或未完成搜索，结果可能不完整，请查看上方说明。')
        if not self.last_command_ok:
            message = (
                '没有源完成搜索'
                if any(outcome.skipped for outcome in outcomes)
                else '所有搜索源均失败'
            )
            self.presenter.error(f'{message}，请检查源状态或使用 --debug 查看原因后重试。')
            if not self.context.searched_results:
                return
        source_stats = self._build_source_stats(
            outcomes, {task.source_name: task for task in tasks}
        )
        logger.info(
            '搜索完成: keyword={keyword}, sources={sources}, results={results}, duration={duration:.2f}s',
            keyword=arg,
            sources=len(tasks),
            results=len(self.context.searched_results),
            duration=search_duration,
        )
        self._print_search_table(arg, search_duration, source_stats)

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
        self.chapter_pages.clear()
        self.presenter.comic_info(comic, paginate=self.paginate_output)

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
        self.presenter.comic_parse_notes(comic, downloading=True)
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

    # help 的快捷别名，降低记忆负担；交互过程中随时可调用。
    # 注意：cmd 的 parseline 已把行首 '?' 改写为 'help'，故无需再定义 do_?。
    do_h = do_help


class Context:
    """
    命令行上下文类。
    """

    def __init__(self, presenter_or_console):
        self._closed = threading.Event()
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

    def create_http_session(self, retry_total: int = 3):
        retry_strategy = Retry(
            total=retry_total,
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
        if self._closed.is_set():
            return False
        ready = self.driver_manager.ensure_driver(source_or_class)
        if self._closed.is_set():
            self.driver_manager.destroy()
            return False
        return ready

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
        self._closed.set()
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
