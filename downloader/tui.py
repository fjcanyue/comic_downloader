from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from downloader.models import Comic, DownloadSummary, VolumeDownloadResult

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
        self.print(message)

    def success(self, message: Any) -> None:
        self.print(f'[bold {SUCCESS}]成功[/] {message}')

    def warn(self, message: Any) -> None:
        self.print(f'[bold {WARN}]注意[/] {message}')

    def error(self, message: Any) -> None:
        self.print(f'[bold {ERROR}]错误[/] {message}')

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
                f'本机存储路径  [{ACCENT}]{path}',
                border_style=MUTED,
                padding=(0, 1),
            )
        )

    # ------------------------------------------------------------------
    # 命令速查：welcome 与 help 复用同一份文本，避免两处不一致。
    # ------------------------------------------------------------------
    def _command_cheatsheet(self) -> Table:
        commands = Table.grid(padding=(0, 2))
        commands.add_column(style=f'bold {ACCENT}', no_wrap=True)
        commands.add_column(style=MUTED, no_wrap=True)
        commands.add_column()
        commands.add_row('s', '<关键词>', '从所有启用源搜索动漫')
        commands.add_row('i', '<序号/URL>', '查看动漫详情')
        commands.add_row('d', '[序号/URL]', '下载当前或指定动漫')
        commands.add_row('v', '<章节> [范围]', '按范围下载章节')
        commands.add_row('source', '[序号/代码名]', '查看并切换动漫源')
        commands.add_row('sources', '', '查看动漫源能力概览')
        commands.add_row('help / ?', '', '查看命令速查')
        commands.add_row('q', '', '退出')
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
        table.add_column('下载', min_width=6, no_wrap=True)

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
                    self._access_label(source.search_uses_driver),
                    self._access_label(source.download_uses_driver),
                ]
            )
            table.add_row(*row, style='bold' if source.selected else None)

        hint = (
            '输入序号、代码名或动漫源名称进行切换；直接回车刷新列表。'
            if selection_mode
            else '使用 source <序号/代码名> 直接切换动漫源。'
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
    def _access_label(uses_driver: bool) -> str:
        if uses_driver:
            return f'[{WARN}]浏览器[/]'
        return f'[{SUCCESS}]HTTP[/]'

    def source_selected(self, display_name: str, source_name: str) -> None:
        self.success(f'已切换到 [bold]{display_name}[/] [{MUTED}]({source_name})[/]')

    def source_unchanged(self, display_name: str) -> None:
        self.info(f'当前动漫源已经是 [bold {ACCENT}]{display_name}[/]。')

    def source_not_found(self, selection: str, max_index: int) -> None:
        self.warn(
            f'未找到动漫源 "{escape(selection)}"。请输入 1 到 {max_index} 的序号，'
            '或使用 sources 查看代码名。'
        )

    # ------------------------------------------------------------------
    # 搜索结果
    # ------------------------------------------------------------------
    def search_results(
        self,
        keyword: str,
        comics: list[Comic],
        source_display_names: dict[str | None, str],
        duration: float,
        *,
        source_stats: list[SourceStat] | None = None,
    ) -> None:
        if not comics:
            self.warn(f'未找到与 "{keyword}" 相关的结果。')
            self._print_source_stats(source_stats)
            return

        self.print(Rule(f'搜索结果 · [bold]{keyword}[/]', style=ACCENT))
        table = Table(
            show_header=True,
            header_style=f'bold {ACCENT}',
            border_style=MUTED,
            pad_edge=False,
        )
        table.add_column('序号', justify='right', no_wrap=True, style=ACCENT)
        table.add_column('动漫源')
        table.add_column('作者')
        table.add_column('名称')
        table.add_column('URL', overflow='fold', style=MUTED)

        for index, comic in enumerate(comics):
            table.add_row(
                str(index + 1),
                source_display_names.get(comic.source, comic.source or 'N/A'),
                comic.author or '[未提供]',
                comic.name or '[未提供]',
                comic.url or 'N/A',
            )

        footer = f'共 [{ACCENT}]{len(comics)}[/] 条结果，用时 [{ACCENT}]{duration:.1f}s[/]'
        self.print(Group(table, Text(''), footer))
        self._print_source_stats(source_stats)

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
    def comic_info(self, comic: Comic) -> None:
        self.print(Rule(style=ACCENT))
        header_parts = [Text(comic.name or '未知漫画', style=f'bold {ACCENT}')]
        if comic.author:
            header_parts.append(Text(f'  作者: {comic.author}', style=MUTED))
        if comic.source:
            header_parts.append(Text(f'  源: {comic.source}', style=MUTED))

        body_lines: list[Any] = [Group(*header_parts)]
        if comic.metadata:
            md_lines = ['## 详情', '']
            md_lines.extend(f'- **{meta["k"]}**: {meta["v"]}' for meta in comic.metadata)
            body_lines.append(Text(''))
            body_lines.append(Markdown('\n'.join(md_lines)))

        self.print(Panel(Group(*body_lines), border_style=ACCENT, padding=(0, 1)))

        for book_index, book in enumerate(comic.books):
            self.print(self.chapter_table(book_index, book))

    def chapter_table(self, book_index: int, book) -> Table:
        table = Table(
            title=f'[{ACCENT}]{book_index + 1}[/]: {book.name}',
            show_header=False,
            box=None,
            padding=(0, 2),
            title_style='bold',
        )

        # 自适应列数：每对「序号+名称」预估占约 32 字符宽度，按终端宽度动态分列，
        # 避免窄终端挤压换行、宽终端浪费空间。至少 1 列。
        columns = max(1, self.console.width // 32)
        for _ in range(columns):
            table.add_column('Index', justify='right', style=ACCENT)
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
            detail.add_row(result.name, badge, imgs, note)

            if result.failed_images and shown_failures < MAX_FAILURE_DETAIL_ROWS:
                for img in result.failed_images[: MAX_FAILURE_DETAIL_ROWS - shown_failures]:
                    detail.add_row('', '', '', f'[{MUTED}]第 {img.index} 张: {img.error}[/]')
                    shown_failures += 1

        self.print(detail)

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
