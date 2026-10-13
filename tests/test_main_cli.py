from __future__ import annotations

import sys

import main as main_module
import pytest

from downloader.tui import TerminalPresenter


class FakeContext:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class FakeShell:
    def __init__(self, output_path, overwrite=False, runtime_config=None):
        self.output_path = output_path
        self.overwrite = overwrite
        self.runtime_config = runtime_config
        self.last_command_ok = True
        self.context = FakeContext()
        # 真实 Shell 通过 TerminalPresenter 暴露输出，fake 也需对齐该接口。
        self.presenter = TerminalPresenter()
        self.cmdloop_called = False
        self.sources_called = False
        self.check_called_with = None
        self.retry_called_with = None

    def cmdloop(self):
        self.cmdloop_called = True

    def do_i(self, arg):
        pass

    def do_sources(self, arg):
        self.sources_called = True

    def do_check(self, arg):
        self.check_called_with = arg

    def do_retry(self, arg):
        self.retry_called_with = arg


class InterruptingShell(FakeShell):
    def cmdloop(self):
        raise KeyboardInterrupt


@pytest.mark.parametrize(
    'args',
    [
        ['tasks', 'unfinished', '2'],
        ['tasks', 'ABCD', 'failed', '3'],
        ['tasks', '1234'],
    ],
)
def test_task_filter_and_page_arguments_pass_prevalidation(args):
    _, command, values = main_module._parse_command(args)
    assert command == 'tasks'
    assert values == args[1:]


@pytest.mark.parametrize(
    'args',
    [
        ['tasks', 'next'],
        ['tasks', 'all', '0'],
        ['tasks', 'abcd', 'running'],
        ['tasks', 'all', '2', 'extra'],
    ],
)
def test_invalid_task_filters_fail_before_shell_creation(monkeypatch, args, capsys):
    def fail_shell(*args, **kwargs):
        pytest.fail('invalid tasks syntax must not initialize the shell')

    monkeypatch.setattr(main_module, 'Shell', fail_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', *args])
    assert main_module.main() == 2
    assert '参数错误' in capsys.readouterr().out


def test_help_exits_before_shell_creation(monkeypatch, capsys):
    def fail_shell(*args, **kwargs):
        raise AssertionError('help should not create Shell')

    monkeypatch.setattr(main_module, 'Shell', fail_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', '--help'])

    exit_code = main_module.main()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '用法:' in output
    assert 'download_vols' in output
    assert 'check' in output


def test_default_output_path_is_current_working_directory(monkeypatch, tmp_path):
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = FakeShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader'])
    monkeypatch.chdir(tmp_path)

    exit_code = main_module.main()

    assert exit_code == 0
    assert created_shells[0].output_path == str(tmp_path)
    assert created_shells[0].cmdloop_called is True


def test_sources_subcommand_renders_catalog_without_entering_shell(monkeypatch, tmp_path):
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = FakeShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', str(tmp_path), 'sources'])

    exit_code = main_module.main()

    assert exit_code == 0
    assert created_shells[0].sources_called is True
    assert created_shells[0].cmdloop_called is False
    assert created_shells[0].context.destroyed is True


def test_retry_subcommand_passes_selection_without_entering_shell(monkeypatch, tmp_path):
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = FakeShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', str(tmp_path), 'retry', 'all'])

    exit_code = main_module.main()

    assert exit_code == 0
    assert created_shells[0].retry_called_with == 'all'
    assert created_shells[0].cmdloop_called is False
    assert created_shells[0].context.destroyed is True


def test_check_subcommand_passes_selection_without_entering_shell(monkeypatch, tmp_path):
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = FakeShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', str(tmp_path), 'check', 'morui'])

    exit_code = main_module.main()

    assert exit_code == 0
    assert created_shells[0].check_called_with == 'morui'
    assert created_shells[0].cmdloop_called is False
    assert created_shells[0].context.destroyed is True


def test_keyboard_interrupt_exits_cleanly(monkeypatch, capsys):
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = InterruptingShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader'])

    exit_code = main_module.main()

    output = capsys.readouterr().out
    assert exit_code == main_module.INTERRUPT_EXIT_CODE
    # 中断后走 presenter.farewell()，输出告别横幅与文案。
    assert '再会' in output
    assert '动漫下载器' in output
    assert created_shells[0].context.destroyed is True


def test_config_file_is_loaded_and_passed_to_shell(monkeypatch, tmp_path):
    config_path = tmp_path / 'runtime.json'
    config_path.write_text(
        '{"sources": {"morui": {"enabled": false, "browser_mode": "requests"}}}',
        encoding='utf-8',
    )
    created_shells = []

    def make_shell(output_path, overwrite=False, runtime_config=None):
        shell = FakeShell(output_path, overwrite, runtime_config)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(
        sys,
        'argv',
        ['comic_downloader', '--config', str(config_path), '--overwrite', str(tmp_path)],
    )

    exit_code = main_module.main()

    runtime_config = created_shells[0].runtime_config
    assert exit_code == 0
    assert created_shells[0].output_path == str(tmp_path)
    assert created_shells[0].overwrite is True
    assert runtime_config.enabled_override('morui') is False
    assert runtime_config.browser_mode_override('morui') == 'requests'


def test_missing_config_path_exits_before_shell_creation(monkeypatch, capsys):
    def fail_shell(*args, **kwargs):
        raise AssertionError('invalid config should not create Shell')

    monkeypatch.setattr(main_module, 'Shell', fail_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', '--config'])

    exit_code = main_module.main()

    output = capsys.readouterr().out
    assert exit_code == main_module.CONFIG_ERROR_EXIT_CODE
    assert '--config 需要指定配置文件路径' in output


@pytest.mark.parametrize(
    'args',
    [
        ['--overwite'],
        ['search'],
        ['info', '1'],
        ['info', 'https://example.test/comic', 'extra'],
        ['download'],
        ['download_vols', 'https://example.test/comic'],
        ['download_vols', 'https://example.test/comic', '0'],
        ['download_vols', 'https://example.test/comic', 'first'],
        ['download_vols', 'https://example.test/comic', '1', '5', '2'],
        ['download_vols', 'https://example.test/comic', '1', '2', '3', '4'],
        ['output', 'typo', 'argument'],
        ['--config=a.json', '--config=b.json'],
        ['sources', 'extra'],
        ['check', 'morui', 'extra'],
        ['retry', 'abcd', 'extra'],
        ['tasks', 'abcd', 'extra'],
    ],
)
def test_invalid_arguments_fail_before_shell_creation(monkeypatch, capsys, args):
    monkeypatch.setattr(main_module, 'Shell', lambda *a, **kw: pytest.fail('unexpected Shell'))
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', *args])
    assert main_module.main() == 2
    assert '参数错误' in capsys.readouterr().out


@pytest.mark.parametrize('range_args', [['1'], ['1', '3'], ['1', '2', '3']])
def test_cli_accepts_all_documented_range_forms(range_args):
    args = ['download_vols', 'https://example.test/comic', *range_args]
    _, command, parsed_args = main_module._parse_command(args)
    assert command == 'download_vols'
    assert parsed_args == args[1:]


def test_cli_exception_reports_failure_and_releases_resources(monkeypatch, capsys):
    shell = FakeShell('output')

    def fail_info(arg):
        raise OSError('网络连接失败')

    shell.do_i = fail_info
    monkeypatch.setattr(main_module, 'Shell', lambda *a, **kw: shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader', 'info', 'https://example.test/comic'])
    assert main_module.main() == 1
    assert shell.context.destroyed is True
    assert '网络连接失败' in capsys.readouterr().out
