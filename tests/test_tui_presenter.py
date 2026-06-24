from __future__ import annotations

from io import StringIO

from rich.console import Console

from downloader.models import (
    Comic,
    ComicBook,
    ComicVolume,
    DownloadSummary,
    ImageDownloadFailure,
    VolumeDownloadResult,
)
from downloader.tui import SourceStat, TerminalPresenter


def presenter_with_output() -> tuple[TerminalPresenter, StringIO]:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=120)
    return TerminalPresenter(console), output


# ---------------------------------------------------------------------------
# 搜索结果
# ---------------------------------------------------------------------------
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
    assert '搜索结果' in rendered
    assert '猎人' in rendered
    assert '1.2s' in rendered
    assert '摩锐漫画' in rendered
    assert '作者' in rendered
    assert '漫画名' in rendered
    assert 'https://example.test/comic' in rendered


def test_search_results_render_empty_message():
    presenter, output = presenter_with_output()

    presenter.search_results('不存在', [], {}, 0.1)

    assert '未找到与 "不存在" 相关的结果。' in output.getvalue()


def test_search_results_footer_resolves_markup_not_literal():
    """Footer 是富文本标记字符串，必须被渲染为样式而不是字面 [cyan] 文本。"""
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.source = 'morui'
    comic.name = '漫画名'
    comic.url = 'https://example.test/comic'

    presenter.search_results('猎人', [comic] * 3, {'morui': '摩锐漫画'}, 83.4)

    rendered = output.getvalue()
    assert '[cyan]' not in rendered
    assert '3' in rendered
    assert '条结果' in rendered
    assert '83.4s' in rendered


def test_search_results_render_placeholder_for_missing_fields():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.source = 'morui'
    comic.url = 'https://example.test/comic'

    presenter.search_results('猎人', [comic], {'morui': '摩锐漫画'}, 0.2)

    rendered = output.getvalue()
    assert '[未提供]' in rendered


# ---------------------------------------------------------------------------
# 动漫详情
# ---------------------------------------------------------------------------
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
    assert '正篇' in rendered
    assert '第1话' in rendered
    assert '第2话' in rendered


def test_comic_info_renders_author_and_source_when_present():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.name = '漫画名'
    comic.author = '作者名'
    comic.source = 'morui'
    comic.books = []

    presenter.comic_info(comic)

    rendered = output.getvalue()
    assert '漫画名' in rendered
    assert '作者名' in rendered
    assert 'morui' in rendered


# ---------------------------------------------------------------------------
# 下载汇总
# ---------------------------------------------------------------------------
def test_download_summary_renders_success_counts_for_clean_run():
    presenter, output = presenter_with_output()
    summary = DownloadSummary()
    summary.add(
        VolumeDownloadResult(name='第1话', url='https://example.test/1', status='downloaded')
    )
    summary.add(
        VolumeDownloadResult(name='第2话', url='https://example.test/2', status='skipped')
    )

    presenter.download_summary(summary)

    rendered = output.getvalue()
    assert '下载完成' in rendered
    assert '成功 1' in rendered
    assert '跳过 1' in rendered
    assert '失败 0' in rendered


def test_download_summary_renders_detail_table_with_badges_when_failures_exist():
    presenter, output = presenter_with_output()
    summary = DownloadSummary()
    summary.add(
        VolumeDownloadResult(
            name='第1话', url='https://example.test/1', status='downloaded',
            image_count=10, downloaded_count=10,
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第2话', url='https://example.test/2', status='skipped',
            archive_path='/tmp/第2话.zip',
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第3话', url='https://example.test/3', status='failed', image_count=8,
            downloaded_count=0, message='未解析到任何图片',
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第4话', url='https://example.test/4', status='partial', image_count=5,
            downloaded_count=3,
            failed_images=[ImageDownloadFailure(index=4, url='u', file_path='p', error='超时')],
        )
    )

    presenter.download_summary(summary)

    rendered = output.getvalue()
    assert '下载汇总' in rendered
    assert '失败 1' in rendered
    assert '部分 1' in rendered
    # 详情表头
    assert '状态' in rendered
    assert '图片' in rendered
    # 卷名都出现
    assert '第1话' in rendered
    assert '第2话' in rendered
    assert '第3话' in rendered
    assert '第4话' in rendered
    # 状态徽标文本
    assert '✓ 已下载' in rendered
    assert '⊘ 已跳过' in rendered
    assert '✗ 失败' in rendered
    assert '△ 部分失败' in rendered
    # 图片计数
    assert '10/10' in rendered
    assert '3/5' in rendered
    # 失败图片展开
    assert '超时' in rendered


def test_download_summary_renders_warn_for_empty_run():
    presenter, output = presenter_with_output()
    summary = DownloadSummary()

    presenter.download_summary(summary)

    assert '没有下载任何章节' in output.getvalue()


# ---------------------------------------------------------------------------
# 提示符
# ---------------------------------------------------------------------------
def test_prompt_includes_current_source_when_selected():
    presenter, _ = presenter_with_output()

    assert presenter.prompt(None) == '动漫下载器> '
    assert presenter.prompt('morui') == '动漫下载器[morui]> '


# ---------------------------------------------------------------------------
# 欢迎与退出
# ---------------------------------------------------------------------------
def test_welcome_renders_title_commands_and_sources():
    presenter, output = presenter_with_output()

    presenter.welcome(['摩锐漫画', '读漫屋'])

    rendered = output.getvalue()
    assert '动漫下载器' in rendered
    assert '命令速查' in rendered
    assert 's' in rendered and 'i' in rendered and 'd' in rendered
    assert 'v' in rendered and 'source' in rendered and 'q' in rendered
    assert '摩锐漫画' in rendered
    assert '读漫屋' in rendered


def test_welcome_renders_without_sources():
    presenter, output = presenter_with_output()

    presenter.welcome()

    rendered = output.getvalue()
    assert '动漫下载器' in rendered
    assert '命令速查' in rendered


def test_farewell_renders_message():
    presenter, output = presenter_with_output()

    presenter.farewell()

    rendered = output.getvalue()
    assert '再会' in rendered
    assert '动漫下载器' in rendered


# ---------------------------------------------------------------------------
# 语义化提示
# ---------------------------------------------------------------------------
def test_semantic_methods_render_with_markers():
    presenter, output = presenter_with_output()

    presenter.info('普通信息')
    presenter.success('成功信息')
    presenter.warn('警告信息')
    presenter.error('错误信息')

    rendered = output.getvalue()
    assert '✔ 成功信息' in rendered
    assert '⚠ 警告信息' in rendered
    assert '✖ 错误信息' in rendered
    assert '普通信息' in rendered


def test_source_options_renders_indexed_list_in_panel():
    presenter, output = presenter_with_output()

    presenter.source_options(['摩锐漫画', '读漫屋'])

    rendered = output.getvalue()
    assert '摩锐漫画' in rendered
    assert '读漫屋' in rendered
    assert '1.' in rendered
    assert '2.' in rendered


def test_output_path_renders_path_in_panel():
    presenter, output = presenter_with_output()

    presenter.output_path('/tmp/comics')

    assert '/tmp/comics' in output.getvalue()


# ---------------------------------------------------------------------------
# help 命令速查
# ---------------------------------------------------------------------------
def test_help_renders_command_cheatsheet_panel():
    presenter, output = presenter_with_output()

    presenter.help()

    rendered = output.getvalue()
    assert '命令速查' in rendered
    assert 's' in rendered and 'i' in rendered and 'd' in rendered
    assert 'v' in rendered and 'source' in rendered and 'q' in rendered


# ---------------------------------------------------------------------------
# 搜索结果源状态汇总
# ---------------------------------------------------------------------------
def _comic(source: str = 'morui', name: str = '漫画名') -> Comic:
    comic = Comic()
    comic.source = source
    comic.name = name
    comic.url = 'https://example.test/comic'
    return comic


def test_search_results_renders_source_stats_when_provided():
    presenter, output = presenter_with_output()

    presenter.search_results(
        '猎人',
        [_comic()],
        {'morui': '摩锐漫画'},
        2.5,
        source_stats=[
            SourceStat(display_name='摩锐漫画', ok=True, duration=1.2),
            SourceStat(display_name='读漫屋', ok=False, duration=0.5, error='timeout'),
        ],
    )

    rendered = output.getvalue()
    assert '源状态' in rendered
    assert '摩锐漫画' in rendered
    assert '1.2s' in rendered
    assert '读漫屋' in rendered
    assert 'timeout' in rendered


def test_search_results_omits_source_stats_line_when_not_provided():
    presenter, output = presenter_with_output()

    presenter.search_results('猎人', [_comic()], {'morui': '摩锐漫画'}, 1.0)

    assert '源状态' not in output.getvalue()


def test_search_results_renders_source_stats_for_empty_results():
    """无搜索结果时也应展示各源执行状态，便于排查失败的源。"""
    presenter, output = presenter_with_output()

    presenter.search_results(
        '不存在',
        [],
        {},
        0.1,
        source_stats=[SourceStat(display_name='摩锐漫画', ok=True, duration=0.1)],
    )

    rendered = output.getvalue()
    assert '未找到' in rendered
    assert '源状态' in rendered
    assert '摩锐漫画' in rendered


# ---------------------------------------------------------------------------
# 章节表自适应列数
# ---------------------------------------------------------------------------
def test_chapter_table_columns_adapt_to_console_width():
    """窄终端应收敛到更少列数，宽终端可展开更多列；卷名始终可见。"""
    narrow = Console(width=64, force_terminal=False, color_system=None)
    wide = Console(width=200, force_terminal=False, color_system=None)
    book = ComicBook()
    book.name = '正篇'
    book.vols = [ComicVolume(f'第{i}话', f'https://example.test/{i}') for i in range(1, 7)]

    narrow_table = TerminalPresenter(narrow).chapter_table(0, book)
    wide_table = TerminalPresenter(wide).chapter_table(0, book)

    # 宽终端列数应不少于窄终端
    assert len(wide_table.columns) >= len(narrow_table.columns)
    # 至少 2 列（序号+名称对），且宽终端应在窄终端之上
    assert len(narrow_table.columns) >= 2
    assert len(wide_table.columns) > len(narrow_table.columns)
