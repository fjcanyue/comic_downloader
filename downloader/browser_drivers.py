from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

import requests
from seleniumbase import SB
from seleniumbase.core import browser_launcher as sb_browser_launcher

try:
    from cloakbrowser import launch as cloakbrowser_launch
except ImportError:  # pragma: no cover - depends on optional runtime install
    cloakbrowser_launch = None


def _user_cache_root() -> Path:
    if sys.platform == 'win32':
        cache_root = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if cache_root:
            return Path(cache_root)
        return Path.home() / 'AppData' / 'Local'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches'
    cache_root = os.environ.get('XDG_CACHE_HOME')
    if cache_root:
        return Path(cache_root)
    return Path.home() / '.cache'


def _packaged_seleniumbase_driver_dir() -> Path:
    return _user_cache_root() / 'comic_downloader' / 'seleniumbase' / 'drivers'


def configure_seleniumbase_driver_cache() -> None:
    if not getattr(sys, 'frozen', False):
        return

    settings = getattr(sb_browser_launcher.sb_config, 'settings', None)
    existing_dir = getattr(settings, 'NEW_DRIVER_DIR', None)
    if existing_dir:
        return

    driver_dir = _packaged_seleniumbase_driver_dir()
    driver_dir.mkdir(parents=True, exist_ok=True)
    sb_browser_launcher.override_driver_dir(str(driver_dir))


class CloakBrowserDriver:
    """Small WebDriver-shaped adapter around CloakBrowser's Playwright API."""

    def __init__(
        self,
        *,
        headless: bool,
        humanize: bool,
        timeout_seconds: float,
        launch_options: dict[str, Any] | None = None,
    ) -> None:
        if cloakbrowser_launch is None:
            raise RuntimeError(
                'CloakBrowser mode requires the "cloakbrowser" package to be installed.'
            )

        options = dict(launch_options or {})
        options.setdefault('geoip', True)
        options.setdefault('headless', False)
        options.setdefault('humanize', True)

        self._browser = cloakbrowser_launch(**options)
        self._page = self._browser.new_page()
        self._timeout_ms = self._to_timeout_ms(timeout_seconds)

    def get(self, url: str) -> None:
        self._page.goto(url, wait_until='domcontentloaded', timeout=self._timeout_ms)

    def execute_script(self, js_code: str):
        return self._page.evaluate(f'() => {{ {js_code} }}')

    @property
    def page_source(self) -> str:
        return self._page.content()

    def wait_for_selector(self, selector: str, timeout: float | None = None) -> None:
        self._page.wait_for_selector(selector, timeout=self._to_timeout_ms(timeout))

    def implicitly_wait(self, seconds: float) -> None:
        self._timeout_ms = self._to_timeout_ms(seconds)

    def quit(self) -> None:
        self._browser.close()

    @staticmethod
    def _to_timeout_ms(seconds: float | None) -> int:
        if seconds is None:
            return 30_000
        return max(1, int(seconds * 1000))


class SeleniumBaseDriver:
    """Persistent SeleniumBase session with a WebDriver-shaped surface."""

    is_seleniumbase_driver = True

    def __init__(self, *, headless: bool, timeout_seconds: float) -> None:
        configure_seleniumbase_driver_cache()
        kwargs: dict[str, Any] = {
            'uc': True,
            'locale': 'zh-CN',
        }
        if headless:
            kwargs['headless'] = True
        else:
            kwargs['headed'] = True

        self._context = SB(**kwargs)
        self._sb = self._context.__enter__()
        self._timeout_seconds = timeout_seconds
        self._closed = False

    @property
    def cdp(self):
        return getattr(self._sb, 'cdp', None)

    def activate_cdp_mode(self, url: str) -> None:
        if self._navigate_active_cdp(url):
            return
        self._sb.activate_cdp_mode(url)

    def _navigate_active_cdp(self, url: str) -> bool:
        cdp = self.cdp
        if cdp is None:
            return False
        for method_name in ('get', 'open', 'goto'):
            navigate = getattr(cdp, method_name, None)
            if callable(navigate):
                navigate(url)
                return True
        return False

    def get(self, url: str) -> None:
        self.activate_cdp_mode(url)
        self.sleep(10)
        self.solve_captcha()
        self.sleep(5)

    def sleep(self, seconds: float) -> None:
        self._sb.sleep(seconds)

    def solve_captcha(self) -> None:
        solve_captcha = getattr(self._sb, 'solve_captcha', None)
        if callable(solve_captcha):
            solve_captcha()

    def execute_script(self, js_code: str):
        cdp = self.cdp
        if cdp is not None and hasattr(cdp, 'evaluate'):
            return cdp.evaluate(js_code)
        return self._sb.execute_script(js_code)

    @property
    def page_source(self) -> str:
        return self.get_page_source()

    def get_page_source(self) -> str:
        cdp = self.cdp
        if cdp is not None and hasattr(cdp, 'get_page_source'):
            return cdp.get_page_source()
        return self._sb.get_page_source()

    def wait_for_selector(self, selector: str, timeout: float | None = None) -> None:
        cdp = self.cdp
        if cdp is not None and hasattr(cdp, 'find'):
            cdp.find(selector, timeout=timeout or self._timeout_seconds)
            return
        self._sb.wait_for_element_present(selector, timeout=timeout or self._timeout_seconds)

    def implicitly_wait(self, seconds: float) -> None:
        driver = getattr(self._sb, 'driver', None)
        if driver is not None and hasattr(driver, 'implicitly_wait'):
            driver.implicitly_wait(seconds)

    def download_to_file(self, url: str, file_path: str, *, referer: str | None = None) -> None:
        try:
            data = self._download_bytes_with_cdp_fetch(url)
            with open(file_path, 'wb') as f:
                f.write(data)
            return
        except Exception:
            self._download_with_browser_session(url, file_path, referer=referer)

    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._quit_managed_driver()
        self._mark_seleniumbase_teardown_done()
        self._exit_context()

    def _quit_managed_driver(self) -> None:
        driver = getattr(self._sb, 'driver', None)
        if driver is None:
            return

        with suppress(Exception):
            driver._already_quit = True

        quit_driver = getattr(driver, 'quit', None)
        if callable(quit_driver):
            try:
                with suppress(Exception):
                    quit_driver()
            except KeyboardInterrupt:
                return

    def _mark_seleniumbase_teardown_done(self) -> None:
        with suppress(Exception):
            self._sb._BaseCase__called_teardown = True

    def _exit_context(self) -> None:
        try:
            with suppress(Exception):
                self._context.__exit__(None, None, None)
        except KeyboardInterrupt:
            return

    def _download_bytes_with_cdp_fetch(self, url: str) -> bytes:
        cdp = self.cdp
        if cdp is None or not hasattr(cdp, 'evaluate'):
            raise RuntimeError('SeleniumBase CDP mode is not active.')

        expression = f"""
        (async () => {{
            const response = await fetch({json.dumps(url)}, {{
                credentials: 'include',
                cache: 'no-store'
            }});
            if (!response.ok) {{
                throw new Error(`HTTP ${{response.status}}`);
            }}
            const buffer = await response.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            const chunkSize = 0x8000;
            let binary = '';
            for (let i = 0; i < bytes.length; i += chunkSize) {{
                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
            }}
            return btoa(binary);
        }})()
        """
        encoded = cdp.evaluate(expression)
        if not isinstance(encoded, str):
            raise RuntimeError('SeleniumBase CDP fetch did not return image bytes.')
        return base64.b64decode(encoded)

    def _download_with_browser_session(
        self, url: str, file_path: str, *, referer: str | None = None
    ) -> None:
        headers = {
            'User-Agent': self._user_agent(),
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        }
        if referer:
            headers['Referer'] = referer

        with requests.Session() as session:
            self._copy_browser_cookies_to(session)
            with session.get(url, headers=headers, timeout=30, stream=True) as response:
                response.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)

    def _user_agent(self) -> str:
        default_user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
        )
        get_user_agent = getattr(self._sb, 'get_user_agent', None)
        if callable(get_user_agent):
            try:
                user_agent = get_user_agent()
                if isinstance(user_agent, str) and user_agent:
                    return user_agent
            except Exception:
                return default_user_agent
        return default_user_agent

    def _copy_browser_cookies_to(self, session: requests.Session) -> None:
        for cookie in self._browser_cookies():
            name = self._cookie_value(cookie, 'name')
            value = self._cookie_value(cookie, 'value')
            if not name or value is None:
                continue
            domain = self._cookie_value(cookie, 'domain')
            path = self._cookie_value(cookie, 'path') or '/'
            if domain:
                session.cookies.set(name, value, domain=domain, path=path)
            else:
                session.cookies.set(name, value, path=path)

    def _browser_cookies(self) -> list[Any]:
        cdp = self.cdp
        if cdp is not None and hasattr(cdp, 'get_all_cookies'):
            try:
                cookies = cdp.get_all_cookies()
                return list(cookies or [])
            except Exception:
                return self._webdriver_cookies()
        return self._webdriver_cookies()

    def _webdriver_cookies(self) -> list[Any]:
        get_cookies = getattr(self._sb, 'get_cookies', None)
        if callable(get_cookies):
            try:
                return list(get_cookies() or [])
            except Exception:
                return []
        return []

    @staticmethod
    def _cookie_value(cookie: Any, key: str, default: Any = None) -> Any:
        if isinstance(cookie, dict):
            return cookie.get(key, default)
        return getattr(cookie, key, default)
