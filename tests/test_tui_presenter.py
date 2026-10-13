from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from downloader.download.job_browser import TaskQuery
from downloader.download.jobs import DownloadJob, JobVolume
from downloader.models import (
    Comic,
    ComicBook,
    ComicVolume,
    DownloadSummary,
    ImageDownloadFailure,
    SearchOutcome,
    VolumeDownloadResult,
)
from downloader.tui import RetryTaskView, SourceStat, SourceView, TerminalPresenter


@pytest.mark.parametrize('width', [40, 80, 120])
def test_archive_views_show_literal_names_and_only_archive_navigation(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    volume = JobVolume('正篇', '第一话', 'https://example.test/1')
    volume.result = VolumeDownloadResult(volume.name, volume.url, 'downloaded')
    job = DownloadJob('fixture', '[red]漫画[/]', '', [volume], state='completed')
    presenter.download_jobs([job], archived=True)
    presenter.download_job(job, archived=True)
    presenter.archive_navigation('archive list', 2, 45, 20)
    text = output.getvalue()
    plain = ''.join(text.replace('│', '').split())
    assert '[red]漫画[/]' in plain
    assert '已归档计划' in text
    assert '归档计划详情' in text
    assert f'archiverestore{job.id}' in plain
    assert 'archivelist1' in plain and 'archivelist3' in plain
    assert 'retry' not in text and 'tasks next' not in text


@pytest.mark.parametrize('width', [40, 80, 120])
def test_catalog_warnings_are_visible_literal_and_bounded(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    comic = Comic()
    comic.name = '详情回归'
    comic.parse_warnings = ['[red]追加章节失败[/]', *[f'提示{i}' for i in range(8)]]
    presenter.comic_info(comic)
    presenter.comic_parse_notes(comic, downloading=True)
    rendered = output.getvalue()
    assert '章节解析提示' in rendered
    assert '[red]追加章节失败[/]' in rendered
    assert '提示7' not in rendered
    assert '另有 4 项提示' in rendered
    assert '任务完成不代表网站全书已完整获取' in ''.join(rendered.replace('│', '').split())


@pytest.mark.parametrize('width', [40, 80, 120])
def test_filtered_search_shows_original_ids_literal_filter_and_navigation(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    comics = []
    for index in range(50):
        comic = Comic()
        comic.name = f'漫画{index + 1:03d}'
        comic.source = 'fixture'
        comics.append(comic)
    presenter.search_results(
        '漫画',
        comics,
        {'fixture': '测试源'},
        1.2,
        result_indices=list(range(25, 50)),
        filter_text='[red]',
        page=2,
    )
    rendered = output.getvalue()
    assert '[red]' in rendered
    assert '匹配 25 / 50 条' in rendered
    assert '漫画046' in rendered
    assert '漫画050' in rendered
    assert '漫画045' not in rendered
    assert 'p prev' in rendered
    assert 'p next' not in rendered
    assert '46' in rendered
    assert '第 2/2 页' in rendered


def test_empty_filter_shows_clear_action_instead_of_network_search_failure():
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=80, color_system=None))
    presenter.search_results('漫画', [Comic()], {}, 0.1, result_indices=[], filter_text='missing')
    rendered = output.getvalue()
    assert '匹配 0 / 1 条' in rendered
    assert 'f 清除筛选' in rendered
    assert '未找到与' not in rendered


def test_narrow_help_keeps_command_descriptions_readable():
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=40, color_system=None))
    presenter.welcome(['fixture'])
    rendered = output.getvalue()
    assert '…' not in rendered
    assert 'next/prev' in rendered
    assert '筛选缓存结果' in rendered


@pytest.mark.parametrize('width', [40, 80, 120])
def test_search_report_keeps_error_literal_and_explains_empty_results(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    presenter.search_report(
        [
            SearchOutcome('broken', [], '[red]HTTP 500[/]', 1.2),
            SearchOutcome('empty', [], None, 0.2),
            SearchOutcome('captcha', [], '使用 URL', 0, skipped=True),
        ]
    )
    rendered = output.getvalue()
    assert 'broken' in rendered
    assert '[red]HTTP 500[/]' in rendered
    assert '未检出' in rendered
    assert '跳过' in rendered
    assert '使用 URL' in rendered
    assert '可重试或改用漫画URL' in ''.join(rendered.split())


@pytest.mark.parametrize('width', [40, 80, 120])
def test_task_list_and_details_show_recovery_actions(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    volume = JobVolume('正篇', '[red]第一话[/]', 'https://example.test/1')
    volume.result = VolumeDownloadResult(volume.name, volume.url, 'failed', message='网络超时')
    job = DownloadJob('test', '测试漫画', 'https://example.test/comic', [volume], state='failed')
    presenter.download_jobs([job])
    assert job.id[:12] in output.getvalue()
    presenter.download_job(job)
    rendered = output.getvalue()
    assert job.id[:12] in rendered
    assert '测试漫画' in rendered
    assert '网络超时' in rendered
    assert 'retry' in rendered
    assert '0/1' in rendered


@pytest.mark.parametrize('width', [40, 80, 120])
def test_task_detail_filter_retains_original_chapter_numbers_and_literal_errors(width):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    volumes = [JobVolume('正篇', f'话{i:03d}', f'https://example.test/{i}') for i in range(1, 36)]
    volumes[30].result = VolumeDownloadResult(
        '话031', volumes[30].url, 'partial', message='[red]失败[/]'
    )
    job = DownloadJob('test', '漫画', 'https://example.test/comic', volumes, state='failed')
    presenter.task_position(TaskQuery(job.id, 'failed'), 1, 35, 30)
    presenter.download_job(job, volume_indices=[30])
    rendered = output.getvalue()
    assert '匹配 1 / 35 项' in rendered
    assert '话031' in rendered
    assert '话001' not in rendered
    assert '[red]失败[/]' in rendered
    assert '筛选不改变重试范围' in ''.join(rendered.split())
    assert '31' in rendered


def test_direct_task_navigation_provides_explicit_commands():
    presenter, output = presenter_with_output()
    presenter.task_navigation(TaskQuery(status='unfinished', page=2), 43, 20, interactive=False)
    rendered = output.getvalue()
    assert 'tasks unfinished 1' in rendered
    assert 'tasks unfinished 3' in rendered
    assert 'tasks next' not in rendered


def test_external_text_is_rendered_literally():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.name = '[red]漫画[/red]'
    comic.author = '作者[/]'
    presenter.search_results('[bold]关键词[/bold]', [comic], {}, 0.1)
    presenter.output_path('D:/[red]漫画[/red]')
    presenter.error('网络[/]错误')
    rendered = output.getvalue()
    assert '[red]漫画[/red]' in rendered
    assert '[bold]关键词[/bold]' in rendered
    assert '作者[/]' in rendered
    assert 'D:/[red]漫画[/red]' in rendered
    assert '网络[/]错误' in rendered


def test_narrow_search_keeps_selection_readable_and_details_expose_url():
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=40, color_system=None))
    comic = Comic()
    comic.name = '漫画名'
    comic.author = '作者名'
    comic.source = 'test'
    comic.url = 'https://example.test/comic'
    presenter.search_results('漫画', [comic], {'test': '测试源'}, 0.1)
    rendered = output.getvalue()
    assert '漫画名' in rendered
    assert '测试源' in rendered
    assert '窄屏模式' in rendered
    assert comic.url not in rendered
    presenter.comic_info(comic)
    assert comic.url in output.getvalue()
    assert comic.author in output.getvalue()


@pytest.mark.parametrize('width, expected_columns', [(40, 2), (80, 4), (120, 6)])
def test_chapter_table_adapts_to_terminal_width(width, expected_columns):
    output = StringIO()
    presenter = TerminalPresenter(Console(file=output, width=width, color_system=None))
    book = ComicBook()
    book.name = '[正篇]'
    book.vols = [ComicVolume(f'第{i}话', 'url') for i in range(1, 8)]
    table = presenter.chapter_table(0, book)
    presenter.print(table)
    assert len(table.columns) == expected_columns
    rendered = output.getvalue()
    assert '7 话' in rendered
    assert '[正篇]' in rendered
    for i in range(1, 8):
        assert f'第{i}话' in rendered


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
    summary.add(VolumeDownloadResult(name='第2话', url='https://example.test/2', status='skipped'))

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
            name='第1话',
            url='https://example.test/1',
            status='downloaded',
            image_count=10,
            downloaded_count=10,
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第2话',
            url='https://example.test/2',
            status='skipped',
            archive_path='C:/downloads/第2话.zip',
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第3话',
            url='https://example.test/3',
            status='failed',
            image_count=8,
            downloaded_count=0,
            message='未解析到任何图片',
        )
    )
    summary.add(
        VolumeDownloadResult(
            name='第4话',
            url='https://example.test/4',
            status='partial',
            image_count=5,
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
    assert '已下载' in rendered
    assert '已跳过' in rendered
    assert '失败' in rendered
    assert '部分失败' in rendered
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
    assert '已启用 2 个动漫源' in rendered
    assert 'sources' in rendered


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
    assert '成功 成功信息' in rendered
    assert '注意 警告信息' in rendered
    assert '错误 错误信息' in rendered
    assert '普通信息' in rendered


def test_source_catalog_renders_capabilities_and_current_source():
    presenter, output = presenter_with_output()

    presenter.source_catalog(
        [
            SourceView(1, 'morui', '摩锐漫画', 'seleniumbase', True, True, selected=True),
            SourceView(
                2,
                'dumanwu',
                '读漫屋',
                'requests',
                False,
                True,
                supports_info=False,
                verification_status='healthy',
                last_verified_at='2026-08-08T00:00:00+08:00',
            ),
        ]
    )

    rendered = output.getvalue()
    assert '动漫源 · 2 个已启用' in rendered
    assert '摩锐漫画' in rendered
    assert '读漫屋' in rendered
    assert 'morui' in rendered
    assert 'SeleniumBase' in rendered
    assert 'HTTP' in rendered
    assert '浏览器' in rendered
    assert '详情' in rendered
    assert '未检查' in rendered
    assert '不支持' in rendered
    assert '正常' in rendered
    assert '2026-08-08' in rendered
    assert '>' in rendered
    assert max(len(line) for line in rendered.splitlines()) <= 112


def test_source_catalog_hides_code_column_on_narrow_terminal():
    output = StringIO()
    presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=72)
    )

    presenter.source_catalog([SourceView(1, 'morui', '摩锐漫画', 'cloakbrowser', True, True)])

    rendered = output.getvalue()
    assert 'morui' not in rendered
    assert 'CloakBrowser' in rendered


def test_source_catalog_renders_empty_configuration_state():
    presenter, output = presenter_with_output()

    presenter.source_catalog([])

    rendered = output.getvalue()
    assert '没有启用的动漫源' in rendered
    assert 'sources.<名称>.enabled' in rendered


def test_source_feedback_uses_gbk_safe_characters():
    presenter, output = presenter_with_output()

    presenter.source_selected('摩锐漫画', 'morui')
    presenter.source_unchanged('摩锐漫画')

    output.getvalue().encode('gbk')


def test_source_not_found_escapes_user_markup():
    presenter, output = presenter_with_output()

    presenter.source_not_found('[red]unknown[/]', 7)

    rendered = output.getvalue()
    assert '[red]unknown[/]' in rendered
    assert '1 到 7' in rendered


def test_retry_tasks_render_pending_downloads_and_commands():
    presenter, output = presenter_with_output()

    presenter.retry_tasks(
        [
            RetryTaskView(
                index=1,
                task_id='abc123def456',
                source_name='摩锐漫画',
                volume_name='第 12 话',
                status='partial',
                attempts=2,
                updated_at='2026-08-08T10:00:00+00:00',
                message='1 张图片失败',
            )
        ]
    )

    rendered = output.getvalue()
    assert '下载恢复 · 1 个待处理' in rendered
    assert '摩锐漫画' in rendered
    assert '第 12 话' in rendered
    assert '部分失败' in rendered
    assert 'abc123def456' in rendered
    assert 'retry all' in rendered


def test_retry_tasks_render_empty_state():
    presenter, output = presenter_with_output()

    presenter.retry_tasks([])

    rendered = output.getvalue()
    assert '没有待恢复的下载任务' in rendered
    assert '自动记录' in rendered


def test_output_path_renders_path_in_panel():
    presenter, output = presenter_with_output()

    presenter.output_path('C:/downloads/comics')

    assert 'C:/downloads/comics' in output.getvalue()


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
