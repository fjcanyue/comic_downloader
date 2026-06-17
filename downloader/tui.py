from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from downloader.models import Comic


class TerminalPresenter:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def print(self, message: Any = '', style: str | None = None) -> None:
        self.console.print(message, style=style)

    def status(self, message: str, spinner: str = 'dots'):
        return self.console.status(message, spinner=spinner)

    def prompt(self, source_name: str | None = None) -> str:
        if source_name:
            return f'动漫下载器[{source_name}]> '
        return '动漫下载器> '

    def output_path(self, path: str) -> None:
        self.print(f'动漫文件本机存储路径为: {path}')

    def source_options(self, source_names: list[str]) -> None:
        self.print('请选择动漫下载网站源:')
        for index, source_name in enumerate(source_names):
            self.print(f'{index + 1}. {source_name}')

    def source_switching(self, source_name: str) -> None:
        self.print(f'正在切换到{source_name}动漫下载网站源...')

    def search_results(
        self,
        keyword: str,
        comics: list[Comic],
        source_display_names: dict[str | None, str],
        duration: float,
    ) -> None:
        if not comics:
            self.print(f'未找到与 "{keyword}" 相关的结果。', style='bold yellow')
            return

        table = Table(title=f'搜索结果 ({len(comics)} 条，用时 {duration:.1f}s)')
        table.add_column('序号', justify='right', no_wrap=True)
        table.add_column('动漫源')
        table.add_column('作者')
        table.add_column('名称')
        table.add_column('URL', style='#75D7EC')

        for index, comic in enumerate(comics):
            table.add_row(
                str(index + 1),
                source_display_names.get(comic.source, comic.source or 'N/A'),
                comic.author if comic.author else 'N/A',
                comic.name if comic.name else 'N/A',
                comic.url if comic.url else 'N/A',
            )

        self.print(table)

    def comic_info(self, comic: Comic) -> None:
        md_content = f'# {comic.name}\n\n'

        if comic.metadata:
            md_content += '## Metadata\n'
            for meta in comic.metadata:
                md_content += f'- **{meta["k"]}**: {meta["v"]}\n'

        self.print(Markdown(md_content))

        for book_index, book in enumerate(comic.books):
            self.print(self.chapter_table(book_index, book))

    def chapter_table(self, book_index: int, book) -> Table:
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

    def download_summary(self, summary) -> None:
        if summary.ok:
            self.print(
                f'下载完成：成功 {summary.downloaded}，跳过 {summary.skipped}',
                style='bold green',
            )
            return
        self.print(
            f'下载完成，但存在失败：成功 {summary.downloaded}，跳过 {summary.skipped}，'
            f'失败 {summary.failed}，部分失败 {summary.partial}',
            style='bold yellow',
        )
