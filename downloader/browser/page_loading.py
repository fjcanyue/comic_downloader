from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser.modes import CLOAKBROWSER_MODE, SELENIUMBASE_MODE, BrowserModeName

BLOCK_FALLBACK_STATUS_CODES = {403, 429}
ERROR_CHAIN_LIMIT = 5
PROXY_ENVIRONMENT_KEYS = (
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'NO_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
    'no_proxy',
)


@dataclass(frozen=True)
class PageLoadRequest:
    url: str
    base_url: str
    browser_mode: BrowserModeName
    method: str = 'GET'
    data: Any = None
    encoding: str = 'utf-8'
    headers: dict[str, str] | None = None
    wait_selector: str | None = None
    wait_seconds: float = 0
    diagnostics_dir: str | Path | None = None


@dataclass(frozen=True)
class PageLoadAdapters:
    http: Any
    browsers: dict[BrowserModeName, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageLoadResult:
    root: Any = None
    failure_reason: str | None = None
    error_message: str | None = None
    status_code: int | None = None
    required_browser_mode: BrowserModeName | None = None
    recoverable: bool = False
    browser_mode: BrowserModeName | None = None
    diagnostic_paths: dict[str, str | None] | None = None

    @property
    def ok(self) -> bool:
        return self.root is not None and self.failure_reason is None


class PageLoader:
    def __init__(self) -> None:
        self.parser = etree.HTMLParser()

    def load(self, request: PageLoadRequest, adapters: PageLoadAdapters) -> PageLoadResult:
        if request.browser_mode == SELENIUMBASE_MODE:
            return self._load_with_seleniumbase(request, adapters.browsers.get(SELENIUMBASE_MODE))
        if request.browser_mode == CLOAKBROWSER_MODE:
            return self._load_with_webdriver(
                request,
                adapters.browsers.get(CLOAKBROWSER_MODE),
                CLOAKBROWSER_MODE,
            )

        method = request.method.upper()
        request_headers = {'referer': request.base_url}
        if request.headers:
            request_headers.update(request.headers)

        if method == 'POST':
            response = adapters.http.post(
                request.url,
                data=request.data,
                timeout=30,
                headers=request_headers,
            )
        else:
            response = adapters.http.get(
                request.url,
                timeout=30,
                headers=request_headers,
            )
        status_code = getattr(response, 'status_code', None)
        if (
            method != 'GET'
            and isinstance(status_code, int)
            and status_code in BLOCK_FALLBACK_STATUS_CODES
        ):
            return PageLoadResult(
                failure_reason='unsupported_fallback_method',
                status_code=status_code,
                recoverable=False,
            )
        if (
            method == 'GET'
            and isinstance(status_code, int)
            and status_code in BLOCK_FALLBACK_STATUS_CODES
        ):
            browser = adapters.browsers.get(SELENIUMBASE_MODE)
            if browser is not None:
                return self._load_with_seleniumbase(request, browser)
            return PageLoadResult(
                failure_reason='browser_adapter_required',
                status_code=status_code,
                required_browser_mode=SELENIUMBASE_MODE,
                recoverable=True,
            )
        response.raise_for_status()
        response.encoding = request.encoding
        return PageLoadResult(
            root=etree.parse(StringIO(response.text), self.parser),
            browser_mode=request.browser_mode,
        )

    def _load_with_seleniumbase(self, request: PageLoadRequest, browser: Any) -> PageLoadResult:
        if browser is None:
            return PageLoadResult(
                failure_reason='browser_adapter_required',
                required_browser_mode=SELENIUMBASE_MODE,
                recoverable=True,
            )
        try:
            browser.activate_cdp_mode(request.url)
            browser.sleep(10)
            solve_captcha = getattr(browser, 'solve_captcha', None)
            if callable(solve_captcha):
                solve_captcha()
            browser.sleep(5)
            self._wait_for_seleniumbase(request, browser)
            html = self._seleniumbase_page_source(browser)
            return PageLoadResult(
                root=etree.parse(StringIO(html), self.parser),
                browser_mode=SELENIUMBASE_MODE,
            )
        except Exception as e:
            return self.browser_failure_result(request, browser, e, SELENIUMBASE_MODE)

    def _load_with_webdriver(
        self, request: PageLoadRequest, browser: Any, browser_mode: BrowserModeName
    ) -> PageLoadResult:
        if browser is None:
            return PageLoadResult(
                failure_reason='browser_adapter_required',
                required_browser_mode=browser_mode,
                recoverable=True,
            )
        if request.method.upper() != 'GET':
            return PageLoadResult(
                failure_reason='unsupported_browser_method',
                required_browser_mode=browser_mode,
                recoverable=False,
            )
        try:
            browser.get(request.url)
            self._wait_for_webdriver(request, browser)
            html = self._webdriver_page_source(browser)
            return PageLoadResult(
                root=etree.parse(StringIO(html), self.parser),
                browser_mode=browser_mode,
            )
        except Exception as e:
            return self.browser_failure_result(request, browser, e, browser_mode)

    def browser_failure_result(
        self,
        request: PageLoadRequest,
        browser: Any,
        error: Exception,
        browser_mode: BrowserModeName,
        *,
        attempt: int = 1,
    ) -> PageLoadResult:
        diagnostic_paths = self._record_browser_failure_diagnostics(
            browser, request, error, attempt
        )
        return PageLoadResult(
            failure_reason='browser_load_failed',
            error_message=str(error),
            required_browser_mode=browser_mode,
            browser_mode=browser_mode,
            diagnostic_paths=diagnostic_paths,
        )

    def _wait_for_webdriver(self, request: PageLoadRequest, browser: Any) -> None:
        if request.wait_selector:
            wait_for_selector = getattr(browser, 'wait_for_selector', None)
            if callable(wait_for_selector):
                wait_for_selector(request.wait_selector, timeout=request.wait_seconds)
            return
        if request.wait_seconds > 0:
            time.sleep(request.wait_seconds)

    def _webdriver_page_source(self, browser: Any) -> str:
        page_source = getattr(browser, 'page_source', None)
        if isinstance(page_source, str):
            return page_source
        get_page_source = getattr(browser, 'get_page_source', None)
        if callable(get_page_source):
            html = get_page_source()
            if isinstance(html, str):
                return html
        raise RuntimeError('Browser returned empty HTML.')

    def _wait_for_seleniumbase(self, request: PageLoadRequest, browser: Any) -> None:
        if request.wait_selector:
            browser.cdp.find(request.wait_selector, timeout=request.wait_seconds)
        elif request.wait_seconds > 0:
            browser.sleep(request.wait_seconds)

    def _seleniumbase_page_source(self, browser: Any) -> str:
        cdp = getattr(browser, 'cdp', None)
        if cdp is not None and hasattr(cdp, 'get_page_source'):
            html = cdp.get_page_source()
            if isinstance(html, str):
                return html
        get_page_source = getattr(browser, 'get_page_source', None)
        if callable(get_page_source):
            html = get_page_source()
            if isinstance(html, str):
                return html
        raise RuntimeError('SeleniumBase returned empty HTML.')

    def _record_browser_failure_diagnostics(
        self, browser: Any, request: PageLoadRequest, error: Exception, attempt: int
    ) -> dict[str, str | None]:
        base_path = self._diagnostic_base_path(request)
        html_path = self._save_page_source_diagnostic(browser, base_path)
        screenshot_path = self._save_screenshot_diagnostic(browser, base_path)
        metadata = {
            'attempt': attempt,
            'original_url': request.url,
            'final_url': self._browser_current_url(browser),
            'error_type': type(error).__name__,
            'error_module': type(error).__module__,
            'error_message': str(error),
            'error_args': [self._json_safe_error_arg(arg) for arg in error.args],
            'error_chain': self._error_chain(error),
            'error': repr(error),
            'proxy_environment': self._proxy_environment_metadata(),
            'html_path': html_path,
            'screenshot_path': screenshot_path,
        }
        metadata_path = self._write_metadata_diagnostic(base_path, metadata)
        return {
            'html': html_path,
            'screenshot': screenshot_path,
            'metadata': metadata_path,
        }

    def _diagnostic_base_path(self, request: PageLoadRequest) -> Path:
        diagnostic_dir = Path(request.diagnostics_dir or 'seleniumbase_diagnostics')
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^A-Za-z0-9_-]+', '_', request.url.split('?', 1)[0]).strip('_')
        slug = slug[-80:] or 'page'
        url_hash = hashlib.sha256(request.url.encode('utf-8')).hexdigest()[:10]
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        unique_suffix = f'{time.time_ns() % 1_000_000_000:09d}'
        return diagnostic_dir / f'{timestamp}-{unique_suffix}-{slug}-{url_hash}'

    def _save_page_source_diagnostic(self, browser: Any, base_path: Path) -> str | None:
        try:
            html = self._seleniumbase_page_source(browser)
        except Exception:
            return None
        html_path = base_path.with_suffix('.html')
        html_path.write_text(html, encoding='utf-8')
        return str(html_path)

    def _save_screenshot_diagnostic(self, browser: Any, base_path: Path) -> str | None:
        screenshot_path = base_path.with_suffix('.png')
        for target in (browser, getattr(browser, 'cdp', None), getattr(browser, 'driver', None)):
            if target is None:
                continue
            save_screenshot = getattr(target, 'save_screenshot', None)
            if not callable(save_screenshot):
                continue
            try:
                save_screenshot(screenshot_path.name, folder=str(screenshot_path.parent))
            except TypeError:
                try:
                    save_screenshot(str(screenshot_path))
                except Exception:  # noqa: S112
                    continue
            except Exception:  # noqa: S112
                continue
            if screenshot_path.exists():
                return str(screenshot_path)
        return None

    def _write_metadata_diagnostic(self, base_path: Path, metadata: dict[str, Any]) -> str:
        metadata_path = base_path.with_suffix('.json')
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        return str(metadata_path)

    def _browser_current_url(self, browser: Any) -> str | None:
        get_current_url = getattr(browser, 'get_current_url', None)
        if callable(get_current_url):
            current_url = get_current_url()
            if isinstance(current_url, str) and current_url:
                return current_url
        for target in (browser, getattr(browser, 'driver', None), getattr(browser, 'cdp', None)):
            if target is None:
                continue
            current_url = getattr(target, 'current_url', None)
            if isinstance(current_url, str) and current_url:
                return current_url
            url = getattr(target, 'url', None)
            if isinstance(url, str) and url:
                return url
        return None

    def _proxy_environment_metadata(self) -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        for key in PROXY_ENVIRONMENT_KEYS:
            value = os.environ.get(key)
            if value is None:
                metadata[key] = {'set': False}
            else:
                metadata[key] = {
                    'set': True,
                    'value': self._sanitize_proxy_environment_value(value),
                }
        return metadata

    def _sanitize_proxy_environment_value(self, value: str) -> str:
        if '@' not in value:
            return value
        try:
            parsed = urlsplit(value)
            if not (parsed.username or parsed.password):
                return '<redacted proxy value>'
            hostname = parsed.hostname or ''
            try:
                port = f':{parsed.port}' if parsed.port is not None else ''
            except ValueError:
                port = ''
            netloc = f'<credentials>@{hostname}{port}'
            return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        except Exception:
            return '<redacted proxy value>'

    def _json_safe_error_arg(self, value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return repr(value)

    def _error_chain(self, error: Exception) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        current: BaseException | None = error
        relation = 'error'
        seen_ids: set[int] = set()
        while (
            current is not None and id(current) not in seen_ids and len(chain) < ERROR_CHAIN_LIMIT
        ):
            seen_ids.add(id(current))
            chain.append(
                {
                    'relation': relation,
                    'type': type(current).__name__,
                    'module': type(current).__module__,
                    'message': str(current),
                    'repr': repr(current),
                    'args': [self._json_safe_error_arg(arg) for arg in current.args],
                }
            )
            if current.__cause__ is not None:
                relation = 'cause'
                current = current.__cause__
            elif current.__context__ is not None and not current.__suppress_context__:
                relation = 'context'
                current = current.__context__
            else:
                current = None
        return chain
