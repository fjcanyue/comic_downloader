"""Export the actual keyboard browser screen using synthetic data, without network access."""

from __future__ import annotations

import asyncio
import sys
from io import StringIO
from pathlib import Path

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.style import Style
from rich.text import Text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from downloader.models import Comic, ComicBook, ComicVolume
from downloader.search_browser.loader import PreviewWorker
from downloader.search_browser.state import BrowserState, Detail, SearchItem, detail_lines
from downloader.search_browser.view import WIDE_COLUMNS, SearchBrowser


class ScreenOutput(DummyOutput):
    def __init__(self, width: int):
        self.width = width

    def get_size(self):
        return Size(rows=30, columns=self.width)


async def render(width: int, *, confirmation: bool = False) -> None:
    items = tuple(
        SearchItem(i, 'demo', f'https://example.test/comic/{i}', name, '演示作者')
        for i, name in enumerate(['星海旅人', '星海旅人 · 特别篇', '星海纪事', '银河漫游'])
    )
    state = BrowserState(items, '星海 · 演示数据', 1, source_names={'demo': '演示漫画源'})
    comic = Comic()
    comic.name = items[0].name
    comic.author = '演示作者'
    comic.metadata = [
        {'k': '简介', 'v': '少年在星际旅行中寻找失落的故乡，与伙伴一起探索未知世界。'}
    ]
    book = ComicBook()
    book.name = '正篇'
    book.vols = [
        ComicVolume(f'第 {i + 1} 话 · 新的旅程', f'https://example.test/v/{i}') for i in range(50)
    ]
    comic.books = [book]
    state.remember(items[0], Detail(detail_lines(items[0], comic), comic))
    worker = PreviewWorker(lambda item, stop: comic)
    with create_pipe_input() as pipe:
        browser = SearchBrowser(
            state, worker, 'D:/Comics', False, input=pipe, output=ScreenOutput(width)
        )
        task = asyncio.create_task(browser.app.run_async(pre_run=browser.start))
        try:
            await asyncio.sleep(0.15)
            if confirmation:
                pipe.send_text('d')
                await asyncio.sleep(0.15)
            screen = browser.app.renderer.last_rendered_screen
            if screen is None:
                raise RuntimeError('No rendered browser screen')
            text = Text()
            for y in range(30):
                for x in range(width):
                    cell = screen.data_buffer[y][x]
                    if cell.char == '':
                        continue
                    attrs = browser.app._merged_style.get_attrs_for_style_str(cell.style)
                    text.append(
                        cell.char,
                        Style(
                            color=f'#{attrs.color}' if attrs.color else None,
                            bgcolor=f'#{attrs.bgcolor}' if attrs.bgcolor else None,
                            bold=attrs.bold,
                            italic=attrs.italic,
                            reverse=attrs.reverse,
                        ),
                    )
                text.append('\n')
            console = Console(
                file=StringIO(),
                width=width,
                record=True,
                force_terminal=True,
                color_system='truecolor',
                _environ={},
            )
            console.print(text, end='', soft_wrap=True)
            suffix = 'confirm' if confirmation else ('wide' if width >= WIDE_COLUMNS else 'narrow')
            svg = console.export_svg(title='漫画下载器 · 键盘浏览 · 演示数据')
            Path(__file__).with_name(f'search-browser-{suffix}.svg').write_text(
                '\n'.join(line.rstrip() for line in svg.splitlines()) + '\n', encoding='utf-8'
            )
        finally:
            browser._finish()
            await task
            browser.close()


async def main() -> None:
    await render(120)
    await render(80)
    await render(80, confirmation=True)


if __name__ == '__main__':
    asyncio.run(main())
