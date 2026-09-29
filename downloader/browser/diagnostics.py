from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

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


class SeleniumBaseDiagnosticsMixin:
    output_dir: str

    if TYPE_CHECKING:

        def _get_seleniumbase_page_source(self, sb: Any) -> str: ...

        def _seleniumbase_current_url(self, sb: Any) -> str | None: ...

    def _seleniumbase_diagnostic_base_path(self, url: str, attempt: int) -> Path:
        diagnostic_dir = Path(self.output_dir or '.') / SELENIUMBASE_DIAGNOSTIC_DIR
        diagnostic_dir.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r'[^A-Za-z0-9_-]+', '_', url.split('?', 1)[0]).strip('_')
        slug = slug[-80:] or 'page'
        url_hash = hashlib.sha256(url.encode('utf-8'), usedforsecurity=False).hexdigest()[:10]
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        unique_suffix = f'{time.time_ns() % 1_000_000_000:09d}'
        filename = f'{timestamp}-{unique_suffix}-attempt{attempt}-{slug}-{url_hash}'
        return diagnostic_dir / filename

    def _save_seleniumbase_page_source_diagnostic(self, sb: Any, base_path: Path) -> str | None:
        try:
            html = self._get_seleniumbase_page_source(sb)
        except Exception as exc:
            logger.debug('Failed to capture SeleniumBase page source: {}', exc)
            return None

        html_path = base_path.with_suffix('.html')
        try:
            html_path.write_text(html, encoding='utf-8')
            return str(html_path)
        except Exception as exc:
            logger.debug('Failed to write SeleniumBase page source diagnostic: {}', exc)
            return None

    def _save_seleniumbase_screenshot_diagnostic(self, sb: Any, base_path: Path) -> str | None:
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
                except Exception as exc:
                    logger.debug('Failed to capture SeleniumBase screenshot: {}', exc)
                    continue
            except Exception as exc:
                logger.debug('Failed to capture SeleniumBase screenshot: {}', exc)
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
        except Exception as exc:
            logger.debug('Failed to write SeleniumBase diagnostic metadata: {}', exc)
            return None

    @staticmethod
    def _json_safe_error_arg(value: Any) -> Any:
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

    @staticmethod
    def _sanitize_proxy_environment_value(value: str) -> str:
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
        self, sb: Any, url: str, attempt: int, error: Exception
    ) -> None:
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
