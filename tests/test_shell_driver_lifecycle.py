from __future__ import annotations

import threading
from io import StringIO
from typing import Any, cast

from requests.adapters import HTTPAdapter
from rich.console import Console

from downloader.browser.manager import DriverManager
from downloader.comic import ComicSource
from downloader.download.tasks import DownloadTask
from downloader.models import VolumeDownloadResult
from downloader.runtime_config import RuntimeConfig, SourceRuntimeConfig
from downloader.shell import Context, Shell, url_matches_base
from downloader.sources.metadata import SourceVerification
from downloader.sources.profiles import SourceProfile
from downloader.tui import TerminalPresenter


def quiet_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, color_system=None)


def test_context_create_does_not_initialize_webdriver(monkeypatch, tmp_path):
    def fail_init_driver(self):
        raise AssertionError('driver should be lazy')

    monkeypatch.setattr(Context, 'init_driver', fail_init_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.driver is None


def test_context_http_session_returns_final_retry_status(tmp_path):
    context = Context(quiet_console())
    context.create(str(tmp_path))

    adapter = cast(HTTPAdapter, context.http.get_adapter('https://'))

    assert adapter.max_retries.raise_on_status is False


def test_context_ensure_driver_initializes_once(monkeypatch, tmp_path):
    driver = object()
    calls = []

    def fake_init_driver(self, source_or_class=None):
        calls.append(True)
        self.current_driver = driver
        return True

    monkeypatch.setattr(DriverManager, 'init_driver', fake_init_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.ensure_driver() is True
    assert context.ensure_driver() is True
    assert context.driver is driver
    assert calls == [True]


class CloakBackedSource(ComicSource):
    browser_mode = 'cloakbrowser'
    browser_headless = False

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_context_caches_drivers_by_source_mode(monkeypatch, tmp_path):
    calls = []

    def fake_init_driver(self, source_or_class=None):
        driver = object()
        calls.append(source_or_class)
        self.current_driver = driver
        return True

    monkeypatch.setattr(DriverManager, 'init_driver', fake_init_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.ensure_driver(CloakBackedSource) is True
    first_driver = context.driver
    assert context.ensure_driver(CloakBackedSource) is True

    assert context.driver is first_driver
    assert calls == [CloakBackedSource]


class SeleniumBaseBackedSource(ComicSource):
    browser_mode = 'seleniumbase'
    browser_headless = False

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_context_initializes_seleniumbase_for_seleniumbase_mode(monkeypatch, tmp_path):
    driver = object()
    calls = []

    def fake_init_seleniumbase_driver(self, source_or_class=None):
        calls.append(source_or_class)
        self.current_driver = driver
        return True

    def fail_init_selenium_driver(self):
        raise AssertionError('raw Selenium driver should not be initialized')

    monkeypatch.setattr(
        DriverManager, '_try_init_seleniumbase_driver', fake_init_seleniumbase_driver
    )
    monkeypatch.setattr(DriverManager, '_try_init_selenium_driver', fail_init_selenium_driver)

    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context.ensure_driver(SeleniumBaseBackedSource) is True
    assert context.ensure_driver(SeleniumBaseBackedSource) is True
    assert context.driver is driver
    assert calls == [SeleniumBaseBackedSource]


def test_context_driver_mode_uses_profile_browser_mode(tmp_path):
    profile = SourceProfile(
        source_name='profiled',
        class_name='ProfiledSource',
        enabled=True,
        deprecated=False,
        browser_mode='cloakbrowser',
        browser_headless=False,
    )
    context = Context(quiet_console())
    context.create(str(tmp_path))

    assert context._driver_cache_key(profile) == ('cloakbrowser', False)


def test_context_driver_methods_delegate_to_driver_manager(tmp_path):
    class FakeDriverManager:
        def __init__(self):
            self.current_driver = None
            self.drivers = {('selenium', True): object()}
            self.ensure_calls = []
            self.get_calls = []
            self.init_calls = []
            self.cache_key_calls = []
            self.destroy_calls = 0

        def ensure_driver(self, source_or_class=None):
            self.ensure_calls.append(source_or_class)
            self.current_driver = object()
            return True

        def get_driver(self, source_or_class=None):
            self.get_calls.append(source_or_class)
            return self.drivers[('selenium', True)]

        def init_driver(self, source_or_class=None):
            self.init_calls.append(source_or_class)
            return True

        def driver_cache_key(self, source_or_class=None):
            self.cache_key_calls.append(source_or_class)
            return ('selenium', True)

        def destroy(self):
            self.destroy_calls += 1
            self.current_driver = None
            self.drivers.clear()

    context = Context(quiet_console())
    context.create(str(tmp_path))
    fake_driver_manager = FakeDriverManager()
    context.driver_manager = cast(Any, fake_driver_manager)
    source_marker: Any = object()

    assert context.ensure_driver(source_marker) is True
    assert context.get_driver(source_marker) is fake_driver_manager.drivers[('selenium', True)]
    assert context.init_driver(source_marker) is True
    assert context._driver_cache_key(source_marker) == ('selenium', True)
    assert context.driver is fake_driver_manager.current_driver
    assert context.drivers is fake_driver_manager.drivers

    context.destroy()

    assert fake_driver_manager.ensure_calls == [source_marker]
    assert fake_driver_manager.get_calls == [source_marker]
    assert fake_driver_manager.init_calls == [source_marker]
    assert fake_driver_manager.cache_key_calls == [source_marker]
    assert fake_driver_manager.destroy_calls == 1
    assert context.driver is None
    assert context.drivers == {}


def test_shell_uses_plain_stdin_for_interactive_prompt():
    assert Shell.use_rawinput is False


def test_source_url_matching_rejects_prefix_and_scheme_confusion():
    base_url = 'https://www.morui.com/manga'

    assert url_matches_base('https://www.morui.com/manga/123', base_url) is True
    assert url_matches_base('https://www.morui.com/mangaevil/123', base_url) is False
    assert url_matches_base('https://www.morui.com.evil.test/manga/123', base_url) is False
    assert url_matches_base('http://www.morui.com/manga/123', base_url) is False
    assert url_matches_base('not-a-url', base_url) is False


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

    def fake_ensure_driver(source_or_class=None):
        shell.context.driver = driver
        return True

    monkeypatch.setattr(shell.context, 'ensure_driver', fake_ensure_driver)

    try:
        assert shell._ensure_source_download_ready() is True
        assert source.driver is driver
    finally:
        shell.context.destroy()


def test_shell_source_instances_receive_profiles(tmp_path):
    runtime_config = RuntimeConfig(sources={'morui': SourceRuntimeConfig(browser_mode='requests')})
    shell = Shell(str(tmp_path), runtime_config=runtime_config)
    try:
        cast(Any, shell)._Shell__switch_source('morui')
        source = shell.sources['morui']

        assert source.profile is not None
        assert source.profile.browser_mode == 'requests'
        assert source.browser_mode == 'requests'
    finally:
        shell.context.destroy()


def test_shell_prompt_updates_when_source_switches(tmp_path):
    shell = Shell(str(tmp_path))
    try:
        cast(Any, shell)._Shell__switch_source('morui')

        assert shell.prompt == '动漫下载器[摩锐漫画]> '
    finally:
        shell.context.destroy()


def test_shell_source_display_names_resolve_to_chinese_not_code(tmp_path):
    """欢迎/选源界面必须展示中文显示名（读漫屋），而非源代码名（dumanwu）。"""
    shell = Shell(str(tmp_path))
    try:
        display_names = shell._source_display_names()

        assert len(display_names) == len(shell.source_options)
        # 源代码名（小写英文）不应出现在展示列表中
        for code_name in (
            'dumanwu',
            'manhuafree',
            'manhuagui',
            'manhuazhan',
            'morui',
            'thmh',
            'tuku',
        ):
            assert code_name not in display_names
        # 已知中文名应出现
        assert '摩锐漫画' in display_names
        assert '读漫屋' in display_names
    finally:
        shell.context.destroy()


def test_shell_source_views_expose_runtime_capabilities(tmp_path):
    runtime_config = RuntimeConfig(sources={'morui': SourceRuntimeConfig(browser_mode='requests')})
    shell = Shell(str(tmp_path), runtime_config=runtime_config)
    try:
        views = {view.source_name: view for view in shell._source_views()}

        assert views['morui'].display_name == '摩锐漫画'
        assert views['morui'].browser_mode == 'requests'
        assert views['morui'].search_uses_driver is False
        assert views['morui'].download_uses_driver is True
        assert views['morui'].selected is False
    finally:
        shell.context.destroy()


def test_shell_resolves_source_by_index_code_and_display_name(tmp_path):
    shell = Shell(str(tmp_path))
    try:
        first_source = shell.source_options[0]
        first_display_name = shell._source_display_name(first_source)

        assert shell._resolve_source_selection('1') == first_source
        assert shell._resolve_source_selection(first_source.upper()) == first_source
        assert shell._resolve_source_selection(first_display_name) == first_source
        assert shell._resolve_source_selection('999') is None
        assert shell._resolve_source_selection('不存在') is None
    finally:
        shell.context.destroy()


def test_shell_source_command_switches_directly_without_secondary_prompt(monkeypatch, tmp_path):
    shell = Shell(str(tmp_path))
    output = StringIO()
    shell.presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=120)
    )

    def fail_prompt(prompt: str) -> str:
        raise AssertionError(f'direct source selection should not prompt: {prompt}')

    monkeypatch.setattr(shell, '_read_prompt_line', fail_prompt)
    try:
        shell.do_source('morui')

        assert shell.current_source_name == 'morui'
        assert '已切换到 摩锐漫画 (morui)' in output.getvalue()
    finally:
        shell.context.destroy()


def test_shell_sources_command_renders_capability_catalog(tmp_path):
    shell = Shell(str(tmp_path))
    output = StringIO()
    shell.presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=120)
    )
    try:
        shell.do_sources('')

        rendered = output.getvalue()
        assert '动漫源' in rendered
        assert '页面加载' in rendered
        assert '搜索' in rendered
        assert '下载' in rendered
        assert '摩锐漫画' in rendered
    finally:
        shell.context.destroy()


def test_shell_check_without_selection_only_reads_cached_state(monkeypatch, tmp_path):
    shell = Shell(str(tmp_path))
    output = StringIO()
    shell.presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=120)
    )

    def fail_check(source_name: str) -> SourceVerification:
        raise AssertionError(f'check without selection must not access {source_name}')

    monkeypatch.setattr(shell, '_check_source', fail_check)
    try:
        shell.do_check('')

        rendered = output.getvalue()
        assert '未检查' in rendered
        assert 'check all' in rendered
        assert not shell.verification_store.store_path.exists()
    finally:
        shell.context.destroy()


def test_shell_check_persists_result_and_updates_source_catalog(monkeypatch, tmp_path):
    shell = Shell(str(tmp_path))
    output = StringIO()
    shell.presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=120)
    )
    result = SourceVerification(
        status='healthy',
        checked_at='2026-08-08T00:00:00+00:00',
        latency_seconds=0.125,
        http_status=200,
        message='HTTP 200，连接正常。',
        final_url='https://www.morui.com/',
    )
    monkeypatch.setattr(shell, '_check_source', lambda source_name: result)
    try:
        shell.do_check('morui')
        shell.do_sources('')

        rendered = output.getvalue()
        assert '来源检查 · 1 个结果' in rendered
        assert '正常 1 · 受限 0 · 不可用 0' in rendered
        assert '0.125s' in rendered
        assert '2026-08-08' in rendered
        assert shell.verification_store.load_all()['morui'] == result
        view = next(view for view in shell._source_views() if view.source_name == 'morui')
        assert view.verification_status == 'healthy'
        assert view.last_verified_at == '2026-08-08T00:00:00+00:00'
    finally:
        shell.context.destroy()


def test_shell_resolves_retry_tasks_by_index_id_and_all(tmp_path):
    shell = Shell(str(tmp_path))
    tasks = [
        DownloadTask(
            task_id='abc123def456',
            source_name='morui',
            volume_name='chapter-1',
            source_url='https://example.test/1',
            target_path='comic/book/chapter-1',
        ),
        DownloadTask(
            task_id='def456abc123',
            source_name='morui',
            volume_name='chapter-2',
            source_url='https://example.test/2',
            target_path='comic/book/chapter-2',
        ),
    ]
    try:
        assert shell._resolve_retry_tasks('all', tasks) == tasks
        assert shell._resolve_retry_tasks('2', tasks) == [tasks[1]]
        assert shell._resolve_retry_tasks('abc123', tasks) == [tasks[0]]
        assert shell._resolve_retry_tasks('9', tasks) is None
        assert shell._resolve_retry_tasks('unknown', tasks) is None
    finally:
        shell.context.destroy()


def test_shell_retry_command_executes_selected_tasks_and_renders_summary(monkeypatch, tmp_path):
    shell = Shell(str(tmp_path))
    output = StringIO()
    shell.presenter = TerminalPresenter(
        Console(file=output, force_terminal=False, color_system=None, width=120)
    )
    task = DownloadTask(
        task_id='abc123def456',
        source_name='morui',
        volume_name='chapter-1',
        source_url='https://example.test/1',
        target_path='comic/book/chapter-1',
    )

    class FakeTaskStore:
        def list_pending(self):
            return [task]

    shell.task_store = cast(Any, FakeTaskStore())
    monkeypatch.setattr(
        shell,
        '_retry_download_task',
        lambda selected: VolumeDownloadResult(
            name=selected.volume_name,
            url=selected.source_url,
            status='downloaded',
        ),
    )
    try:
        shell.do_retry('all')

        rendered = output.getvalue()
        assert '下载完成' in rendered
        assert '成功 1' in rendered
    finally:
        shell.context.destroy()


def test_context_destroy_suppresses_driver_cleanup_interrupt():
    class InterruptingDriver:
        def __init__(self):
            self.quit_calls = 0

        def quit(self):
            self.quit_calls += 1
            raise KeyboardInterrupt

    driver = InterruptingDriver()
    context = Context(quiet_console())
    context.create('download-output')
    context.driver = driver
    context.drivers[('selenium', True)] = driver

    context.destroy()

    assert driver.quit_calls == 1
    assert context.driver is None
    assert context.drivers == {}


def test_context_closes_driver_initialized_after_shutdown(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    ready = []

    class LateDriver:
        quit_calls = 0

        def quit(self):
            self.quit_calls += 1

    driver = LateDriver()

    def delayed_init(manager, source_or_class=None):
        started.set()
        assert release.wait(5)
        manager.current_driver = driver
        return True

    monkeypatch.setattr(DriverManager, 'init_driver', delayed_init)
    context = Context(quiet_console())
    context.create(str(tmp_path))
    worker = threading.Thread(target=lambda: ready.append(context.ensure_driver()))
    worker.start()
    try:
        assert started.wait(5)
        context.destroy()
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    assert ready == [False]
    assert driver.quit_calls == 1
    assert context.drivers == {}
    assert context.ensure_driver() is False
