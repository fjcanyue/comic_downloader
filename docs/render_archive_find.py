"""Render synthetic archive UX examples: python docs/render_archive_find.py."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

from rich.console import Console

# Allow running this documentation helper directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


if __name__ == '__main__':
    render()
