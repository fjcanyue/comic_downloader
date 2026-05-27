from __future__ import annotations

from io import StringIO
from typing import Any, cast

from rich.console import Console

from downloader.comic import ComicSource
from downloader.shell import Context, Shell


def quiet_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, color_system=None)


def test_context_create_does_not_initialize_webdriver(monkeypatch, tmp_path):
    def fail_init_driver(self):
        raise AssertionError('driver should be lazy')

    monkeypatch.setattr(Context, 'init_driver', fail_init_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.driver is None


def test_context_ensure_driver_initializes_once(monkeypatch, tmp_path):
    driver = object()
    calls = []

    def fake_init_driver(self):
        calls.append(True)
        self.driver = driver
        return True

    monkeypatch.setattr(Context, 'init_driver', fake_init_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.ensure_driver() is True
    assert context.ensure_driver() is True
    assert context.driver is driver
    assert calls == [True]


def test_shell_uses_plain_stdin_for_interactive_prompt():
    assert Shell.use_rawinput is False


class DriverBackedSource(ComicSource):
    name = 'driver-backed'
    download_requires_driver = True

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_shell_attaches_lazy_driver_to_current_source(monkeypatch, tmp_path):
    driver = object()
    shell = Shell(str(tmp_path))
    source = DriverBackedSource(
        str(tmp_path),
        cast(Any, shell.context.http),
        None,
        overwrite=False,
    )
    cast(Any, shell.context).source = source

    def fake_ensure_driver():
        shell.context.driver = driver
        return True

    monkeypatch.setattr(shell.context, 'ensure_driver', fake_ensure_driver)

    try:
        assert shell._ensure_source_download_ready() is True
        assert source.driver is driver
    finally:
        shell.context.destroy()
