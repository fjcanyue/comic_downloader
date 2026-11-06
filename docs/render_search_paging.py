"""Render search-page status examples with synthetic data and no network access."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from downloader.models import Comic, SearchOutcome
from downloader.tui import SearchPageView, TerminalPresenter


def render(width: int) -> None:
    console = Console(
        file=StringIO(),
        width=width,
        record=True,
        force_terminal=True,
        color_system='truecolor',
        _environ={},
    )
    presenter = TerminalPresenter(console)
    comics = []
    for index in range(9, 19):
        comic = Comic()
        comic.name = f'星海旅人 · 演示条目 {index}'
        comic.source = 'manhuagui'
        comic.url = f'https://example.test/comic/{index}'
        comics.append(comic)
    console.rule('加载网站下一页 · 演示数据')
    presenter.search_report([SearchOutcome('manhuagui', comics, None, 1.2)])
    presenter.info('本页返回 10 条，新增 9 条；原序号保持不变。')
    presenter.search_pages([SearchPageView('manhuagui', 2, 19, True)])
    console.rule('失败后保留重试位置 · 演示数据')
    presenter.search_report([SearchOutcome('manhuagui', [], '网络超时', 15)])
    presenter.warn('本页未完整加载，已保留可用结果；more manhuagui 重试同一页。')
    presenter.search_pages([SearchPageView('manhuagui', 2, 19, True)])
    svg = console.export_svg(title='网站搜索分页 · 演示数据', clear=False)
    # Rich's exported textLength counts characters, while CJK occupies two terminal cells.
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    root = ET.fromstring(svg)  # noqa: S314 - locally generated Rich SVG
    for node in root.iter('{http://www.w3.org/2000/svg}text'):
        if 'textLength' in node.attrib and node.text:
            length = float(node.attrib['textLength']) * cell_len(node.text) / len(node.text)
            node.attrib['textLength'] = f'{length:g}'
    svg = ET.tostring(root, encoding='unicode')
    Path(__file__).with_name(f'search-paging-{width}.svg').write_text(
        '\n'.join(line.rstrip() for line in svg.splitlines()) + '\n', encoding='utf-8'
    )
    print(console.export_text(clear=False))


if __name__ == '__main__':
    for width in (48, 100):
        render(width)
