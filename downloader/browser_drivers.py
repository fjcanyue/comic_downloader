from __future__ import annotations

from typing import Any

try:
    from cloakbrowser import launch as cloakbrowser_launch
except ImportError:  # pragma: no cover - depends on optional runtime install
    cloakbrowser_launch = None


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
