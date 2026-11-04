"""Render synthetic archive UX examples: python docs/render_archive_find.py."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console

# Allow running this documentation helper directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from downloader.download.archive_batch import ArchiveBatch, ArchiveEntry
from downloader.download.job_archive import ArchiveQuery
from downloader.download.job_browser import JobSummary
from downloader.tui import TerminalPresenter


def render() -> None:
    console = Console(
        file=StringIO(),
        width=90,
        record=True,
        force_terminal=True,
        color_system='truecolor',
        _environ={},
    )
    presenter = TerminalPresenter(console)
    console.rule('归档查找 · 演示数据')
    query = ArchiveQuery(keyword='猎人 morui')
    presenter.archive_position(query, 24, 86, 20)
    presenter.download_jobs(
        [
            JobSummary(
                'a1b2c3d4' + f'{index:04x}' + '0' * 20,
                name,
                'morui',
                'completed',
                '2026-10-27T10:00:00+00:00',
                total,
                0,
            )
            for index, (name, total) in enumerate(
                [('猎人 · 正篇', 120), ('猎人 · 番外', 12), ('猎人 · 特别篇', 3)], start=1
            )
        ],
        archived=True,
    )
    presenter.info('演示仅列出 3 条样例；实际列表每页最多 20 项。')
    presenter.archive_navigation(query, 24, 20)
    console.rule('无匹配时')
    presenter.archive_position(ArchiveQuery(keyword='不存在的漫画'), 0, 86, 20)
    presenter.info('没有符合查找条件的归档。输入 archive 清除条件，返回全部归档。')
    svg = console.export_svg(title='动漫下载器 · 归档查找', clear=False)
    Path(__file__).with_name('archive-find.svg').write_text(
        '\n'.join(line.rstrip() for line in svg.splitlines()) + '\n', encoding='utf-8'
    )
    print(console.export_text(clear=False))


def render_batch(width: int, *, finished: bool = False) -> None:
    console = Console(
        file=StringIO(),
        width=width,
        record=True,
        force_terminal=True,
        color_system='truecolor',
        _environ={},
    )
    entries = [
        ArchiveEntry(
            JobSummary(
                f'{index:032x}', name, 'demo', 'completed', '2026-11-04T14:00:00+00:00', total, 0
            ),
            'a' * 64,
        )
        for index, (name, total) in enumerate(
            [('星海旅人 · 正篇', 120), ('星海旅人 · 番外', 12), ('星海旅人 · 特别篇', 3)], 1
        )
    ]
    if finished:
        entries[0].status = 'archived'
        entries[1].status = 'skipped'
        entries[1].message = '任务自预览后已变化，已跳过；请重新生成批次。'
        entries[2].status = 'failed'
        entries[2].message = '文件暂时不可写，请检查后重新预览。'
    batch = ArchiveBatch(
        'b' * 32,
        'D:/Comics',
        '星海 demo',
        '2026-11-04T14:00:00+00:00',
        entries,
        state='finished' if finished else 'ready',
    )
    TerminalPresenter(console).archive_batch(batch)
    svg = console.export_svg(title='批量归档 · 演示数据', clear=False)
    # Rich's SVG textLength uses character counts; CJK needs terminal-cell widths.
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    root = ET.fromstring(svg)  # noqa: S314 - generated locally by Rich, not external XML
    for node in root.iter('{http://www.w3.org/2000/svg}text'):
        if 'textLength' in node.attrib and node.text:
            length = float(node.attrib['textLength']) * cell_len(node.text) / len(node.text)
            node.attrib['textLength'] = f'{length:g}'
    svg = ET.tostring(root, encoding='unicode')
    suffix = 'result' if finished else 'preview'
    Path(__file__).with_name(f'archive-batch-{suffix}-{width}.svg').write_text(
        '\n'.join(line.rstrip() for line in svg.splitlines()) + '\n', encoding='utf-8'
    )
    print(console.export_text(clear=False))


if __name__ == '__main__':
    if '--batch' in sys.argv:
        render_batch(48)
        render_batch(100)
        render_batch(100, finished=True)
    else:
        render()
