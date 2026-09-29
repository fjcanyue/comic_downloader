from __future__ import annotations

from io import StringIO

import main as main_module
import pytest
from rich.console import Console

from downloader.comic import ComicSource
from downloader.models import Comic, ComicBook, ComicVolume, DownloadSummary, VolumeDownloadResult
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

    def download_vols(self, comic_name, book_name, vols):
        self.downloaded_urls = [vol.url for vol in vols]
        return DownloadSummary(
            [VolumeDownloadResult(vol.name, vol.url, 'downloaded') for vol in vols]
        )


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
        'download_full_by_url',
        lambda url: DownloadSummary([VolumeDownloadResult('第一话', url, status)]),
    )
    assert main_module._run_command(shell, 'download', ['https://first.test/comic']) == exit_code


def test_invalid_range_exit_code_and_no_download(shell):
    result = main_module._run_command(
        shell, 'download_vols', ['https://first.test/comic', '1', '9']
    )
    assert result == 1
    assert not hasattr(shell.context.source, 'downloaded_urls')


def test_empty_download_summary_is_failure(shell, monkeypatch):
    shell.onecmd('source first')
    monkeypatch.setattr(shell.context.source, 'download_full_by_url', lambda url: DownloadSummary())
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
