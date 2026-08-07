from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from downloader.sources.metadata import SourceVerification
from downloader.sources.profiles import SourceProfile

VERIFICATION_STORE_VERSION = 1
VERIFICATION_STORE_DIRECTORY = '.comic_downloader'
VERIFICATION_STORE_FILENAME = 'source-verifications.json'
SOURCE_CHECK_TIMEOUT_SECONDS = 12.0
HTTP_SUCCESS_MIN_STATUS = 200
HTTP_ERROR_STATUS = 400
KNOWN_VERIFICATION_STATUSES = frozenset({'unchecked', 'healthy', 'degraded', 'unavailable'})
URL_CREDENTIALS_PATTERN = re.compile(r'([a-z][a-z0-9+.-]*://)[^/@\s]+@', re.IGNORECASE)


class SourceVerificationStoreError(Exception):
    pass


class SourceVerificationStore:
    """Persist the latest explicit connectivity check for each source."""

    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.store_dir = self.output_dir / VERIFICATION_STORE_DIRECTORY
        self.store_path = self.store_dir / VERIFICATION_STORE_FILENAME
        self._lock = threading.RLock()

    def load_all(self) -> dict[str, SourceVerification]:
        with self._lock:
            return self._load()

    def save_all(self, results: dict[str, SourceVerification]) -> None:
        with self._lock:
            existing = self._load()
            existing.update(results)
            self._save(existing)

    def _load(self) -> dict[str, SourceVerification]:
        if not self.store_path.exists():
            return {}
        try:
            with open(self.store_path, encoding='utf-8-sig') as verification_file:
                raw = json.load(verification_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceVerificationStoreError(f'来源验证记录读取失败: {exc}') from exc

        if not isinstance(raw, dict) or raw.get('version') != VERIFICATION_STORE_VERSION:
            raise SourceVerificationStoreError('来源验证记录版本无效。')
        raw_sources = raw.get('sources')
        if not isinstance(raw_sources, dict):
            raise SourceVerificationStoreError('来源验证记录的 sources 必须是对象。')

        results: dict[str, SourceVerification] = {}
        for source_name, value in raw_sources.items():
            if not isinstance(source_name, str) or not source_name:
                raise SourceVerificationStoreError('来源验证记录包含无效来源名称。')
            results[source_name] = _verification_from_mapping(value)
        return results

    def _save(self, results: dict[str, SourceVerification]) -> None:
        payload = {
            'version': VERIFICATION_STORE_VERSION,
            'sources': {
                source_name: asdict(result) for source_name, result in sorted(results.items())
            },
        }
        temp_path: str | None = None
        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.store_dir,
                prefix='source-verifications-',
                suffix='.tmp',
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write('\n')
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.store_path)
        except OSError as exc:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise SourceVerificationStoreError(f'来源验证记录写入失败: {exc}') from exc


def verify_source_connectivity(
    profile: SourceProfile,
    http: requests.Session,
    *,
    timeout_seconds: float = SOURCE_CHECK_TIMEOUT_SECONDS,
) -> SourceVerification:
    """Perform one explicit, lightweight HTTP connectivity check."""
    checked_at = _timestamp()
    started_at = time.perf_counter()
    if not profile.base_url:
        return SourceVerification(
            status='unavailable',
            checked_at=checked_at,
            latency_seconds=0.0,
            message='来源未配置 base_url。',
            error_type='ConfigurationError',
        )

    response: requests.Response | None = None
    try:
        response = http.get(
            profile.base_url,
            timeout=timeout_seconds,
            allow_redirects=True,
            stream=True,
        )
        latency = _elapsed_seconds(started_at)
        status_code = int(response.status_code)
        final_url = _redact_url_credentials(str(response.url or profile.base_url))
        if HTTP_SUCCESS_MIN_STATUS <= status_code < HTTP_ERROR_STATUS:
            status = 'healthy'
            message = f'HTTP {status_code}，连接正常。'
        else:
            status = 'degraded'
            message = f'站点可连接，但返回 HTTP {status_code}。'
        return SourceVerification(
            status=status,
            checked_at=checked_at,
            latency_seconds=latency,
            http_status=status_code,
            message=message,
            final_url=final_url,
        )
    except Exception as exc:
        return SourceVerification(
            status='unavailable',
            checked_at=checked_at,
            latency_seconds=_elapsed_seconds(started_at),
            message=_redact_url_credentials(str(exc)) or type(exc).__name__,
            error_type=type(exc).__name__,
        )
    finally:
        if response is not None:
            with suppress(Exception):
                response.close()


def _verification_from_mapping(raw: Any) -> SourceVerification:
    if not isinstance(raw, dict):
        raise SourceVerificationStoreError('单条来源验证记录必须是对象。')
    status = raw.get('status')
    if status not in KNOWN_VERIFICATION_STATUSES:
        raise SourceVerificationStoreError(f'未知来源验证状态: {status}')
    try:
        latency = _optional_float(raw.get('latency_seconds'))
        http_status = _optional_int(raw.get('http_status'))
    except (TypeError, ValueError) as exc:
        raise SourceVerificationStoreError(f'来源验证记录字段无效: {exc}') from exc
    return SourceVerification(
        status=status,
        checked_at=_optional_string(raw.get('checked_at')),
        latency_seconds=latency,
        http_status=http_status,
        message=_optional_string(raw.get('message')),
        final_url=_optional_string(raw.get('final_url')),
        error_type=_optional_string(raw.get('error_type')),
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _elapsed_seconds(started_at: float) -> float:
    return round(max(0.0, time.perf_counter() - started_at), 3)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else max(0.0, float(value))


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _redact_url_credentials(value: str) -> str:
    return URL_CREDENTIALS_PATTERN.sub(r'\1<credentials>@', value)
