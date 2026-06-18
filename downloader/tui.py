from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.markdown import Markdown
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
        self.print(f'[bold {SUCCESS}]✔ {message}')

    def warn(self, message: Any) -> None:
        self.print(f'[bold {WARN}]⚠ {message}')

    def error(self, message: Any) -> None:
        self.print(f'[bold {ERROR}]✖ {message}')

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
    # 欢迎与退出
    # ------------------------------------------------------------------
    def welcome(self, source_names: list[str] | None = None) -> None:
        title = Text(BRAND, style=f'bold {ACCENT}')
        commands = (
            '[bold]命令速查[/]\n'
            f'  [{ACCENT}]s[/]  <关键词>       从所有源搜索动漫\n'
            f'  [{ACCENT}]i[/]  <序号/URL>     查看动漫详情\n'
            f'  [{ACCENT}]d[/]  <序号/URL>     全量下载动漫\n'
            f'  [{ACCENT}]v[/]  <章节> [范围]  按范围下载章节\n'
            f'  [{ACCENT}]source[/]            手动切换下载源\n'
            f'  [{ACCENT}]q[/]                 退出'
        )
        body_lines = [commands]
        if source_names:
            joined = f'  · '.join(source_names)
            body_lines.append(f'\n[{MUTED}]支持源: {joined}')

        self.print(
            Panel(
                Group(title, Text(''), *body_lines),
                border_style=ACCENT,
                padding=(0, 2),
                title=f'欢迎使用 {BRAND}',
                title_align='left',
            )
        )

    def farewell(self) -> None:
        self.print()
        self.print(Rule(style=MUTED))
        self.print(f'感谢使用 {BRAND}，再会！', style=f'bold {ACCENT}')

    # ------------------------------------------------------------------
    # 源选择
    # ------------------------------------------------------------------
    def source_options(self, source_names: list[str]) -> None:
        lines = []
        for index, source_name in enumerate(source_names):
            lines.append(f'  [{ACCENT}]{index + 1:>2}.[/] {source_name}')
        self.print(
            Panel(
                Group('请选择动漫下载网站源:', Text(''), *lines),
                border_style=ACCENT,
                padding=(0, 1),
            )
        )

    def source_switching(self, source_name: str) -> None:
        self.print(f'[{ACCENT}]⟳[/] 正在切换到 [bold]{source_name}[/] 动漫下载源...')

    # ------------------------------------------------------------------
    # 搜索结果
    # ------------------------------------------------------------------
    def search_results(
        self,
        keyword: str,
        comics: list[Comic],
        source_display_names: dict[str | None, str],
        duration: float,
    ) -> None:
        if not comics:
            self.warn(f'未找到与 "{keyword}" 相关的结果。')
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
            for meta in comic.metadata:
                md_lines.append(f'- **{meta["k"]}**: {meta["v"]}')
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

        columns = 3
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
            'downloaded': f'[{SUCCESS}]✓ 已下载[/]',
            'skipped': f'[{MUTED}]⊘ 已跳过[/]',
            'partial': f'[{WARN}]△ 部分失败[/]',
            'failed': f'[{ERROR}]✗ 失败[/]',
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
                    detail.add_row(
                        '', '', '', f'[{MUTED}]第 {img.index} 张: {img.error}[/]'
                    )
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
    'downloaded': f'[{SUCCESS}]✓[/]',
    'skipped': f'[{MUTED}]⊘[/]',
    'partial': f'[{WARN}]△[/]',
    'failed': f'[{ERROR}]✗[/]',
}
