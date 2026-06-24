from __future__ import annotations

import sys

import main as main_module
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
        self.context = FakeContext()
        # 真实 Shell 通过 TerminalPresenter 暴露输出，fake 也需对齐该接口。
        self.presenter = TerminalPresenter()
        self.cmdloop_called = False

    def cmdloop(self):
        self.cmdloop_called = True


class InterruptingShell(FakeShell):
    def cmdloop(self):
        raise KeyboardInterrupt


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
