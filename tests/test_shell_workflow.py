from __future__ import annotations

from io import StringIO

import main as main_module
import pytest
from rich.console import Console

from downloader.comic import ComicSource
from downloader.download.progress import NoopDownloadProgress
from downloader.models import Comic, ComicBook, ComicVolume, VolumeDownloadResult
from downloader.shell import Shell, url_belongs_to_source
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
