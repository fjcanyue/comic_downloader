from __future__ import annotations

import threading
from dataclasses import replace
from io import StringIO

import main as main_module
import pytest
from rich.console import Console

from downloader.browser.manager import DriverManager
from downloader.comic import ComicSource
from downloader.download.jobs import DownloadJob, JobVolume
from downloader.download.progress import NoopDownloadProgress
from downloader.models import Comic, ComicBook, ComicVolume, VolumeDownloadResult
from downloader.shell import Shell, url_belongs_to_source
from downloader.sources.metadata import SourceVerification
from downloader.sources.profiles import SourceBinding, SourceProfile
from downloader.tui import TerminalPresenter


class WorkflowSource(ComicSource):
    name = '测试漫画源'

    def search(self, keyword):
        return [self.info(f'{self.base_url}/comic')]

    def info(self, url):
        comic = Comic()
        comic.name = '[red]漫画[/red]'
        comic.url = url
        book = ComicBook()
        book.name = '正篇'
        book.vols = [ComicVolume(f'第{i}话', f'{self.base_url}/{i}') for i in range(1, 6)]
        comic.books = [book]
        return comic

    def __parse_imgs__(self, url):
        return []

    def __download_vol__(self, path, vol_name, url, parent_progress=None):
        self.downloaded_urls = [*getattr(self, 'downloaded_urls', []), url]
        return VolumeDownloadResult(vol_name, url, 'downloaded')

    def create_download_progress(self):
        return NoopDownloadProgress()


@pytest.fixture
def shell(monkeypatch, tmp_path):
    bindings = {
        name: SourceBinding(
            name,
            WorkflowSource,
            SourceProfile(
                source_name=name,
                class_name='WorkflowSource',
                enabled=True,
                deprecated=False,
                base_url=f'https://{name}.test',
            ),
        )
        for name in ('first', 'second')
    }
    monkeypatch.setattr(Shell, '_discover_source_bindings', lambda *a, **kw: bindings)
    presenter = TerminalPresenter(Console(file=StringIO(), width=100, color_system=None))
    instance = Shell(str(tmp_path))
    instance.presenter = presenter
    instance.console = presenter.console
    instance.stdin = StringIO()
    instance.stdout = StringIO()
    yield instance
    instance.context.destroy()


def test_search_info_range_download_stays_in_shell(shell):
    assert not shell.onecmd('s 测试')
    assert len(shell.context.searched_results) == 2
    assert not shell.onecmd('i 2')
    assert shell.current_source_name == 'second'
    assert not shell.onecmd('v 1 2 4')
    assert shell.last_command_ok is True
    assert shell.context.source.downloaded_urls == [
        'https://second.test/2',
        'https://second.test/3',
        'https://second.test/4',
    ]


def test_blank_line_does_not_repeat_download(shell, monkeypatch):
    calls = []
    monkeypatch.setattr(shell, 'do_d', calls.append)
    shell.onecmd('d 1')
    shell.onecmd('')
    shell.onecmd('   ')
    assert calls == ['1']


def test_retry_all_handles_plans_and_standalone_chapters_without_duplicate_attempts(
    shell, monkeypatch
):
    job = DownloadJob(
        'first',
        '漫画',
        'https://first.test/comic',
        [
            JobVolume('正篇', '第一话', 'https://first.test/1'),
            JobVolume('正篇', '第二话', 'https://first.test/2'),
        ],
    )
    shell.job_store.save(job)
    tasks = [
        shell.task_store.start(
            source_name='first',
            volume_name=f'第{index}话',
            source_url=f'https://first.test/{index}',
            target_path=shell.task_store.output_dir / f'comic/book/{index}',
        )
        for index in (1, 3)
    ]
    attempts = []

    def retry_job(job_id):
        attempts.append(('job', job_id))
        shell.last_command_ok = False

    def retry_chapter(task):
        attempts.append(('chapter', task.task_id))
        return VolumeDownloadResult(task.volume_name, task.source_url, 'downloaded')

    monkeypatch.setattr(shell, '_retry_job', retry_job)
    monkeypatch.setattr(shell, '_retry_download_task', retry_chapter)
    shell.do_retry('all')
    assert attempts == [('job', job.id), ('chapter', tasks[1].task_id)]
    assert shell.last_command_ok is False


def test_retry_without_selection_lists_both_record_types(shell):
    job = DownloadJob(
        'first',
        '漫画',
        'https://first.test/comic',
        [
            JobVolume('正篇', '第一话', 'https://first.test/1'),
        ],
    )
    shell.job_store.save(job)
    task = shell.task_store.start(
        source_name='first',
        volume_name='独立章节',
        source_url='https://first.test/2',
        target_path=shell.task_store.output_dir / 'comic/book/2',
    )
    assert main_module._run_command(shell, 'retry', []) == 0
    rendered = shell.console.file.getvalue()
    assert job.id[:12] in rendered
    assert task.task_id in rendered


@pytest.mark.parametrize(
    ('status', 'exit_code'), [('healthy', 0), ('degraded', 1), ('unavailable', 1)]
)
def test_source_check_cli_reports_health_and_resets_previous_failure(
    shell, monkeypatch, status, exit_code
):
    monkeypatch.setattr(
        shell,
        '_check_source',
        lambda name: SourceVerification(status=status, checked_at='2026-09-29T00:00:00+00:00'),
    )
    shell.last_command_ok = False
    assert main_module._run_command(shell, 'check', ['first']) == exit_code
    assert main_module._run_command(shell, 'sources', []) == 0


def test_eof_closes_context_and_stops_loop(shell, monkeypatch):
    closed = []
    monkeypatch.setattr(shell.context, 'destroy', lambda: closed.append(True))
    assert shell.onecmd('EOF') is True
    assert closed == [True]


def test_source_change_invalidates_details_but_preserves_results(shell):
    shell.onecmd('s 测试')
    shell.onecmd('i 1')
    shell.onecmd('source second')
    assert shell.context.comic is None
    assert len(shell.context.searched_results) == 2
    shell.onecmd('v 1')
    assert shell.last_command_ok is False
    assert not hasattr(shell.context.source, 'downloaded_urls')


@pytest.mark.parametrize('selection', ['1', 'first'])
def test_direct_source_selection(shell, selection):
    assert not shell.onecmd(f'source {selection}')
    assert shell.current_source_name == 'first'
    assert shell.last_command_ok is True


@pytest.mark.parametrize('input_text', ['\n', 'q\n', 'invalid\nq\n', ''])
def test_source_menu_can_cancel(shell, input_text):
    shell.stdin = StringIO(input_text)
    assert not shell.onecmd('source')
    assert shell.current_source_name is None


def test_source_menu_without_enabled_sources_does_not_prompt(shell, monkeypatch):
    shell.source_options = []
    monkeypatch.setattr(shell, '_read_prompt_line', lambda _: pytest.fail('unexpected prompt'))
    shell.onecmd('source')
    assert shell.last_command_ok is False


@pytest.mark.parametrize('command', ['i invalid', 'i 0', 'i'])
def test_invalid_info_cannot_leave_previous_comic_downloadable(shell, command):
    shell.onecmd('i https://first.test/comic')
    assert shell.context.comic is not None
    shell.onecmd(command)
    assert shell.context.comic is None
    shell.onecmd('d')
    assert shell.last_command_ok is False


def test_parser_exception_is_recoverable_and_clears_stale_details(shell, monkeypatch):
    shell.onecmd('i https://first.test/comic')

    def fail_info(url):
        raise ValueError('网页格式已改变 [red]')

    monkeypatch.setattr(shell.context.source, 'info', fail_info)
    assert not shell.onecmd('i https://first.test/another')
    assert shell.context.comic is None
    assert shell.last_command_ok is False
    assert not shell.onecmd('status')
    assert '网页格式已改变 [red]' in shell.console.file.getvalue()


@pytest.mark.parametrize(
    'url, expected',
    [
        ('https://first.test/comic', True),
        ('https://FIRST.test/comic', True),
        ('http://first.test/comic', True),
        ('https://first.test:443/comic', True),
        ('http://first.test:80/comic', True),
        ('https://first.test.evil.test/comic', False),
        ('https://first.test@evil.test/comic', False),
        ('https://user@first.test/comic', False),
        ('https://first.test:bad/comic', False),
        ('https://first.test:123/comic', False),
        ('file://first.test/comic', False),
        ('https://[invalid', False),
    ],
)
def test_source_url_matching_uses_host(url, expected):
    assert url_belongs_to_source(url, 'https://first.test') is expected


@pytest.mark.parametrize(
    'status, exit_code',
    [
        ('downloaded', 0),
        ('skipped', 0),
        ('partial', 1),
        ('failed', 1),
    ],
)
def test_download_exit_code_reflects_actual_summary(shell, monkeypatch, status, exit_code):
    shell.onecmd('source first')
    monkeypatch.setattr(
        shell.context.source,
        '__download_vol__',
        lambda path, name, url, progress: VolumeDownloadResult(name, url, status),
    )
    assert main_module._run_command(shell, 'download', ['https://first.test/comic']) == exit_code


def test_invalid_range_exit_code_and_no_download(shell):
    result = main_module._run_command(
        shell, 'download_vols', ['https://first.test/comic', '1', '9']
    )
    assert result == 1
    assert not hasattr(shell.context.source, 'downloaded_urls')


def test_empty_download_plan_is_failure(shell, monkeypatch):
    shell.onecmd('source first')
    monkeypatch.setattr(shell.context.source, 'info', lambda url: Comic())
    assert main_module._run_command(shell, 'download', ['https://first.test/comic']) == 1


def test_lookalike_url_is_rejected_even_when_source_selected(shell, monkeypatch):
    shell.onecmd('source first')
    monkeypatch.setattr(
        shell.context.source, 'info', lambda url: pytest.fail('unsupported URL was fetched')
    )
    assert main_module._run_command(shell, 'info', ['https://first.test.evil.test/comic']) == 1


def test_empty_group_does_not_initialize_download_driver(shell, monkeypatch):
    shell.onecmd('i https://first.test/comic')
    shell.context.comic.books[0].vols = []
    monkeypatch.setattr(
        shell, '_ensure_source_download_ready', lambda: pytest.fail('empty group needs no driver')
    )
    shell.onecmd('v 1')
    assert shell.last_command_ok is False


def test_search_all_failures_and_empty_success_are_distinct(shell, monkeypatch):
    def fail_search(self, keyword):
        raise OSError('离线')

    monkeypatch.setattr(WorkflowSource, 'search', fail_search)
    assert main_module._run_command(shell, 'search', ['漫画']) == 1
    assert '所有搜索源均失败' in shell.console.file.getvalue()
    monkeypatch.setattr(WorkflowSource, 'search', lambda self, keyword: [])
    assert main_module._run_command(shell, 'search', ['漫画']) == 0


def test_shell_task_history_and_retry_after_new_session(shell, monkeypatch, tmp_path):
    shell.onecmd('i https://first.test/comic')
    source = shell.context.source
    original_download = source.__download_vol__

    def interrupted(path, name, url, progress):
        if url.endswith('/3'):
            raise KeyboardInterrupt
        return original_download(path, name, url, progress)

    monkeypatch.setattr(source, '__download_vol__', interrupted)
    with pytest.raises(KeyboardInterrupt):
        shell.onecmd('v 1 2 4')
    jobs, errors = shell.job_store.list_jobs()
    assert not errors
    job = jobs[0]
    assert len(job.volumes) == 3
    assert job.state == 'interrupted'
    shell.onecmd(f'tasks {job.id[:12]}')
    assert '已中断' in shell.console.file.getvalue()

    restarted = Shell(str(tmp_path))
    try:
        assert main_module._run_command(restarted, 'retry', [job.id[:12]]) == 0
        assert restarted.context.comic is None
        assert isinstance(restarted.context.source, WorkflowSource)
        assert restarted.context.source.downloaded_urls == [
            'https://first.test/3',
            'https://first.test/4',
        ]
        assert len(restarted.job_store.list_jobs()[0]) == 1
        assert restarted.job_store.load(job.id).state == 'completed'
    finally:
        restarted.context.destroy()


def test_tasks_does_not_initialize_browser_or_create_history_directory(shell, monkeypatch):
    monkeypatch.setattr(shell.context, 'ensure_driver', lambda _: pytest.fail('unexpected browser'))
    assert main_module._run_command(shell, 'tasks', []) == 0
    assert not shell.job_store.directory.exists()


def make_browsable_jobs(shell, count):
    jobs = []
    for index in range(count):
        job = DownloadJob(
            'first',
            f'漫画{index:03d}',
            'https://first.test/comic',
            [
                JobVolume('正篇', f'第{number:03d}话', f'https://first.test/{number}')
                for number in range(1, 66)
            ],
            id=f'{index + 1:032x}',
            state='failed',
        )
        for volume in job.volumes:
            volume.result = VolumeDownloadResult(volume.name, volume.url, 'failed', message='超时')
        shell.job_store.save(job)
        jobs.append(job)
    return jobs


def test_task_pages_filters_and_stable_details(shell):
    jobs = make_browsable_jobs(shell, 23)
    shell.onecmd('tasks unfinished')
    output = shell.console.file
    first = output.getvalue()
    assert '漫画022' in first
    assert '漫画000' not in first
    assert 'tasks next' in first
    shell.onecmd('tasks next')
    assert shell.task_query.page == 2
    assert '漫画000' in output.getvalue()
    shell.onecmd('tasks next')
    assert shell.last_command_ok is False
    assert shell.task_query.page == 2
    shell.onecmd(f'tasks {jobs[0].id} failed 2')
    assert shell.task_query.job_id == jobs[0].id
    assert shell.task_query.status == 'failed'
    detail = output.getvalue()[len(first) :]
    assert '第031话' in detail
    assert '第060话' in detail
    assert '第061话' not in detail
    shell.onecmd('tasks next')
    assert '第065话' in output.getvalue()
    assert shell.task_query.page == 3
    shell.onecmd('tasks prev')
    assert shell.task_query.page == 2
    shell.onecmd('tasks')
    assert shell.task_query.job_id is None
    assert shell.task_query.status == 'all'
    assert shell.task_query.page == 1


def test_task_filter_does_not_change_retry_scope_or_current_comic(shell):
    shell.onecmd('i https://first.test/comic')
    comic = shell.context.comic
    job = make_browsable_jobs(shell, 1)[0]
    job.volumes[0].result = None
    shell.job_store.save(job)
    shell.onecmd(f'tasks {job.id} failed')
    assert shell.context.comic is comic
    assert len(shell.job_store.load(job.id).remaining) == 65
    shell.onecmd(f'retry {job.id}')
    assert len(shell.context.source.downloaded_urls) == 65
    assert shell.job_store.load(job.id).state == 'completed'


def test_task_browser_refreshes_changed_records_and_handles_no_matches(shell):
    job = make_browsable_jobs(shell, 1)[0]
    shell.onecmd('tasks completed')
    assert shell.last_command_ok is True
    assert '匹配 0 / 1 项' in shell.console.file.getvalue()
    for volume in job.volumes:
        volume.result = VolumeDownloadResult(volume.name, volume.url, 'skipped')
    job.state = 'completed'
    shell.job_store.save(job)
    shell.onecmd('tasks completed')
    assert '匹配 1 / 1 项' in shell.console.file.getvalue()
    shell.onecmd(f'tasks {job.id} failed')
    assert shell.last_command_ok is True
    assert '没有符合当前筛选的章节' in shell.console.file.getvalue()


def test_task_detail_navigation_keeps_resolved_id_if_prefix_becomes_ambiguous(shell):
    job = make_browsable_jobs(shell, 1)[0]
    job.id = 'abcd' + '0' * 28
    shell.job_store.save(job)
    shell.onecmd('tasks abcd')
    assert shell.task_query.job_id == job.id
    job.id = 'abcd' + '1' * 28
    shell.job_store.save(job)
    shell.onecmd('tasks next')
    assert shell.last_command_ok is True
    assert shell.task_query.job_id == 'abcd' + '0' * 28


def test_corrupt_task_is_reported_without_hiding_valid_tasks(shell):
    job = make_browsable_jobs(shell, 1)[0]
    (shell.job_store.directory / f'{"f" * 32}.json').write_text('{broken', encoding='utf-8')
    shell.onecmd('tasks')
    assert shell.last_command_ok is False
    assert job.comic_name in shell.console.file.getvalue()
    assert '无法读取任务记录' in shell.console.file.getvalue()


def test_direct_task_command_limits_output_and_provides_explicit_page_commands(shell):
    make_browsable_jobs(shell, 23)
    assert main_module._run_command(shell, 'tasks', ['failed']) == 0
    output = shell.console.file.getvalue()
    assert 'tasks failed 2' in output
    assert 'tasks next' not in output
    assert '漫画000' not in output
    assert main_module._run_command(shell, 'tasks', ['failed', '2']) == 0
    assert '漫画000' in shell.console.file.getvalue()


def test_full_download_saves_all_groups(shell, monkeypatch):
    shell.onecmd('i https://first.test/comic')
    extra = ComicBook()
    extra.name = '番外'
    extra.vols = [ComicVolume('特别篇', 'https://first.test/extra')]
    shell.context.comic.books.append(extra)
    shell.onecmd('d')
    job = shell.job_store.list_jobs()[0][0]
    assert len(job.volumes) == 6
    assert job.volumes[-1].book_name == '番外'
    assert job.state == 'completed'


def test_partial_catalog_warns_before_downloading_only_available_chapters(shell, monkeypatch):
    original = WorkflowSource.info

    def partial_info(self, url):
        comic = original(self, url)
        comic.parse_warnings = ['追加章节请求失败，当前列表可能不完整。']
        return comic

    monkeypatch.setattr(WorkflowSource, 'info', partial_info)
    shell.onecmd('i https://first.test/comic')
    assert '章节解析提示' in shell.console.file.getvalue()
    shell.console.file.seek(0)
    shell.console.file.truncate(0)
    shell.onecmd('d https://first.test/comic')
    assert shell.last_command_ok is True
    output = shell.console.file.getvalue()
    assert output.index('章节解析提示') < output.index('下载任务已保存')
    job = shell.job_store.list_jobs()[0][0]
    assert len(job.volumes) == 5
    assert job.state == 'completed'


def test_unavailable_driver_keeps_retryable_plan(shell, monkeypatch):
    shell.onecmd('i https://first.test/comic')
    monkeypatch.setattr(shell, '_ensure_source_download_ready', lambda: False)
    shell.onecmd('v 1 2 3')
    jobs, _ = shell.job_store.list_jobs()
    assert shell.last_command_ok is False
    assert len(jobs) == 1
    assert len(jobs[0].remaining) == 2
    assert jobs[0].state == 'pending'


def test_retry_missing_source_preserves_job(shell):
    shell.onecmd('i https://first.test/comic')
    shell.onecmd('v 1 2 3')
    job = shell.job_store.list_jobs()[0][0]
    job.volumes[0].result = None
    job.state = 'interrupted'
    job.source_name = 'removed'
    shell.job_store.save(job)
    shell.onecmd(f'retry {job.id[:12]}')
    assert shell.last_command_ok is False
    assert shell.job_store.load(job.id).state == 'interrupted'


def make_search_results(source, count):
    results = []
    for index in range(1, count + 1):
        comic = Comic()
        comic.name = f'{source.profile.source_name}-{index:03d}'
        comic.url = f'{source.base_url}/{index}'
        results.append(comic)
    return results


def test_search_pagination_keeps_all_results_and_original_selection_indices(shell, monkeypatch):
    searches = []

    def search(self, keyword):
        searches.append(self.profile.source_name)
        return make_search_results(self, 25)

    monkeypatch.setattr(WorkflowSource, 'search', search)
    shell.onecmd('s 漫画')
    assert len(shell.context.searched_results) == 50
    assert 'first-020' in shell.console.file.getvalue()
    assert 'first-021' not in shell.console.file.getvalue()
    shell.onecmd('p 2')
    assert 'first-021' in shell.console.file.getvalue()
    shell.onecmd('i 21')
    assert shell.context.comic.url == 'https://first.test/21'
    assert sorted(searches) == ['first', 'second']


def test_long_chapter_pagination_preserves_download_range(shell):
    shell.onecmd('i https://first.test/comic')
    book = shell.context.comic.books[0]
    book.vols = [ComicVolume(f'V{i:04d}', f'https://first.test/{i}') for i in range(1, 126)]
    shell._print_comic_info(shell.context.comic)
    assert 'V0060' in shell.console.file.getvalue()
    assert 'V0061' not in shell.console.file.getvalue()
    shell.onecmd('ch 1 2')
    assert 'V0061' in shell.console.file.getvalue()
    assert 'V0120' in shell.console.file.getvalue()
    assert 'V0121' not in shell.console.file.getvalue()
    shell.onecmd('v 1 61 62')
    assert shell.context.source.downloaded_urls == [
        'https://first.test/61',
        'https://first.test/62',
    ]


def test_filter_navigation_preserves_selection_and_never_searches_again(shell, monkeypatch):
    searches = []

    def search(self, keyword):
        searches.append(keyword)
        results = make_search_results(self, 25)
        for comic in results:
            comic.author = '测试作者'
        return results

    monkeypatch.setattr(WorkflowSource, 'search', search)
    shell.onecmd('s 漫画')
    original = list(shell.context.searched_results)
    shell.onecmd('f SECOND 测试作者')
    assert shell.search_result_indices == list(range(25, 50))
    assert shell.search_page == 1
    shell.onecmd('p next')
    assert shell.search_page == 2
    assert 'second-025' in shell.console.file.getvalue()
    shell.onecmd('p')
    assert shell.search_page == 2
    shell.onecmd('p next')
    assert shell.last_command_ok is False
    assert shell.search_page == 2
    shell.onecmd('p prev')
    assert shell.search_page == 1
    shell.onecmd('i 46')
    assert shell.context.comic.url == 'https://second.test/21'
    shell.onecmd('d 46')
    assert shell.last_command_ok is True
    assert shell.job_store.list_jobs()[0][0].comic_url == 'https://second.test/21'
    assert shell.context.searched_results == original
    assert searches == ['漫画', '漫画']
    shell.onecmd('f')
    assert shell.search_result_indices is None
    assert shell.search_filter == ''
    assert shell.search_page == 1


@pytest.mark.parametrize('term', ['测试漫画源', '[red]', 'FIRST'])
def test_filter_matches_literal_titles_and_source_names(shell, term):
    shell.onecmd('s 漫画')
    shell.onecmd(f'f {term}')
    assert shell.last_command_ok is True
    assert shell.search_result_indices == ([0] if term == 'FIRST' else [0, 1])


def test_empty_filter_results_are_recoverable_and_new_search_resets_view(shell):
    shell.onecmd('f 漫画')
    assert shell.last_command_ok is False
    shell.onecmd('s 漫画')
    shell.onecmd('i 1')
    comic = shell.context.comic
    shell.onecmd('f 无匹配内容')
    assert shell.last_command_ok is True
    assert shell.search_result_indices == []
    assert shell.context.comic is comic
    shell.onecmd('status')
    assert '匹配 0 / 2 条' in shell.console.file.getvalue()
    shell.onecmd('p next')
    assert shell.last_command_ok is False
    shell.onecmd('f')
    assert shell.search_result_indices is None
    shell.onecmd('f first')
    shell.onecmd('s 新搜索')
    assert shell.search_filter == ''
    assert shell.search_result_indices is None
    assert shell.search_page == 1


def test_chapter_navigation_remembers_each_group_and_resets_for_new_comic(shell):
    shell.onecmd('i https://first.test/comic')
    book = shell.context.comic.books[0]
    book.vols = [ComicVolume(f'V{i}', f'https://first.test/{i}') for i in range(125)]
    shell.context.comic.books.append(book)
    shell.onecmd('ch 1 next')
    shell.onecmd('ch 2 3')
    shell.onecmd('ch 1')
    assert shell.chapter_pages == {0: 2, 1: 3}
    shell.onecmd('ch 1 prev')
    shell.onecmd('ch 1 prev')
    assert shell.last_command_ok is False
    assert shell.chapter_pages == {0: 1, 1: 3}
    shell.onecmd('i https://second.test/comic')
    assert shell.chapter_pages == {}


@pytest.mark.parametrize(
    'command',
    [
        'p 0',
        'p x',
        'p 99',
        'ch',
        'ch 1 0',
        'ch 2',
        'ch 1 x',
    ],
)
def test_invalid_page_does_not_clear_current_selection(shell, command):
    shell.onecmd('s 漫画')
    shell.onecmd('i 1')
    comic = shell.context.comic
    results = list(shell.context.searched_results)
    assert not shell.onecmd(command)
    assert shell.last_command_ok is False
    assert shell.context.comic is comic
    assert shell.context.searched_results == results


def test_direct_search_command_prints_all_results_without_interactive_pagination(
    shell, monkeypatch
):
    monkeypatch.setattr(
        WorkflowSource, 'search', lambda self, keyword: make_search_results(self, 25)
    )
    assert main_module._run_command(shell, 'search', ['漫画']) == 0
    assert 'first-025' in shell.console.file.getvalue()
    assert 'second-025' in shell.console.file.getvalue()
    assert '第 1/3 页' not in shell.console.file.getvalue()


def test_direct_info_command_prints_all_chapters(shell, monkeypatch):
    def info(self, url):
        comic = Comic()
        comic.url = url
        comic.name = '漫画'
        book = ComicBook()
        book.name = '正篇'
        book.vols = [ComicVolume(f'V{i:04d}', f'https://first.test/{i}') for i in range(1, 126)]
        comic.books = [book]
        return comic

    monkeypatch.setattr(WorkflowSource, 'info', info)
    assert main_module._run_command(shell, 'info', ['https://first.test/comic']) == 0
    assert 'V0125' in shell.console.file.getvalue()


def test_slow_browser_initialization_does_not_block_http_progress(shell, monkeypatch):
    binding = shell.source_bindings['first']
    shell.source_bindings['first'] = replace(
        binding, profile=replace(binding.profile, search_requires_driver=True)
    )
    entered = threading.Event()
    release = threading.Event()
    updates = []

    def ensure_driver(manager, profile):
        entered.set()
        assert release.wait(3), 'HTTP progress was blocked by browser initialization'
        return True

    def search(self, keyword):
        if self.profile.source_name == 'second':
            assert entered.wait(3)
        return make_search_results(self, 1)

    class Status:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def update(self, message):
            updates.append(str(message))
            if 'second' in str(message):
                release.set()

    monkeypatch.setattr(DriverManager, 'ensure_driver', ensure_driver)
    monkeypatch.setattr(WorkflowSource, 'search', search)
    monkeypatch.setattr(shell.presenter, 'status', lambda *a, **kw: Status())
    shell.onecmd('s 漫画')
    assert shell.last_command_ok is True
    assert 'second' in updates[0]
    assert [comic.source for comic in shell.context.searched_results] == ['first', 'second']


@pytest.mark.parametrize('fail', [False, True])
def test_search_browser_lifetime_stays_on_worker_thread(shell, monkeypatch, fail):
    binding = shell.source_bindings['first']
    shell.source_bindings['first'] = replace(
        binding, profile=replace(binding.profile, search_requires_driver=True)
    )
    events = []

    class Driver:
        def quit(self):
            events.append(('close', threading.get_ident()))

    def init_driver(manager, profile):
        events.append(('create', threading.get_ident()))
        manager.current_driver = Driver()
        return True

    def search(source, keyword):
        if source.driver is not None:
            events.append(('search', threading.get_ident()))
            if fail:
                raise RuntimeError('search failure')
        return []

    monkeypatch.setattr(DriverManager, 'init_driver', init_driver)
    monkeypatch.setattr(WorkflowSource, 'search', search)
    shell.onecmd('s 漫画')
    assert [action for action, _ in events] == ['create', 'search', 'close']
    assert len({thread for _, thread in events}) == 1
    assert events[0][1] != threading.get_ident()
    assert shell.context.driver is None
    assert shell.context.drivers == {}


def test_known_unavailable_sources_are_reported_and_not_counted_as_success(shell, monkeypatch):
    monkeypatch.setattr(WorkflowSource, 'search_unavailable_reason', '需要验证码')
    monkeypatch.setattr(WorkflowSource, 'search', lambda *a: pytest.fail('should not search'))
    shell.onecmd('s 漫画')
    assert shell.last_command_ok is False
    assert all(outcome.state == 'skipped' for outcome in shell.search_outcomes)
    assert '需要验证码' in shell.console.file.getvalue()


def test_partial_results_are_visible_even_when_no_source_fully_succeeds(shell, monkeypatch):
    def partial(self, keyword):
        self.search_error = '部分条目损坏'
        return make_search_results(self, 1)

    monkeypatch.setattr(WorkflowSource, 'search', partial)
    assert main_module._run_command(shell, 'search', ['漫画']) == 1
    assert len(shell.context.searched_results) == 2
    assert 'first-001' in shell.console.file.getvalue()
    assert '部分结果' in shell.console.file.getvalue()
