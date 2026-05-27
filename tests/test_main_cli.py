from __future__ import annotations

import sys

import main as main_module


class FakeContext:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class FakeShell:
    def __init__(self, output_path, overwrite=False):
        self.output_path = output_path
        self.overwrite = overwrite
        self.context = FakeContext()
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

    def make_shell(output_path, overwrite=False):
        shell = FakeShell(output_path, overwrite)
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

    def make_shell(output_path, overwrite=False):
        shell = InterruptingShell(output_path, overwrite)
        created_shells.append(shell)
        return shell

    monkeypatch.setattr(main_module, 'Shell', make_shell)
    monkeypatch.setattr(sys, 'argv', ['comic_downloader'])

    exit_code = main_module.main()

    output = capsys.readouterr().out
    assert exit_code == main_module.INTERRUPT_EXIT_CODE
    assert '感谢使用，再会！' in output
    assert created_shells[0].context.destroyed is True
