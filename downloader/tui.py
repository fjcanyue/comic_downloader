from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from downloader.download.jobs import DownloadJob
from downloader.models import Comic, DownloadSummary, SearchOutcome, VolumeDownloadResult
from downloader.sources.profiles import SourceBinding

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
SEARCH_PAGE_SIZE = 20
CHAPTER_PAGE_SIZE = 60
SEARCH_STATE_LABELS = {
    'success': '有结果',
    'empty': '未检出',
    'failed': '失败',
    'partial': '部分结果',
    'skipped': '跳过',
}


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
        self.print(Text(f'✔ {message}', style=f'bold {SUCCESS}'))

    def warn(self, message: Any) -> None:
        self.print(Text(f'⚠ {message}', style=f'bold {WARN}'))

    def error(self, message: Any) -> None:
        self.print(Text(f'✖ {message}', style=f'bold {ERROR}'))

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
    # 欢迎与退出
    # ------------------------------------------------------------------
    def welcome(self, source_names: list[str] | None = None) -> None:
        title = Text(BRAND, style=f'bold {ACCENT}')
        commands = (
            '[bold]命令速查[/]\n'
            f'  [{ACCENT}]s[/]  <关键词>       从所有源搜索动漫\n'
            f'  [{ACCENT}]i[/]  <序号/URL>     查看动漫详情\n'
            f'  [{ACCENT}]p[/]  [页码]         翻看搜索结果，序号保持不变\n'
            f'  [{ACCENT}]ch[/] <分组> [页码]  翻看章节，例如 ch 1 2\n'
            f'  [{ACCENT}]d[/]  [序号/URL]     全量下载；不填则下载当前漫画\n'
            f'  [{ACCENT}]v[/]  <分组> [范围]  如 v 1 5 10，下载第 5～10 话\n'
            f'  [{ACCENT}]source[/] [源名/序号] 切换下载源；搜索仍使用所有启用源\n'
            f'  [{ACCENT}]status[/]            查看当前漫画、路径和覆盖模式\n'
            f'  [{ACCENT}]tasks[/] [任务ID]     查看保存的下载任务和失败详情\n'
            f'  [{ACCENT}]retry[/] <任务ID>     继续未完成章节（支持重启后恢复）\n'
            f'  [{ACCENT}]help[/] [命令]       查看用法，例如 help v\n'
            f'  [{ACCENT}]q[/]                 退出'
        )
        body_lines = [commands]
        if source_names:
            joined = '  · '.join(source_names)
            body_lines.append(f'\n[{MUTED}]支持源: {joined}')
        body_lines.append('\n流程：s 关键词 → i 1 → v 1 5 10 或 d。所有序号从 1 开始。')

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
    def source_options(
        self,
        source_names: list[str],
        bindings: dict[str, SourceBinding] | None = None,
        current_source: str | None = None,
    ) -> None:
        lines = []
        for index, source_name in enumerate(source_names):
            detail = ''
            if bindings and source_name in bindings:
                binding = bindings[source_name]
                driver = '需要浏览器' if binding.profile.uses_driver_for_download() else 'HTTP 下载'
                detail = f' · {getattr(binding.source_class, "name", source_name)} · {driver}'
                if getattr(binding.source_class, 'search_unavailable_reason', None):
                    detail += ' · 仅支持 URL'
            selected = ' ← 当前' if source_name == current_source else ''
            lines.append(Text(f'  {index + 1:>2}. {source_name}{detail}{selected}'))
        self.print(
            Panel(
                Group('请选择动漫下载网站源（回车 / q 取消）:', Text(''), *lines),
                border_style=ACCENT,
                padding=(0, 1),
            )
        )

    def source_switching(self, source_name: str) -> None:
        self.print(f'[{ACCENT}]⟳[/] 正在切换到 [bold]{source_name}[/] 动漫下载源...')

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

    def download_jobs(self, jobs: list[DownloadJob]) -> None:
        if not jobs:
            self.info('当前保存路径没有下载任务。执行 d 或 v 后会自动保存任务。')
            return
        table = Table(title='下载任务', header_style=f'bold {ACCENT}', border_style=MUTED)
        table.add_column('任务 ID', no_wrap=True, min_width=12)
        table.add_column('漫画', overflow='fold')
        compact = self.console.width < COMPACT_TASK_WIDTH
        if compact:
            table.add_column('进度', overflow='fold')
        else:
            table.add_column('完成', justify='right')
            table.add_column('状态')
        for job in jobs:
            count = f'{len(job.volumes) - len(job.remaining)}/{len(job.volumes)}'
            cells = [Text(job.id[:12]), Text(job.comic_name)]
            if compact:
                cells.append(Text(f'{JOB_STATE_LABELS[job.state]}\n{count}'))
            else:
                cells.extend([Text(count), Text(JOB_STATE_LABELS[job.state])])
            table.add_row(*cells)
        self.print(table)
        self.info('tasks <任务ID> 查看章节与错误；retry <任务ID> 继续未完成章节。')
        self.info('记录属于当前保存路径。未结束的任务可尝试 retry，正在运行的任务会提示占用。')

    def download_job(self, job: DownloadJob) -> None:
        self.print(
            Panel(
                Text(
                    f'任务：{job.id}\n漫画：{job.comic_name}\n源：{job.source_name}\n'
                    f'URL：{job.comic_url or "未记录"}\n状态：{JOB_STATE_LABELS[job.state]}\n'
                    f'已完成：{len(job.volumes) - len(job.remaining)}/{len(job.volumes)}\n'
                    f'更新时间（UTC）：{job.updated_at}'
                ),
                title='任务详情',
                border_style=ACCENT,
            )
        )
        if job.error:
            self.warn(job.error)
        table = Table(header_style=f'bold {ACCENT}', border_style=MUTED)
        for title in ('分组', '卷/话', '状态', '说明'):
            table.add_column(title, overflow='fold')
        for volume in job.volumes:
            result = volume.result
            status = '待下载' if result is None else VOLUME_STATE_LABELS[result.status]
            note = '' if result is None else (result.message or '')
            if result and result.failed_images:
                note = note or result.failed_images[0].error
            table.add_row(Text(volume.book_name), Text(volume.name), status, Text(note))
        self.print(table)
        if job.remaining:
            self.info(f'retry {job.id[:12]} 继续 {len(job.remaining)} 话；已成功的章节保持不变。')

    # ------------------------------------------------------------------
    # 搜索结果
    # ------------------------------------------------------------------
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
    ) -> None:
        if not comics:
            self.warn(f'未找到与 "{keyword}" 相关的结果。')
            return

        self.print(Rule(Text(f'搜索结果 · {keyword}', style='bold'), style=ACCENT))
        table = Table(
            show_header=True,
            header_style=f'bold {ACCENT}',
            border_style=MUTED,
            pad_edge=False,
        )
        table.add_column('序号', justify='right', no_wrap=True, style=ACCENT)
        table.add_column('动漫源')
        compact = self.console.width < COMPACT_SEARCH_WIDTH
        if not compact:
            table.add_column('作者')
        table.add_column('名称', overflow='fold')
        if not compact:
            table.add_column('URL', overflow='fold', style=MUTED)

        size = page_size or len(comics)
        start = (page - 1) * size
        for index, comic in enumerate(comics[start : start + size], start=start):
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
        pages = max(1, (len(comics) + size - 1) // size)
        if pages > 1:
            self.info(f'第 {page}/{pages} 页；p <页码> 翻页。i / d 使用表中原序号。')
        if compact:
            self.info('窄屏模式：使用 i <序号> 查看作者和完整 URL。')
        self.info('下一步：i <序号> 查看分组；d <序号> 全量下载。')

    # ------------------------------------------------------------------
    # 动漫详情
    # ------------------------------------------------------------------
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
                f'ch {book_index + 1} <页码> 翻页，v 使用原话序号。'
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
    'downloaded': f'[{SUCCESS}]✓[/]',
    'skipped': f'[{MUTED}]⊘[/]',
    'partial': f'[{WARN}]△[/]',
    'failed': f'[{ERROR}]✗[/]',
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
