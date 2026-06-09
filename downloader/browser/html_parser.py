from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import ExitStack
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from loguru import logger
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import SB

from downloader.browser.drivers import configure_seleniumbase_driver_cache
from downloader.browser.modes import (
    CLOAKBROWSER_MODE,
    REQUESTS_MODE,
    SELENIUMBASE_MODE,
    BrowserModeName,
    normalize_browser_mode,
)
from downloader.browser.page_loading import (
    PageLoadAdapters,
    PageLoader,
    PageLoadRequest,
    PageLoadResult,
)
from downloader.models import HtmlParseOptions

HTML_METHODS = {'GET', 'POST'}
HTML_MODE_METHODS: dict[str, BrowserModeName] = {
    REQUESTS_MODE.upper(): REQUESTS_MODE,
    SELENIUMBASE_MODE.upper(): SELENIUMBASE_MODE,
    CLOAKBROWSER_MODE.upper(): CLOAKBROWSER_MODE,
}
REQUESTS_TO_SELENIUMBASE_STATUS_CODES = {403, 429}
SELENIUMBASE_HTML_MAX_ATTEMPTS = 2
SELENIUMBASE_RETRY_BACKOFF_SECONDS = 3.0
SELENIUMBASE_DIAGNOSTIC_DIR = 'seleniumbase_diagnostics'
SELENIUMBASE_ERROR_CHAIN_LIMIT = 5
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


class HtmlParsingMixin:
    def parse_xpath_list(self, root, xpath, extract_map):
        """通用XPath列表解析方法

        Args:
            root: etree根元素
            xpath (str): XPath表达式
            extract_map (dict): 提取映射，如 {'name': './@title', 'url': './@href'}

        Returns:
            list: 提取的数据字典列表
        """
        results = []
        try:
            nodes = root.xpath(xpath)
            results.extend(self._extract_xpath_item(node, extract_map) for node in nodes)
        except Exception as e:
            self.logger.error('XPath解析失败: {xpath}, 错误: {error}', xpath=xpath, error=e)
        return results

    def _extract_xpath_item(self, node, extract_map):
        item = {}
        for key, expr in extract_map.items():
            item[key] = self._extract_xpath_value(node, key, expr)
        return item

    def _extract_xpath_value(self, node, key, expr):
        try:
            if expr.startswith('./@'):
                vals = node.xpath(expr)
                return (
                    vals[0].strip()
                    if vals and isinstance(vals[0], str)
                    else vals[0]
                    if vals
                    else None
                )
            if expr == './text()':
                return node.text.strip() if node.text else None
            vals = node.xpath(expr)
            if not vals:
                return None
            text_node = vals[0]
            if isinstance(text_node, str):
                return text_node.strip()
            return (
                text_node.text.strip()
                if hasattr(text_node, 'text') and text_node.text
                else text_node
            )
        except Exception as e:
            self.logger.debug('提取 {key} 时出错: {error}', key=key, error=e)
            return None

    def execute_js_safely(self, driver, js_code, fallback=None):
        """安全执行JavaScript代码

        Args:
            driver: Selenium WebDriver
            js_code (str): JS代码
            fallback: 默认返回值

        Returns:
            执行结果或fallback
        """
        try:
            # 简单验证JS代码，避免明显注入
            if not js_code or 'eval(' in js_code:
                self.logger.warning('潜在不安全JS代码: {js_code}', js_code=js_code)
                return fallback
            return driver.execute_script(js_code)
        except Exception as e:
            self.logger.error('JS执行失败: {js_code}, 错误: {error}', js_code=js_code, error=e)
            return fallback

    def _source_browser_mode(self) -> BrowserModeName:
        return normalize_browser_mode(self._source_profile_value('browser_mode', REQUESTS_MODE))

    def _source_profile_value(self, key: str, default: Any = None) -> Any:
        profile = getattr(self, 'profile', None)
        if profile is not None:
            return getattr(profile, key)
        return getattr(self, key, default)

    def _source_base_url(self) -> str:
        return str(self._source_profile_value('base_url', ''))

    def _browser_wait_selector(self) -> str | None:
        return self._source_profile_value(
            'browser_wait_selector', None
        ) or self._source_profile_value('seleniumbase_wait_selector', None)

    def _browser_wait_seconds(self) -> float:
        wait_seconds = self._source_profile_value('browser_wait_seconds', None)
        if wait_seconds is None:
            wait_seconds = self._source_profile_value('seleniumbase_wait_seconds', 0)
        return float(wait_seconds or 0)

    def _browser_headless(self, default: bool = True) -> bool:
        browser_headless = self._source_profile_value('browser_headless', None)
        if browser_headless is not None:
            return bool(browser_headless)
        seleniumbase_headless = self._source_profile_value('seleniumbase_headless', None)
        if seleniumbase_headless is not None:
            return bool(seleniumbase_headless)
        return default

    def _seleniumbase_context(self):
        configure_seleniumbase_driver_cache()
        headless = self._browser_headless(default=False)
        kwargs = {
            'uc': True,
            'test': True,
            'locale': 'zh-CN',
        }
        if headless:
            kwargs['headless'] = True
        else:
            kwargs['headed'] = True
        return SB(**kwargs)

    def _wait_for_seleniumbase_html(self, sb):
        wait_selector = self._browser_wait_selector()
        wait_seconds = self._browser_wait_seconds()
        if wait_selector:
            try:
                sb.cdp.find(
                    wait_selector,
                    timeout=wait_seconds,
                )
            except Exception as e:
                self.logger.debug(
                    'SeleniumBase 等待选择器超时: {selector}, 错误: {error}',
                    selector=wait_selector,
                    error=e,
                )
            return

        if wait_seconds > 0:
            sb.cdp.sleep(wait_seconds)

    def _wait_for_webdriver_html(self, driver) -> None:
        wait_selector = self._browser_wait_selector()
        wait_seconds = self._browser_wait_seconds()
        if wait_selector:
            try:
                if hasattr(driver, 'wait_for_selector'):
                    driver.wait_for_selector(wait_selector, timeout=wait_seconds)
                else:
                    WebDriverWait(driver, wait_seconds).until(
                        lambda current_driver: current_driver.find_elements(
                            By.CSS_SELECTOR, wait_selector
                        )
                    )
            except Exception as e:
                self.logger.debug(
                    'Browser wait selector timed out: {selector}, error: {error}',
                    selector=wait_selector,
                    error=e,
                )
            return

        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _parse_html_with_webdriver(self, url, mode_name: str):
        if self.driver is None:
            logger.error(
                '{mode_name} HTML parsing requires an initialized browser driver: {url}',
                mode_name=mode_name,
                url=url,
            )
            return None

        try:
            self.driver.get(url)
            self._wait_for_webdriver_html(self.driver)
            html = self._get_driver_page_source()
            if not html:
                logger.error(
                    '{mode_name} returned empty HTML: {url}',
                    mode_name=mode_name,
                    url=url,
                )
                return None
            return etree.parse(StringIO(html), self.parser)
        except Exception as e:
            logger.error(
                '{mode_name} HTML parsing failed: {url}, error: {error}',
                mode_name=mode_name,
                url=url,
                error=e,
                exc_info=True,
            )
            return None

    def _get_driver_page_source(self) -> str | None:
        page_source = getattr(self.driver, 'page_source', None)
        if isinstance(page_source, str):
            return page_source
        get_page_source = getattr(self.driver, 'get_page_source', None)
        if callable(get_page_source):
            html = get_page_source()
            return html if isinstance(html, str) else None
        return None

    def _active_seleniumbase_driver(self):
        if getattr(self.driver, 'is_seleniumbase_driver', False):
            return self.driver
        return None

    def _load_seleniumbase_html(self, sb, url: str):
        sb.activate_cdp_mode(url)
        sb.sleep(10)
        solve_captcha = getattr(sb, 'solve_captcha', None)
        if callable(solve_captcha):
            solve_captcha()
        sb.sleep(5)
        self._wait_for_seleniumbase_html(sb)
        html = self._get_seleniumbase_page_source(sb)
        return etree.parse(StringIO(html), self.parser)

    def _get_seleniumbase_page_source(self, sb) -> str:
        cdp = getattr(sb, 'cdp', None)
        if cdp is not None and hasattr(cdp, 'get_page_source'):
            html = cdp.get_page_source()
            if isinstance(html, str):
                return html
        get_page_source = getattr(sb, 'get_page_source', None)
        if callable(get_page_source):
            html = get_page_source()
            if isinstance(html, str):
                return html
        raise RuntimeError('SeleniumBase returned empty HTML.')

    def _seleniumbase_current_url(self, sb) -> str | None:
        get_current_url = getattr(sb, 'get_current_url', None)
        if callable(get_current_url):
            try:
                current_url = get_current_url()
                if isinstance(current_url, str) and current_url:
                    return current_url
            except Exception as e:
                logger.debug('Failed to read SeleniumBase current URL: {}', e)

        for target in (sb, getattr(sb, 'driver', None), getattr(sb, 'cdp', None)):
            if target is None:
                continue
            current_url = getattr(target, 'current_url', None)
            if isinstance(current_url, str) and current_url:
                return current_url
            url = getattr(target, 'url', None)
            if isinstance(url, str) and url:
                return url
        return None

    def _seleniumbase_diagnostic_base_path(self, url: str, attempt: int) -> Path:
        diagnostic_dir = Path(self.output_dir or '.') / SELENIUMBASE_DIAGNOSTIC_DIR
        diagnostic_dir.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r'[^A-Za-z0-9_-]+', '_', url.split('?', 1)[0]).strip('_')
        slug = slug[-80:] or 'page'
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:10]
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        unique_suffix = f'{time.time_ns() % 1_000_000_000:09d}'
        filename = f'{timestamp}-{unique_suffix}-attempt{attempt}-{slug}-{url_hash}'
        return diagnostic_dir / filename

    def _save_seleniumbase_page_source_diagnostic(self, sb, base_path: Path) -> str | None:
        try:
            html = self._get_seleniumbase_page_source(sb)
        except Exception as e:
            logger.debug('Failed to capture SeleniumBase page source: {}', e)
            return None

        html_path = base_path.with_suffix('.html')
        try:
            html_path.write_text(html, encoding='utf-8')
            return str(html_path)
        except Exception as e:
            logger.debug('Failed to write SeleniumBase page source diagnostic: {}', e)
            return None

    def _save_seleniumbase_screenshot_diagnostic(self, sb, base_path: Path) -> str | None:
        screenshot_path = base_path.with_suffix('.png')
        for target in (sb, getattr(sb, 'cdp', None), getattr(sb, 'driver', None)):
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
                except Exception as e:
                    logger.debug('Failed to capture SeleniumBase screenshot: {}', e)
                    continue
            except Exception as e:
                logger.debug('Failed to capture SeleniumBase screenshot: {}', e)
                continue

            if screenshot_path.exists():
                return str(screenshot_path)
        return None

    def _write_seleniumbase_diagnostic_metadata(
        self, base_path: Path, metadata: dict[str, Any]
    ) -> str | None:
        metadata_path = base_path.with_suffix('.json')
        try:
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            return str(metadata_path)
        except Exception as e:
            logger.debug('Failed to write SeleniumBase diagnostic metadata: {}', e)
            return None

    def _json_safe_error_arg(self, value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return repr(value)

    def _seleniumbase_error_chain(self, error: Exception) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        current: BaseException | None = error
        relation = 'error'
        seen_ids: set[int] = set()
        while (
            current is not None
            and id(current) not in seen_ids
            and len(chain) < SELENIUMBASE_ERROR_CHAIN_LIMIT
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

    def _seleniumbase_error_metadata(self, error: Exception) -> dict[str, Any]:
        return {
            'error_type': type(error).__name__,
            'error_module': type(error).__module__,
            'error_message': str(error),
            'error_args': [self._json_safe_error_arg(arg) for arg in error.args],
            'error_chain': self._seleniumbase_error_chain(error),
        }

    def _sanitize_proxy_environment_value(self, value: str) -> str:
        if '@' not in value:
            return value

        try:
            parsed = urlsplit(value)
            has_credentials = bool(parsed.username or parsed.password)
            if not has_credentials:
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

    def _record_seleniumbase_failure_diagnostics(
        self, sb, url: str, attempt: int, error: Exception
    ):
        try:
            base_path = self._seleniumbase_diagnostic_base_path(url, attempt)
            final_url = self._seleniumbase_current_url(sb)
            html_path = self._save_seleniumbase_page_source_diagnostic(sb, base_path)
            screenshot_path = self._save_seleniumbase_screenshot_diagnostic(sb, base_path)
            error_metadata = self._seleniumbase_error_metadata(error)
            metadata = {
                'attempt': attempt,
                'original_url': url,
                'final_url': final_url,
                'error': repr(error),
                **error_metadata,
                'proxy_environment': self._proxy_environment_metadata(),
                'html_path': html_path,
                'screenshot_path': screenshot_path,
            }
            metadata_path = self._write_seleniumbase_diagnostic_metadata(base_path, metadata)
            logger.warning(
                'SeleniumBase HTML attempt {} failed; original_url: {}; final_url: {}; '
                'metadata: {}; html: {}; screenshot: {}; error_type: {}; '
                'error_message: {}; error: {}',
                attempt,
                url,
                final_url or '<unknown>',
                metadata_path or '<unavailable>',
                html_path or '<unavailable>',
                screenshot_path or '<unavailable>',
                error_metadata['error_type'],
                error_metadata['error_message'] or '<empty>',
                error,
            )
        except Exception as diagnostic_error:
            logger.warning(
                'Failed to record SeleniumBase failure diagnostics: {}',
                diagnostic_error,
                exc_info=True,
            )

    def _parse_html_with_seleniumbase_attempt(self, url: str, attempt: int):
        driver = self._active_seleniumbase_driver()
        if driver is not None:
            try:
                return self._load_seleniumbase_html(driver, url)
            except Exception as e:
                self._record_seleniumbase_failure_diagnostics(driver, url, attempt, e)
                raise

        try:
            context = self._seleniumbase_context()
        except Exception as e:
            self._record_seleniumbase_failure_diagnostics(None, url, attempt, e)
            raise

        with ExitStack() as stack:
            try:
                sb = stack.enter_context(context)
            except Exception as e:
                self._record_seleniumbase_failure_diagnostics(context, url, attempt, e)
                raise

            try:
                return self._load_seleniumbase_html(sb, url)
            except Exception as e:
                self._record_seleniumbase_failure_diagnostics(sb, url, attempt, e)
                raise

    def _try_parse_html_with_seleniumbase_attempt(self, url: str, attempt: int):
        try:
            return self._parse_html_with_seleniumbase_attempt(url, attempt), None
        except Exception as e:
            return None, e

    def _parse_html_with_seleniumbase(self, url, method='GET'):
        if method.upper() != 'GET':
            logger.error('SeleniumBase CDP HTML 解析仅支持 GET 请求: {}', method)
            return None

        for attempt in range(1, SELENIUMBASE_HTML_MAX_ATTEMPTS + 1):
            root, error = self._try_parse_html_with_seleniumbase_attempt(url, attempt)
            if error is None:
                return root

            if attempt < SELENIUMBASE_HTML_MAX_ATTEMPTS:
                logger.warning(
                    'SeleniumBase CDP HTML attempt {}/{} failed; retrying in {}s: {}, error: {}',
                    attempt,
                    SELENIUMBASE_HTML_MAX_ATTEMPTS,
                    SELENIUMBASE_RETRY_BACKOFF_SECONDS,
                    url,
                    error,
                )
                time.sleep(SELENIUMBASE_RETRY_BACKOFF_SECONDS)
                continue

            logger.error(
                'SeleniumBase CDP 解析 HTML 页面失败: {}, 尝试次数: {}, 错误: {}',
                url,
                SELENIUMBASE_HTML_MAX_ATTEMPTS,
                error,
            )
            return None

        return None

    def _resolve_html_parse_options(self, method, data, encoding: str) -> HtmlParseOptions | None:
        method_name = str(method).upper()
        forced_mode = HTML_MODE_METHODS.get(method_name)
        if forced_mode:
            return HtmlParseOptions(forced_mode, 'GET', encoding)
        if method_name in HTML_METHODS:
            return HtmlParseOptions(self._source_browser_mode(), method_name, encoding)
        if data is None and encoding == 'utf-8':
            return HtmlParseOptions(self._source_browser_mode(), 'GET', str(method))

        logger.error('Unsupported HTTP method: {}', method)
        return None

    def _parse_html_with_requests(self, url, method, data, encoding, headers):
        request_headers = {'referer': self._source_base_url()}
        if headers:
            request_headers.update(headers)

        try:
            if method == 'GET':
                r = self.http.get(url, timeout=30, headers=request_headers)
            else:
                r = self.http.post(url, data=data, timeout=30, headers=request_headers)
            status_code = getattr(r, 'status_code', None)
            if (
                isinstance(status_code, int)
                and status_code in REQUESTS_TO_SELENIUMBASE_STATUS_CODES
            ):
                return self._switch_requests_html_to_seleniumbase(url, method, status_code)
            r.raise_for_status()
            r.encoding = encoding
            return etree.parse(StringIO(r.text), self.parser)
        except requests.exceptions.HTTPError as e:
            response = getattr(e, 'response', None)
            status_code = getattr(response, 'status_code', None)
            if (
                isinstance(status_code, int)
                and status_code in REQUESTS_TO_SELENIUMBASE_STATUS_CODES
            ):
                return self._switch_requests_html_to_seleniumbase(url, method, status_code)
            logger.error(
                'HTML request failed: {}, method: {}, error: {}',
                url,
                method,
                e,
                exc_info=True,
            )
            return None
        except requests.exceptions.RequestException as e:
            logger.error(
                'HTML request failed: {}, method: {}, error: {}',
                url,
                method,
                e,
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error('HTML parsing failed: {}, error: {}', url, e, exc_info=True)
            return None

    def _switch_requests_html_to_seleniumbase(self, url, method, status_code: int):
        logger.warning(
            'Requests mode returned HTTP {}; retrying with temporary SeleniumBase mode: {}',
            status_code,
            url,
        )
        return self._parse_html_with_seleniumbase(url, method)

    def __parse_html__(
        self,
        url,
        method='GET',
        data=None,
        encoding='utf-8',
        headers=None,
    ):
        """解析HTML

        Args:
            url (str): 动漫卷/话URL地址
            method (str): HTTP方法
            data (dict): POST数据
            encoding (str): 编码
            headers (dict): 请求头

        Returns:
            array: 根元素
        """
        self.logger.debug('开始解析HTML: {url}, 方法: {method}', url=url, method=method)

        options = self._resolve_html_parse_options(method, data, encoding)
        if options is None:
            return None

        request = PageLoadRequest(
            url=url,
            base_url=self._source_base_url(),
            browser_mode=options.browser_mode,
            method=options.http_method,
            data=data,
            encoding=options.encoding,
            headers=headers,
            wait_selector=self._browser_wait_selector(),
            wait_seconds=self._browser_wait_seconds(),
            diagnostics_dir=Path(self.output_dir or '.') / SELENIUMBASE_DIAGNOSTIC_DIR,
        )
        result = self._load_page_for_legacy_parse_html(request)
        self.last_page_load_result = result
        return result.root if result.ok else None

    def _load_page_for_legacy_parse_html(self, request: PageLoadRequest) -> PageLoadResult:
        loader = getattr(self, 'page_loader', None)
        if loader is None:
            loader = PageLoader()
            self.page_loader = loader

        adapters = self._page_load_adapters()
        result = loader.load(request, adapters)
        if result.failure_reason != 'browser_adapter_required':
            return result
        if result.required_browser_mode != SELENIUMBASE_MODE:
            return result
        return self._load_with_temporary_seleniumbase_context(request, loader)

    def _load_with_temporary_seleniumbase_context(
        self, request: PageLoadRequest, loader: PageLoader
    ) -> PageLoadResult:
        retry_request = replace(request, browser_mode=SELENIUMBASE_MODE)
        last_result = PageLoadResult(
            failure_reason='browser_adapter_required',
            required_browser_mode=SELENIUMBASE_MODE,
            recoverable=True,
        )

        for attempt in range(1, SELENIUMBASE_HTML_MAX_ATTEMPTS + 1):
            context = self._seleniumbase_context()
            with ExitStack() as stack:
                try:
                    seleniumbase_browser = stack.enter_context(context)
                except Exception as e:
                    last_result = loader.browser_failure_result(
                        retry_request,
                        context,
                        e,
                        SELENIUMBASE_MODE,
                        attempt=attempt,
                    )
                else:
                    retry_adapters = self._page_load_adapters()
                    retry_adapters.browsers[SELENIUMBASE_MODE] = seleniumbase_browser
                    last_result = loader.load(retry_request, retry_adapters)

            if last_result.ok:
                return last_result
            if attempt < SELENIUMBASE_HTML_MAX_ATTEMPTS:
                time.sleep(SELENIUMBASE_RETRY_BACKOFF_SECONDS)

        return last_result

    def _page_load_adapters(self) -> PageLoadAdapters:
        browsers = {}
        if self.driver is not None:
            if getattr(self.driver, 'is_seleniumbase_driver', False):
                browsers[SELENIUMBASE_MODE] = self.driver
            elif self._source_browser_mode() == CLOAKBROWSER_MODE:
                browsers[CLOAKBROWSER_MODE] = self.driver
        return PageLoadAdapters(http=self.http, browsers=browsers)
