from __future__ import annotations

from typing import Any

from downloader.browser.manager import DriverManager
from downloader.comic import ComicSource
from downloader.sources.profiles import SourceProfile


class QuietPresenter:
    def __init__(self) -> None:
        self.messages: list[tuple[Any, str | None]] = []

    def print(self, message: Any = '', style: str | None = None) -> None:
        self.messages.append((message, style))


class SeleniumBaseBackedSource(ComicSource):
    browser_mode = 'seleniumbase'
    browser_headless = False

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_driver_manager_starts_without_initializing_driver():
    manager = DriverManager(QuietPresenter())

    assert manager.current_driver is None
    assert manager.drivers == {}


def test_driver_manager_ensure_driver_initializes_once(monkeypatch):
    driver = object()
    calls = []

    def fake_init_driver(self, source_or_class=None):
        calls.append(source_or_class)
        self.current_driver = driver
        return True

    monkeypatch.setattr(DriverManager, 'init_driver', fake_init_driver)

    manager = DriverManager(QuietPresenter())

    assert manager.ensure_driver(SeleniumBaseBackedSource) is True
    assert manager.ensure_driver(SeleniumBaseBackedSource) is True
    assert manager.current_driver is driver
    assert calls == [SeleniumBaseBackedSource]


def test_driver_manager_cache_key_uses_profile_browser_mode_and_headless():
    profile = SourceProfile(
        source_name='profiled',
        class_name='ProfiledSource',
        enabled=True,
        deprecated=False,
        browser_mode='cloakbrowser',
        browser_headless=False,
    )
    manager = DriverManager(QuietPresenter())

    assert manager.driver_cache_key(profile) == ('cloakbrowser', False)


def test_driver_manager_initializes_seleniumbase_for_seleniumbase_mode(monkeypatch):
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

    manager = DriverManager(QuietPresenter())

    assert manager.ensure_driver(SeleniumBaseBackedSource) is True
    assert manager.current_driver is driver
    assert calls == [SeleniumBaseBackedSource]


def test_driver_manager_destroy_closes_cached_drivers():
    class Driver:
        def __init__(self):
            self.quit_calls = 0

        def quit(self):
            self.quit_calls += 1

    driver = Driver()
    manager = DriverManager(QuietPresenter())
    manager.current_driver = driver
    manager.drivers[('selenium', True)] = driver

    manager.destroy()

    assert driver.quit_calls == 1
    assert manager.current_driver is None
    assert manager.drivers == {}


def test_driver_manager_destroy_suppresses_driver_cleanup_interrupt():
    class InterruptingDriver:
        def __init__(self):
            self.quit_calls = 0

        def quit(self):
            self.quit_calls += 1
            raise KeyboardInterrupt

    driver = InterruptingDriver()
    manager = DriverManager(QuietPresenter())
    manager.current_driver = driver
    manager.drivers[('selenium', True)] = driver

    manager.destroy()

    assert driver.quit_calls == 1
    assert manager.current_driver is None
    assert manager.drivers == {}
