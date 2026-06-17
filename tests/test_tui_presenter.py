from __future__ import annotations

from io import StringIO

from rich.console import Console

from downloader.models import (
    Comic,
    ComicBook,
    ComicVolume,
    DownloadSummary,
    VolumeDownloadResult,
)
from downloader.tui import TerminalPresenter


def presenter_with_output() -> tuple[TerminalPresenter, StringIO]:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=120)
    return TerminalPresenter(console), output


def test_search_results_render_table_with_source_author_name_and_url():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.source = 'morui'
    comic.author = '作者'
    comic.name = '漫画名'
    comic.url = 'https://example.test/comic'

    presenter.search_results(
        '猎人',
        [comic],
        {'morui': '摩锐漫画'},
        1.25,
    )

    rendered = output.getvalue()
    assert '搜索结果 (1 条，用时 1.2s)' in rendered
    assert '摩锐漫画' in rendered
    assert '作者' in rendered
    assert '漫画名' in rendered
    assert 'https://example.test/comic' in rendered


def test_search_results_render_empty_message():
    presenter, output = presenter_with_output()

    presenter.search_results('不存在', [], {}, 0.1)

    assert '未找到与 "不存在" 相关的结果。' in output.getvalue()


def test_comic_info_renders_metadata_and_chapter_table():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.name = '漫画名'
    comic.metadata = [{'k': '作者', 'v': '作者名'}]
    book = ComicBook()
    book.name = '正篇'
    book.vols = [
        ComicVolume('第1话', 'https://example.test/1'),
        ComicVolume('第2话', 'https://example.test/2'),
    ]
    comic.books = [book]

    presenter.comic_info(comic)

    rendered = output.getvalue()
    assert '漫画名' in rendered
    assert '作者名' in rendered
    assert '1' in rendered
    assert '第1话' in rendered
    assert '2' in rendered
    assert '第2话' in rendered


def test_download_summary_renders_success_counts():
    presenter, output = presenter_with_output()
    summary = DownloadSummary()
    summary.add(
        VolumeDownloadResult(name='第1话', url='https://example.test/1', status='downloaded')
    )
    summary.add(
        VolumeDownloadResult(name='第2话', url='https://example.test/2', status='skipped')
    )

    presenter.download_summary(summary)

    assert '下载完成：成功 1，跳过 1' in output.getvalue()


def test_prompt_includes_current_source_when_selected():
    presenter, _ = presenter_with_output()

    assert presenter.prompt(None) == '动漫下载器> '
    assert presenter.prompt('morui') == '动漫下载器[morui]> '
