from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from downloader.download.job_archive import ArchiveQuery
from downloader.download.job_browser import TASK_FILTER_LABELS, JobSummary, TaskQuery
from downloader.download.jobs import DownloadJob
from downloader.models import Comic, DownloadSummary, SearchOutcome, VolumeDownloadResult

# ---------------------------------------------------------------------------
# 主题配色：集中管理，避免裸色字符串散落各处。
#   cyan  - 品牌/序号/强调
#   green - 成功/已完成
#   yellow- 警告/跳过
#   red   - 错误/失败
#   dim   - 次要信息/路径
# ---------------------------------------------------------------------------
ACCENT = 'cyan'
SUCCESS = 'green'
WARN = 'yellow'
ERROR = 'red'
MUTED = 'dim'

BRAND = '动漫下载器'
MAX_FAILURE_DETAIL_ROWS = 5
MAX_URL_DISPLAY_WIDTH = 50
COMPACT_SEARCH_WIDTH = 80
COMPACT_TASK_WIDTH = 60
WIDE_TASK_WIDTH = 100
JOB_STATE_STYLES = {
    'completed': SUCCESS,
    'failed': ERROR,
    'interrupted': WARN,
    'running': ACCENT,
    'pending': MUTED,
}
SEARCH_PAGE_SIZE = 20
CHAPTER_PAGE_SIZE = 60
SEARCH_STATE_LABELS = {
    'success': '有结果',
    'empty': '未检出',
    'failed': '失败',
    'partial': '部分结果',
    'skipped': '跳过',
}
MIN_SOURCE_CODE_COLUMN_WIDTH = 88
MAX_COMMAND_PANEL_WIDTH = 96
MAX_SOURCE_PANEL_WIDTH = 112


@dataclass(frozen=True)
class SourceStat:
    """单个搜索源在一次搜索中的执行结果摘要，用于在搜索结果下方汇总展示。"""

    display_name: str
    ok: bool
    duration: float
    error: str | None = None


@dataclass(frozen=True)
class SourceView:
    """面向终端展示的动漫源能力快照。"""

    index: int
    source_name: str
    display_name: str
    browser_mode: str
    search_uses_driver: bool
    download_uses_driver: bool
    selected: bool = False
    supports_search: bool = True
    supports_info: bool = True
    supports_download: bool = True
    verification_status: str = 'unchecked'
    last_verified_at: str | None = None


@dataclass(frozen=True)
class SourceCheckView:
    index: int
    source_name: str
    display_name: str
    status: str
    checked_at: str
    latency_seconds: float | None = None
    http_status: int | None = None
    message: str | None = None
    final_url: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class RetryTaskView:
    index: int
    task_id: str
    source_name: str
    volume_name: str
    status: str
    attempts: int
    updated_at: str
    message: str | None = None


class TerminalPresenter:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # ------------------------------------------------------------------
    # 基础打印
    # ------------------------------------------------------------------
    def print(self, message: Any = '', style: str | None = None) -> None:
        self.console.print(message, style=style)

    def status(self, message: str, spinner: str = 'dots'):
        return self.console.status(message, spinner=spinner)

    # ------------------------------------------------------------------
    # 语义化提示：调用方只传语义，不传样式
    # ------------------------------------------------------------------
    def info(self, message: Any) -> None:
        self.print(Text(str(message)))

    def success(self, message: Any) -> None:
        self.print(Text(f'成功 {message}', style=f'bold {SUCCESS}'))

    def warn(self, message: Any) -> None:
        self.print(Text(f'注意 {message}', style=f'bold {WARN}'))

    def error(self, message: Any) -> None:
        self.print(Text(f'错误 {message}', style=f'bold {ERROR}'))

    # ------------------------------------------------------------------
    # 提示符与路径
    # ------------------------------------------------------------------
    def prompt(self, source_name: str | None = None) -> str:
        if source_name:
            return f'{BRAND}[{source_name}]> '
        return f'{BRAND}> '

    def output_path(self, path: str) -> None:
        self.print(
            Panel.fit(
                Text(f'本机存储路径  {path}', style=ACCENT),
                border_style=MUTED,
                padding=(0, 1),
            )
        )

    # ------------------------------------------------------------------
    # 命令速查：welcome 与 help 复用同一份文本，避免两处不一致。
    # ------------------------------------------------------------------
    def _command_cheatsheet(self) -> Table:
        entries = [
            ('s', '<关键词>', '从所有启用源搜索动漫'),
            ('browse', '', '键盘浏览：Enter 详情，d 确认下载'),
            ('i', '<序号/URL>', '查看动漫详情'),
            ('f', '[关键词]', '筛选缓存结果；不填则清除'),
            ('p', '[页码/next/prev]', '翻看筛选结果；不填重显当前页'),
            ('ch', '<分组> [页码]', '翻看章节，也支持 next / prev'),
            ('status', '', '查看当前漫画、路径和覆盖模式'),
            ('tasks', '[状态/任务ID]', '筛选下载任务；next / prev 翻页'),
            ('tasks find', '<关键词>', '按漫画名、源代码或 ID 查找计划'),
            ('archive', '[list/任务ID/show/restore]', '归档已完成计划、查看或恢复归档'),
            ('archive find', '<关键词>', '查找归档；archive next / prev 翻页'),
            ('d', '[序号/URL]', '下载当前或指定动漫'),
            ('v', '<章节> [范围]', '按范围下载章节'),
            ('source', '[序号/代码名]', '查看并切换动漫源'),
            ('sources', '', '查看动漫源能力概览'),
            ('check', '[序号/代码名/all]', '显式检查动漫源连通性'),
            ('retry', '[序号/任务ID/all]', '查看或重试未完成任务'),
            ('help / ?', '', '查看命令速查'),
            ('q', '', '退出'),
        ]
        compact = self.console.width < COMPACT_SEARCH_WIDTH
        commands = Table.grid(padding=(0, 1 if compact else 2))
        commands.add_column(style=f'bold {ACCENT}', no_wrap=True)
        if compact:
            commands.add_column(overflow='fold')
        else:
            commands.add_column(style=MUTED, no_wrap=True)
            commands.add_column(overflow='fold')
        for command, usage, description in entries:
            if compact:
                detail = Text(usage + '\n', style=MUTED) if usage else Text()
                detail.append(description)
                commands.add_row(command, detail)
            else:
                commands.add_row(command, usage, description)
        return commands

    def _command_panel_body(self) -> Group:
        return Group(
            Text('命令速查', style='bold'),
            Text(''),
            self._command_cheatsheet(),
        )

    # ------------------------------------------------------------------
    # 欢迎与退出
    # ------------------------------------------------------------------
    def welcome(self, source_names: list[str] | None = None) -> None:
        source_summary = '尚未加载动漫源'
        if source_names:
            source_summary = f'已启用 {len(source_names)} 个动漫源，输入 sources 查看能力概览'

        self.print(
            Panel(
                Group(
                    Text(BRAND, style=f'bold {ACCENT}'),
                    Text('多源搜索 · 按章节下载 · 自动复用已下载图片', style=MUTED),
                    Text(''),
                    self._command_panel_body(),
                    Text(''),
                    Text(source_summary, style=MUTED),
                ),
                border_style=ACCENT,
                padding=(1, 2),
                title='开始使用',
                title_align='left',
                width=min(self.console.width, MAX_COMMAND_PANEL_WIDTH),
            )
        )

    def help(self) -> None:
        """随时可调用的命令速查面板，交互过程中也能查看。"""
        self.print(
            Panel(
                self._command_panel_body(),
                border_style=ACCENT,
                padding=(1, 2),
                title='命令速查',
                title_align='left',
                width=min(self.console.width, MAX_COMMAND_PANEL_WIDTH),
            )
        )

    def farewell(self) -> None:
        self.print()
        self.print(Rule(style=MUTED))
        self.print(f'感谢使用 {BRAND}，再会！', style=f'bold {ACCENT}')

    # ------------------------------------------------------------------
    # 源选择
    # ------------------------------------------------------------------
    def source_catalog(self, sources: list[SourceView], *, selection_mode: bool = False) -> None:
        """展示动漫源、页面加载方式以及搜索/下载所需能力。"""
        panel_width = min(self.console.width, MAX_SOURCE_PANEL_WIDTH)
        if not sources:
            self.print(
                Panel(
                    Group(
                        Text('没有启用的动漫源。', style=f'bold {WARN}'),
                        Text('请检查运行配置中的 sources.<名称>.enabled。', style=MUTED),
                    ),
                    border_style=WARN,
                    padding=(1, 2),
                    title='动漫源',
                    title_align='left',
                    width=panel_width,
                )
            )
            return

        table = Table(
            box=None,
            collapse_padding=True,
            expand=True,
            header_style=f'bold {ACCENT}',
            pad_edge=False,
            row_styles=['none', MUTED],
        )
        table.add_column('', width=1, justify='center', no_wrap=True)
        table.add_column('#', width=3, justify='right', style=ACCENT, no_wrap=True)
        table.add_column('动漫源', min_width=8, overflow='ellipsis', no_wrap=True)
        if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
            table.add_column('代码名', min_width=8, style=MUTED, no_wrap=True)
        table.add_column('页面加载', min_width=8, no_wrap=True)
        table.add_column('搜索', min_width=6, no_wrap=True)
        table.add_column('详情', min_width=6, no_wrap=True)
        table.add_column('下载', min_width=6, no_wrap=True)
        table.add_column('验证', min_width=6, no_wrap=True)

        for source in sources:
            row = [
                f'[{ACCENT}]>[/]' if source.selected else '',
                str(source.index),
                source.display_name,
            ]
            if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
                row.append(source.source_name)
            row.extend(
                [
                    self._browser_mode_label(source.browser_mode),
                    self._access_label(source.supports_search, source.search_uses_driver),
                    self._access_label(
                        source.supports_info,
                        source.browser_mode != 'requests',
                    ),
                    self._access_label(source.supports_download, source.download_uses_driver),
                    self._verification_label(
                        source.verification_status,
                        source.last_verified_at,
                    ),
                ]
            )
            table.add_row(*row, style='bold' if source.selected else None)

        hint = (
            '输入序号、代码名或动漫源名称进行切换；回车 / q 取消。'
            if selection_mode
            else '使用 source <序号/代码名> 切换；使用 check <序号/代码名/all> 显式验证。'
        )
        self.print(
            Panel(
                Group(table, Text(''), Text(hint, style=MUTED)),
                border_style=ACCENT,
                padding=(1, 2),
                title=f'动漫源 · {len(sources)} 个已启用',
                title_align='left',
                width=panel_width,
            )
        )

    @staticmethod
    def _browser_mode_label(browser_mode: str) -> str:
        labels = {
            'requests': 'HTTP',
            'seleniumbase': 'SeleniumBase',
            'cloakbrowser': 'CloakBrowser',
        }
        return labels.get(browser_mode, browser_mode)

    @staticmethod
    def _access_label(supported: bool, uses_driver: bool) -> str:
        if not supported:
            return f'[{MUTED}]不支持[/]'
        if uses_driver:
            return f'[{WARN}]浏览器[/]'
        return f'[{SUCCESS}]HTTP[/]'

    @staticmethod
    def _verification_label(status: str, checked_at: str | None) -> str:
        labels = {
            'unchecked': f'[{MUTED}]未检查[/]',
            'healthy': f'[{SUCCESS}]正常[/]',
            'degraded': f'[{WARN}]受限[/]',
            'unavailable': f'[{ERROR}]不可用[/]',
        }
        label = labels.get(status, escape(status))
        if not checked_at or status == 'unchecked':
            return label
        return f'{label} [{MUTED}]{escape(checked_at[:10])}[/]'

    def source_selected(self, display_name: str, source_name: str) -> None:
        self.success(f'已切换到 {display_name} ({source_name})')

    def source_unchanged(self, display_name: str) -> None:
        self.info(f'当前动漫源已经是 {display_name}。')

    def source_not_found(self, selection: str, max_index: int) -> None:
        self.warn(
            f'未找到动漫源 "{selection}"。请输入 1 到 {max_index} 的序号，'
            '或使用 sources 查看代码名。'
        )

    def source_check_started(self, count: int) -> None:
        self.info(f'正在检查 {count} 个动漫源；本操作会显式访问各来源首页。')

    def source_check_summary(
        self,
        checks: list[SourceCheckView],
        *,
        persisted: bool = True,
    ) -> None:
        panel_width = min(self.console.width, MAX_SOURCE_PANEL_WIDTH)
        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_edge=False,
            pad_edge=False,
            header_style=f'bold {MUTED}',
        )
        table.add_column('#', width=3, justify='right', style=ACCENT, no_wrap=True)
        table.add_column('动漫源', min_width=8, overflow='ellipsis', no_wrap=True)
        table.add_column('状态', min_width=6, no_wrap=True)
        table.add_column('HTTP', width=5, justify='right', no_wrap=True)
        table.add_column('耗时', width=8, justify='right', no_wrap=True)
        table.add_column('检查时间', width=19, no_wrap=True)
        if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
            table.add_column('诊断摘要', min_width=18, overflow='ellipsis')

        for check in checks:
            row = [
                str(check.index),
                escape(check.display_name),
                self._verification_label(check.status, None),
                str(check.http_status) if check.http_status is not None else '-',
                (f'{check.latency_seconds:.3f}s' if check.latency_seconds is not None else '-'),
                escape(check.checked_at.replace('T', ' ')[:19]),
            ]
            if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
                detail = check.message or check.error_type or check.final_url or '-'
                row.append(escape(detail))
            table.add_row(*row)

        healthy = sum(check.status == 'healthy' for check in checks)
        degraded = sum(check.status == 'degraded' for check in checks)
        unavailable = sum(check.status == 'unavailable' for check in checks)
        persistence_message = (
            '结果已保存到 .comic_downloader/source-verifications.json'
            if persisted
            else '结果未能保存；请处理上方记录错误后重试'
        )
        self.print(
            Panel(
                Group(
                    table,
                    Text(''),
                    Text(
                        f'正常 {healthy} · 受限 {degraded} · 不可用 {unavailable} · '
                        + persistence_message,
                        style=MUTED,
                    ),
                ),
                border_style=ERROR if unavailable else WARN if degraded else SUCCESS,
                padding=(1, 2),
                title=f'来源检查 · {len(checks)} 个结果',
                title_align='left',
                width=panel_width,
            )
        )

    def source_verification_store_error(self, message: str) -> None:
        self.error(f'无法读取或写入来源验证记录: {message}')

    # ------------------------------------------------------------------
    # 可恢复下载任务
    # ------------------------------------------------------------------
    def retry_tasks(self, tasks: list[RetryTaskView]) -> None:
        panel_width = min(self.console.width, MAX_SOURCE_PANEL_WIDTH)
        if not tasks:
            self.print(
                Panel(
                    Group(
                        Text('没有待恢复的下载任务。', style=f'bold {SUCCESS}'),
                        Text('失败或中断的任务会自动记录在下载目录中。', style=MUTED),
                    ),
                    border_style=SUCCESS,
                    padding=(1, 2),
                    title='下载恢复',
                    title_align='left',
                    width=panel_width,
                )
            )
            return

        table = Table(
            box=None,
            expand=True,
            header_style=f'bold {ACCENT}',
            pad_edge=False,
            row_styles=['none', MUTED],
        )
        table.add_column('#', width=3, justify='right', style=ACCENT, no_wrap=True)
        table.add_column('动漫源', min_width=8, no_wrap=True)
        table.add_column('章节', min_width=12, overflow='ellipsis', no_wrap=True)
        table.add_column('状态', min_width=6, no_wrap=True)
        table.add_column('尝试', width=4, justify='right', no_wrap=True)
        if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
            table.add_column('任务 ID', width=12, style=MUTED, no_wrap=True)
            table.add_column('说明', min_width=12, overflow='ellipsis', style=MUTED)
        for task in tasks:
            row = [
                str(task.index),
                escape(task.source_name),
                escape(task.volume_name),
                self._retry_status_label(task.status),
                str(task.attempts),
            ]
            if self.console.width >= MIN_SOURCE_CODE_COLUMN_WIDTH:
                row.extend([escape(task.task_id), escape(task.message or '-')])
            table.add_row(*row)

        self.print(
            Panel(
                Group(
                    table,
                    Text(''),
                    Text('使用 retry <序号> 重试单个任务，或 retry all 重试全部。', style=MUTED),
                ),
                border_style=ACCENT,
                padding=(1, 2),
                title=f'下载恢复 · {len(tasks)} 个待处理',
                title_align='left',
                width=panel_width,
            )
        )

    @staticmethod
    def _retry_status_label(status: str) -> str:
        labels = {
            'in_progress': f'[{WARN}]已中断[/]',
            'partial': f'[{WARN}]部分失败[/]',
            'failed': f'[{ERROR}]失败[/]',
        }
        return labels.get(status, escape(status))

    def retry_selection_not_found(self, selection: str) -> None:
        self.warn(f'未找到下载任务 "{selection}"。输入 retry 查看待恢复任务。')

    def retry_store_error(self, message: str) -> None:
        self.error(f'无法读取下载任务记录: {message}')

    def session_status(
        self,
        path: str,
        source: str | None,
        comic: Comic | None,
        result_count: int,
        overwrite: bool,
    ) -> None:
        rows = [
            f'保存路径：{path}',
            f'当前源：{source or "未选择（查看详情时自动匹配）"}',
            f'当前漫画：{comic.name if comic else "未加载，请使用 i <序号/URL>"}',
            f'搜索结果：{result_count} 条；s 始终搜索所有启用源',
            f'文件策略：{"覆盖已有文件" if overwrite else "跳过已有压缩包，复用已下载图片"}',
        ]
        self.print(Panel(Text('\n'.join(rows)), title='当前状态', border_style=ACCENT))

    def task_overview(self, jobs: Sequence[JobSummary], *, unreadable: int = 0) -> None:
        counts = dict.fromkeys(JOB_STATE_STYLES, 0)
        for job in jobs:
            counts[job.state] += 1
        state = Text(f'全部计划 {len(jobs)}', style=f'bold {ACCENT}')
        for key, count in counts.items():
            if count:
                state.append(f'  ·  {JOB_STATE_LABELS[key]} {count}', style=JOB_STATE_STYLES[key])
        if unreadable:
            state.append(f'\n无法读取 {unreadable} 条记录（未计入统计）', style=WARN)
        state.append('\n当前保存路径 · 不含归档 · 记录状态不代表进程正在运行', style=MUTED)
        self.print(Panel(state, title='任务概览', title_align='left', border_style=MUTED))

    def task_position(self, query: TaskQuery, count: int, total: int, size: int) -> None:
        pages = max(1, (count + size - 1) // size)
        noun = '章节' if query.job_id else '任务'
        state = Text(f'{noun}筛选  {TASK_FILTER_LABELS[query.status]}', style=f'bold {ACCENT}')
        if query.keyword:
            state.append(f'\n查找  {query.keyword}')
        state.append(f'\n匹配 {count} / {total} 项  ·  第 {query.page}/{pages} 页', style=MUTED)
        self.print(Panel(state, border_style=MUTED, padding=(0, 1)))

    def task_navigation(
        self, query: TaskQuery, count: int, size: int, *, interactive: bool = True
    ) -> None:
        pages = max(1, (count + size - 1) // size)
        command = (
            f'tasks {query.job_id} {query.status}' if query.job_id else f'tasks {query.status}'
        )
        actions = []
        suffix = f' find {query.keyword}' if query.keyword else ''
        if query.page > 1:
            previous = 'tasks prev' if interactive else f'{command} {query.page - 1}{suffix}'
            actions.append(f'{previous} 上一页')
        if query.page < pages:
            following = 'tasks next' if interactive else f'{command} {query.page + 1}{suffix}'
            actions.append(f'{following} 下一页')
        if actions:
            self.info('  ·  '.join(actions))
        if query.job_id:
            self.info(f'tasks {query.job_id} failed 只看失败章节；tasks 返回全部任务。')
        else:
            self.info('tasks unfinished 只看未完成；tasks failed 只看有失败；tasks 返回全部任务。')
            self.info('tasks find <关键词> 查找漫画名、源代码或 ID；查找不改变 retry all 的范围。')

    def download_jobs(
        self,
        jobs: Sequence[DownloadJob | JobSummary],
        *,
        prefixes: dict[str, str] | None = None,
        archived: bool = False,
    ) -> None:
        if not jobs:
            self.info(
                '暂无归档。使用 archive <任务ID> 归档已完成计划；tasks 查看当前任务。'
                if archived
                else '当前列表没有任务。输入 tasks 返回全部任务；执行 d 或 v 创建任务。'
            )
            return
        table = Table(
            title='已归档计划' if archived else '下载任务',
            header_style=f'bold {ACCENT}',
            border_style=MUTED,
            box=box.SIMPLE_HEAD,
        )
        table.add_column('任务 ID', overflow='fold', min_width=12)
        table.add_column('漫画', overflow='fold')
        compact = self.console.width < COMPACT_TASK_WIDTH
        wide = self.console.width >= WIDE_TASK_WIDTH
        if wide:
            table.add_column('源', overflow='fold')
        if compact:
            table.add_column('进度', overflow='fold')
        else:
            table.add_column('完成', justify='right')
            table.add_column('状态')
        if wide:
            table.add_column('更新（UTC）', style=MUTED, no_wrap=True)
        for job in jobs:
            summary = JobSummary.from_job(job) if isinstance(job, DownloadJob) else job
            count = f'{summary.total - summary.remaining}/{summary.total}'
            label = prefixes.get(job.id, job.id) if prefixes is not None else job.id[:12]
            name = Text(job.comic_name)
            if not wide:
                name.append(f'\n{job.source_name}', style=MUTED)
            cells = [Text(label, style=ACCENT), name]
            if wide:
                cells.append(Text(job.source_name, style=MUTED))
            status_style = JOB_STATE_STYLES[job.state]
            if compact:
                cells.append(Text(f'{JOB_STATE_LABELS[job.state]}\n{count}', style=status_style))
            else:
                cells.extend([Text(count), Text(JOB_STATE_LABELS[job.state], style=status_style)])
            if wide:
                cells.append(Text(job.updated_at[:16].replace('T', ' ')))
            table.add_row(*cells)
        self.print(table)
        if archived:
            self.info('archive show <任务ID> 查看章节；archive restore <任务ID> 恢复到任务列表。')
            return
        self.info('tasks <任务ID> 查看章节与错误；retry <任务ID> 继续未完成章节。')
        self.info('记录属于当前保存路径。未结束的任务可尝试 retry，正在运行的任务会提示占用。')
        self.info('archive <任务ID> 归档已完成计划；archive 查看归档。')

    def archive_position(
        self, query: ArchiveQuery, count: int, total: int, size: int, *, unreadable: int = 0
    ) -> None:
        pages = max(1, (count + size - 1) // size)
        state = Text('归档查找', style=f'bold {ACCENT}')
        state.append(f'\n条件  {query.keyword or "全部归档"}')
        state.append(f'\n匹配 {count} / {total} 项  ·  第 {query.page}/{pages} 页', style=MUTED)
        if unreadable:
            state.append(f'\n无法读取 {unreadable} 条记录（未计入统计）', style=WARN)
        state.append('\n当前保存路径 · 仅含归档计划', style=MUTED)
        self.print(Panel(state, border_style=MUTED, padding=(0, 1)))

    def archive_navigation(
        self, query: ArchiveQuery, count: int, size: int, *, interactive: bool = True
    ) -> None:
        pages = max(1, (count + size - 1) // size)
        if query.job_id:
            self.info(f'归档章节 · 共 {count} 项 · 第 {query.page}/{pages} 页')
        command = f'archive show {query.job_id}' if query.job_id else 'archive list'
        suffix = f' find {query.keyword}' if query.keyword else ''
        actions = []
        if query.page > 1:
            previous = 'archive prev' if interactive else f'{command} {query.page - 1}{suffix}'
            actions.append(f'{previous} 上一页')
        if query.page < pages:
            following = 'archive next' if interactive else f'{command} {query.page + 1}{suffix}'
            actions.append(f'{following} 下一页')
        if actions:
            self.info('  ·  '.join(actions))
        if not query.job_id:
            self.info('archive find <关键词> 查找漫画名、源代码或 ID；archive 返回全部归档首页。')
            self.info('查找只影响浏览；归档和恢复始终使用单个任务 ID。')

    def download_job(
        self, job: DownloadJob, *, volume_indices: list[int] | None = None, archived: bool = False
    ) -> None:
        remaining = sum(not volume.complete for volume in job.volumes)
        self.print(
            Panel(
                Text(
                    f'任务：{job.id}\n漫画：{job.comic_name}\n源：{job.source_name}\n'
                    f'URL：{job.comic_url or "未记录"}\n状态：{JOB_STATE_LABELS[job.state]}\n'
                    f'已完成：{len(job.volumes) - remaining}/{len(job.volumes)}\n'
                    f'更新时间（UTC）：{job.updated_at}'
                ),
                title='归档计划详情' if archived else '任务详情',
                border_style=ACCENT,
            )
        )
        if job.error:
            self.warn(job.error)
        indices = range(len(job.volumes)) if volume_indices is None else volume_indices
        table = Table(header_style=f'bold {ACCENT}', border_style=MUTED, box=box.SIMPLE_HEAD)
        table.add_column('序号', justify='right', style=ACCENT)
        compact = self.console.width < COMPACT_TASK_WIDTH
        for title in ('卷/话', '状态 / 说明') if compact else ('分组', '卷/话', '状态', '说明'):
            table.add_column(title, overflow='fold')
        for index in indices:
            volume = job.volumes[index]
            result = volume.result
            status = '待下载' if result is None else VOLUME_STATE_LABELS[result.status]
            note = '' if result is None else (result.message or '')
            if result and result.failed_images:
                note = note or result.failed_images[0].error
            if compact:
                table.add_row(
                    Text(str(index + 1)),
                    Text(f'{volume.book_name}\n{volume.name}'),
                    Text(f'{status}\n{note}' if note else status),
                )
            else:
                table.add_row(
                    Text(str(index + 1)),
                    Text(volume.book_name),
                    Text(volume.name),
                    status,
                    Text(note),
                )
        if indices:
            self.print(table)
        else:
            self.info(
                f'没有符合当前筛选的章节。tasks {job.id} all 查看全部章节，或 tasks 返回任务列表。'
            )
        if archived:
            self.info(f'archive restore {job.id} 恢复到任务列表；archive 返回归档列表。')
        elif remaining:
            self.info(f'retry {job.id} 继续 {remaining} 话；筛选不改变重试范围。')

    # ------------------------------------------------------------------
    # 搜索结果
    # ------------------------------------------------------------------
    def search_position(self, filter_text: str, count: int, total: int, page: int) -> None:
        pages = max(1, (count + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE)
        state = Text('本地筛选  ' if filter_text else '搜索缓存  ', style=f'bold {ACCENT}')
        state.append(filter_text or '全部结果', style='bold')
        state.append(f'\n匹配 {count} / {total} 条  ·  第 {page}/{pages} 页', style=MUTED)
        self.print(Panel(state, border_style=MUTED, padding=(0, 1)))

    @staticmethod
    def search_progress(outcome: SearchOutcome, completed: int, total: int) -> Text:
        return Text(
            f'搜索 {completed}/{total} · {outcome.source_name} '
            f'{SEARCH_STATE_LABELS[outcome.state]} · {len(outcome.results)} 条 · {outcome.duration:.1f}s'
        )

    def search_report(self, outcomes: list[SearchOutcome]) -> None:
        table = Table(title='本次搜索源状态', header_style=f'bold {ACCENT}', border_style=MUTED)
        compact = self.console.width < COMPACT_SEARCH_WIDTH
        titles = (
            ('源', '状态', '结果', '耗时') if compact else ('源', '状态', '结果', '耗时', '说明')
        )
        for title in titles:
            table.add_column(title, overflow='fold')
        for outcome in outcomes:
            note = outcome.error_message or ''
            cells = [
                Text(outcome.source_name),
                Text(SEARCH_STATE_LABELS[outcome.state], style=SUCCESS if outcome.ok else WARN),
                Text(str(len(outcome.results))),
                Text(f'{outcome.duration:.1f}s'),
            ]
            if not compact:
                cells.append(Text(note))
            table.add_row(*cells)
        self.print(table)
        if compact:
            for outcome in outcomes:
                if outcome.error_message:
                    self.warn(f'{outcome.source_name}: {outcome.error_message}')
        if any(outcome.state == 'empty' for outcome in outcomes):
            self.info('未检出：本次没有找到条目；若预期有结果，可重试或改用漫画 URL。')

    def search_results(  # noqa: PLR0913 - presentation data plus optional pagination
        self,
        keyword: str,
        comics: list[Comic],
        source_display_names: dict[str | None, str],
        duration: float,
        *,
        page: int = 1,
        page_size: int | None = SEARCH_PAGE_SIZE,
        source_stats: list[SourceStat] | None = None,
        result_indices: list[int] | None = None,
        filter_text: str = '',
    ) -> None:
        indices = range(len(comics)) if result_indices is None else result_indices
        count = len(indices)
        if filter_text:
            self.search_position(filter_text, count, len(comics), page)
        if not count and filter_text:
            self.warn('没有匹配的缓存结果。输入 f 清除筛选，或 f <其他关键词> 重新筛选。')
            return
        if not comics:
            self.warn(f'未找到与 "{keyword}" 相关的结果。')
            self._print_source_stats(source_stats)
            return

        self.print(Rule(Text(f'搜索结果 · {keyword}', style='bold'), style=ACCENT))
        table = Table(
            show_header=True,
            header_style=f'bold {ACCENT}',
            border_style=MUTED,
            box=box.SIMPLE_HEAD,
            pad_edge=False,
            padding=(0, 1),
        )
        table.add_column('序号', justify='right', no_wrap=True, style=ACCENT)
        table.add_column('动漫源')
        compact = self.console.width < COMPACT_SEARCH_WIDTH
        if not compact:
            table.add_column('作者')
        table.add_column('名称', overflow='fold')
        if not compact:
            table.add_column('URL', overflow='fold', style=MUTED)

        size = page_size or count
        start = (page - 1) * size
        for index in indices[start : start + size]:
            comic = comics[index]
            cells = [
                Text(str(index + 1)),
                Text(source_display_names.get(comic.source, comic.source or 'N/A')),
            ]
            if not compact:
                cells.append(Text(comic.author or '[未提供]'))
            cells.append(Text(comic.name or '[未提供]'))
            if not compact:
                cells.append(Text(comic.url or 'N/A'))
            table.add_row(*cells)

        footer = f'共 [{ACCENT}]{len(comics)}[/] 条结果，用时 [{ACCENT}]{duration:.1f}s[/]'
        self.print(Group(table, Text(''), footer))
        if page_size is not None:
            self._search_navigation(page, size, count)
        if compact:
            self.info('窄屏模式：使用 i <序号> 查看作者和完整 URL。')
        self.info('下一步：i <序号> 查看分组；d <序号> 全量下载。')
        self._print_source_stats(source_stats)

    def _search_navigation(self, page: int, size: int, count: int) -> None:
        pages = max(1, (count + size - 1) // size)
        start = (page - 1) * size
        navigation = []
        if page > 1:
            navigation.append('p prev 上一页')
        if page < pages:
            navigation.append('p next 下一页')
        self.print(
            Text(
                f'第 {page}/{pages} 页  ·  显示 {start + 1}～{min(start + size, count)} / {count} 条',
                style=ACCENT,
            )
        )
        if navigation:
            self.info('  ·  '.join(navigation))
        self.info('f <关键词> 筛选名称 / 作者 / 源；f 清除。i / d 使用表中原序号。')

    def _print_source_stats(self, source_stats: list[SourceStat] | None) -> None:
        """在结果下方渲染一行紧凑的各源执行状态，帮助用户一眼看出哪个源失败了。"""
        if not source_stats:
            return
        parts: list[str] = []
        for stat in source_stats:
            if stat.ok:
                parts.append(f'[{SUCCESS}]成功[/] {stat.display_name} ({stat.duration:.1f}s)')
            else:
                detail = stat.error or '失败'
                if len(detail) > MAX_URL_DISPLAY_WIDTH:
                    detail = detail[: MAX_URL_DISPLAY_WIDTH - 1] + '…'
                parts.append(f'[{ERROR}]失败[/] {stat.display_name} ({detail})')
        self.print(f'[{MUTED}]源状态: {"  ".join(parts)}[/]')

    # ------------------------------------------------------------------
    # 动漫详情
    # ------------------------------------------------------------------
    def comic_parse_notes(self, comic: Comic, *, downloading: bool = False) -> None:
        if not comic.parse_warnings:
            return
        notes = comic.parse_warnings[:MAX_FAILURE_DETAIL_ROWS]
        body = Text('\n'.join(notes))
        if len(comic.parse_warnings) > MAX_FAILURE_DETAIL_ROWS:
            body.append(
                f'\n另有 {len(comic.parse_warnings) - MAX_FAILURE_DETAIL_ROWS} 项提示，详见日志。'
            )
        body.append('\n已保留可用章节；若数量不符，请重新获取详情或更换源。', style=MUTED)
        if downloading:
            body.append(
                '\n本次任务仅包含已解析的所选章节；任务完成不代表网站全书已完整获取。', style=WARN
            )
        self.print(Panel(body, title='章节解析提示', border_style=WARN, padding=(0, 1)))

    def comic_info(self, comic: Comic, *, paginate: bool = True) -> None:
        self.print(Rule(style=ACCENT))
        header_parts = [Text(comic.name or '未知漫画', style=f'bold {ACCENT}')]
        if comic.author:
            header_parts.append(Text(f'  作者: {comic.author}', style=MUTED))
        if comic.source:
            header_parts.append(Text(f'  源: {comic.source}', style=MUTED))
        if comic.url:
            header_parts.append(Text(f'  URL: {comic.url}', style=MUTED))

        body_lines: list[Any] = [Group(*header_parts)]
        if comic.metadata:
            body_lines.append(Text(''))
            body_lines.extend(Text(f'{meta["k"]}: {meta["v"]}') for meta in comic.metadata)

        self.print(Panel(Group(*body_lines), border_style=ACCENT, padding=(0, 1)))
        self.comic_parse_notes(comic)

        for book_index, book in enumerate(comic.books):
            if paginate:
                self.chapter_page(book_index, book)
            else:
                self.print(self.chapter_table(book_index, book))
        if not any(book.vols for book in comic.books):
            self.warn('未找到可下载章节，可稍后重试详情或更换源。')
        else:
            self.info('下一步：v <分组> [截止] 或 v <分组> <起始> <截止>；d 下载全部。')

    def chapter_page(self, book_index: int, book, page: int = 1) -> None:
        pages = max(1, (len(book.vols) + CHAPTER_PAGE_SIZE - 1) // CHAPTER_PAGE_SIZE)
        self.print(
            self.chapter_table(
                book_index,
                book,
                start=(page - 1) * CHAPTER_PAGE_SIZE,
                limit=CHAPTER_PAGE_SIZE,
            )
        )
        if pages > 1:
            self.info(
                f'分组 {book_index + 1} · 第 {page}/{pages} 页；'
                f'ch {book_index + 1} <页码/next/prev> 翻页，v 使用原话序号。'
            )

    def chapter_table(
        self, book_index: int, book, *, start: int = 0, limit: int | None = None
    ) -> Table:
        table = Table(
            title=Text(f'分组 {book_index + 1}: {book.name or "默认章节"}（{len(book.vols)} 话）'),
            show_header=False,
            box=None,
            expand=True,
            padding=(0, 1),
            title_style='bold',
        )

        columns = max(1, min(3, self.console.width // 32))
        for _ in range(columns):
            table.add_column('Index', justify='right', style=ACCENT)
            table.add_column('Name', overflow='fold')

        row_buffer = []
        stop = None if limit is None else start + limit
        for index, vol in enumerate(book.vols[start:stop], start=start):
            row_buffer.extend([Text(str(index + 1)), Text(vol.name)])
            if len(row_buffer) == columns * 2:
                table.add_row(*row_buffer)
                row_buffer = []

        if row_buffer:
            while len(row_buffer) < columns * 2:
                row_buffer.extend([Text(''), Text('')])
            table.add_row(*row_buffer)

        return table

    # ------------------------------------------------------------------
    # 下载汇总
    # ------------------------------------------------------------------
    def download_summary(self, summary: DownloadSummary) -> None:
        total = summary.total_volumes
        if total == 0:
            self.warn('本次没有下载任何章节。')
            return

        overview = self._format_download_overview(summary)
        has_problems = summary.failed > 0 or summary.partial > 0

        if not has_problems:
            self.print(Rule(style=SUCCESS))
            self.print(overview)
            return

        self.print(Rule('下载汇总', style=WARN))
        self.print(overview)

        detail = Table(
            show_header=True,
            header_style=f'bold {ACCENT}',
            border_style=MUTED,
            pad_edge=False,
        )
        detail.add_column('卷/话', overflow='fold')
        detail.add_column('状态', justify='center')
        detail.add_column('图片', justify='right')
        detail.add_column('说明', overflow='fold', style=MUTED)

        status_badges = {
            'downloaded': f'[{SUCCESS}]已下载[/]',
            'skipped': f'[{MUTED}]已跳过[/]',
            'partial': f'[{WARN}]部分失败[/]',
            'failed': f'[{ERROR}]失败[/]',
        }

        shown_failures = 0
        for result in summary.volume_results:
            status = result.status
            badge = status_badges.get(status, status)

            if result.image_count:
                imgs = f'{result.downloaded_count}/{result.image_count}'
            else:
                imgs = '-'

            note = self._volume_note(result)
            detail.add_row(Text(result.name), badge, imgs, Text(note))

            if result.failed_images and shown_failures < MAX_FAILURE_DETAIL_ROWS:
                for img in result.failed_images[: MAX_FAILURE_DETAIL_ROWS - shown_failures]:
                    detail.add_row('', '', '', Text(f'第 {img.index} 张: {img.error}', style=MUTED))
                    shown_failures += 1

        self.print(detail)
        self.info('使用 tasks 查看任务，retry <任务ID> 继续未完成章节；默认复用已下载图片。')

    @staticmethod
    def _volume_note(result: VolumeDownloadResult) -> str:
        if result.status == 'skipped' and result.archive_path:
            return f'已存在: {result.archive_path}'
        if result.status == 'downloaded' and result.archive_path:
            return result.archive_path
        return result.message or ''

    @staticmethod
    def _format_download_overview(summary: DownloadSummary) -> str:
        return (
            f'下载完成：[{SUCCESS}]成功 {summary.downloaded}[/]  '
            f'[{MUTED}]跳过 {summary.skipped}[/]  '
            f'[{WARN}]失败 {summary.failed}[/]  '
            f'[{WARN}]部分 {summary.partial}[/]'
        )


# 向后兼容：保持旧的 status badge 字典可见（如外部引用）。
STATUS_BADGES = {
    'downloaded': f'[{SUCCESS}]成功[/]',
    'skipped': f'[{MUTED}]跳过[/]',
    'partial': f'[{WARN}]部分[/]',
    'failed': f'[{ERROR}]失败[/]',
}

JOB_STATE_LABELS = {
    'pending': '待下载',
    'running': '未结束',
    'interrupted': '已中断',
    'failed': '有失败',
    'completed': '已完成',
}
VOLUME_STATE_LABELS = {
    'downloaded': '已下载',
    'skipped': '已跳过',
    'partial': '部分失败',
    'failed': '失败',
}
