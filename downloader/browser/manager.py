from __future__ import annotations

from typing import Any, Protocol

from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions

from downloader.browser.drivers import CloakBrowserDriver, SeleniumBaseDriver
from downloader.browser.modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, normalize_browser_mode
from downloader.comic import ComicSource
from downloader.sources.profiles import SourceProfile
from downloader.tui import ERROR, MUTED, SUCCESS


class DriverPresenter(Protocol):
    def print(self, message: Any = '', style: str | None = None) -> None: ...


class DriverManager:
    def __init__(self, presenter: DriverPresenter) -> None:
        self.presenter = presenter
        self.current_driver: Any | None = None
        self.drivers: dict[tuple[str, bool], Any] = {}

    def ensure_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        cache_key = self.driver_cache_key(source_or_class)
        driver = self.drivers.get(cache_key)
        if driver:
            self.current_driver = driver
            return True

        self.presenter.print('正在初始化浏览器驱动...', style=MUTED)
        if not self.init_driver(source_or_class):
            return False
        self.drivers[cache_key] = self.current_driver
        return True

    def get_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ):
        return self.drivers.get(self.driver_cache_key(source_or_class))

    def init_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        driver_mode = self._driver_mode_for_source(source_or_class)
        if driver_mode == CLOAKBROWSER_MODE:
            return self._try_init_cloakbrowser_driver(source_or_class)
        if driver_mode == SELENIUMBASE_MODE:
            return self._try_init_seleniumbase_driver(source_or_class)
        return self._try_init_selenium_driver()

    def _try_init_selenium_driver(self) -> bool:
        drivers = [
            ('Chrome', webdriver.Chrome, ChromeOptions),
            ('Firefox', webdriver.Firefox, FirefoxOptions),
            ('Edge', webdriver.Edge, EdgeOptions),
        ]

        for name, driver_cls, options_cls in drivers:
            if self._try_init_driver(name, driver_cls, options_cls):
                return True

        self.presenter.print(
            '所有浏览器驱动初始化失败，请确保已安装 Firefox/Chrome/Edge 及其对应驱动。',
            style=f'bold {ERROR}',
        )
        return False

    def _try_init_driver(self, name, driver_cls, options_cls) -> bool:
        try:
            options = options_cls()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1280,2000')
            if name == 'Chrome':
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')

            self.current_driver = driver_cls(options=options)
            self.presenter.print(f'已初始化 {name} 浏览器驱动', style=SUCCESS)
            return True
        except Exception as e:
            logger.debug('初始化 {driver_name} 驱动失败: {error}', driver_name=name, error=e)
            return False

    def _try_init_cloakbrowser_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None
    ) -> bool:
        try:
            self.current_driver = CloakBrowserDriver(
                headless=self._source_browser_headless(source_or_class),
                humanize=self._source_cloakbrowser_humanize(source_or_class),
                timeout_seconds=self._source_browser_wait_seconds(source_or_class),
                launch_options=self._source_cloakbrowser_options(source_or_class),
            )
            self.presenter.print('已初始化 CloakBrowser 浏览器驱动', style=SUCCESS)
            return True
        except Exception as e:
            logger.debug('初始化 CloakBrowser 驱动失败: {error}', error=e, exc_info=True)
            self.presenter.print(f'CloakBrowser 浏览器驱动初始化失败: {e}', style=f'bold {ERROR}')
            return False

    def _try_init_seleniumbase_driver(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None
    ) -> bool:
        try:
            self.current_driver = SeleniumBaseDriver(
                headless=self._source_browser_headless(source_or_class),
                timeout_seconds=self._source_browser_wait_seconds(source_or_class),
            )
            self.presenter.print('已初始化 SeleniumBase 浏览器会话', style=SUCCESS)
            return True
        except Exception as e:
            logger.debug('初始化 SeleniumBase 驱动失败: {error}', error=e, exc_info=True)
            self.presenter.print(f'SeleniumBase 浏览器会话初始化失败: {e}', style=f'bold {ERROR}')
            return False

    def driver_cache_key(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> tuple[str, bool]:
        driver_mode = self._driver_mode_for_source(source_or_class)
        if driver_mode in {CLOAKBROWSER_MODE, SELENIUMBASE_MODE}:
            return (driver_mode, self._source_browser_headless(source_or_class))
        return (driver_mode, True)

    def _driver_mode_for_source(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> str:
        profile = self._profile_for_source(source_or_class)
        if profile is not None:
            browser_mode = profile.browser_mode
        elif isinstance(source_or_class, type) and issubclass(source_or_class, ComicSource):
            browser_mode = source_or_class.configured_browser_mode()
        elif isinstance(source_or_class, ComicSource):
            browser_mode = source_or_class._source_browser_mode()
        else:
            browser_mode = normalize_browser_mode(None)
        if browser_mode in {CLOAKBROWSER_MODE, SELENIUMBASE_MODE}:
            return browser_mode
        return 'selenium'

    def _profile_for_source(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None
    ) -> SourceProfile | None:
        if isinstance(source_or_class, SourceProfile):
            return source_or_class
        profile = getattr(source_or_class, 'profile', None)
        return profile if isinstance(profile, SourceProfile) else None

    def _source_browser_headless(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        profile = self._profile_for_source(source_or_class)
        if profile is not None:
            if profile.browser_headless is not None:
                return bool(profile.browser_headless)
            if profile.seleniumbase_headless is not None:
                return bool(profile.seleniumbase_headless)
            return True
        browser_headless = getattr(source_or_class, 'browser_headless', None)
        if browser_headless is not None:
            return bool(browser_headless)
        seleniumbase_headless = getattr(source_or_class, 'seleniumbase_headless', None)
        if seleniumbase_headless is not None:
            return bool(seleniumbase_headless)
        return True

    def _source_browser_wait_seconds(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> float:
        profile = self._profile_for_source(source_or_class)
        if profile is not None:
            wait_seconds = profile.browser_wait_seconds
            if wait_seconds is None:
                wait_seconds = profile.seleniumbase_wait_seconds
            return float(30.0 if wait_seconds is None else wait_seconds)
        wait_seconds = getattr(source_or_class, 'browser_wait_seconds', None)
        if wait_seconds is None:
            wait_seconds = getattr(source_or_class, 'seleniumbase_wait_seconds', 30.0)
        return float(30.0 if wait_seconds is None else wait_seconds)

    def _source_cloakbrowser_humanize(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> bool:
        profile = self._profile_for_source(source_or_class)
        if profile is not None:
            return bool(profile.cloakbrowser_humanize)
        return bool(getattr(source_or_class, 'cloakbrowser_humanize', True))

    def _source_cloakbrowser_options(
        self, source_or_class: SourceProfile | ComicSource | type[ComicSource] | None = None
    ) -> dict[str, Any] | None:
        profile = self._profile_for_source(source_or_class)
        if profile is not None:
            options = profile.cloakbrowser_options
            return dict(options) if isinstance(options, dict) else None
        options = getattr(source_or_class, 'cloakbrowser_options', None)
        return dict(options) if isinstance(options, dict) else None

    def _quit_driver(self, driver) -> None:
        try:
            driver.quit()
        except KeyboardInterrupt as e:
            logger.debug('关闭浏览器驱动被中断: {error}', error=e)
        except Exception as e:
            logger.debug('关闭浏览器驱动失败: {error}', error=e)

    def destroy(self) -> None:
        for driver in set(self.drivers.values()):
            self._quit_driver(driver)
        self.drivers.clear()
        self.current_driver = None
