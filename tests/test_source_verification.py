from __future__ import annotations

import json
from typing import Any, cast

import pytest
import requests

from downloader.sources.metadata import SourceVerification
from downloader.sources.profiles import SourceProfile
from downloader.sources.verification import (
    SourceVerificationStore,
    SourceVerificationStoreError,
    verify_source_connectivity,
)


class FakeResponse:
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeHttp:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _profile(base_url: str = 'https://example.test') -> SourceProfile:
    return SourceProfile('example', 'ExampleComic', True, False, base_url=base_url)


def test_verify_source_connectivity_records_healthy_response_and_closes_it():
    response = FakeResponse(204, 'https://example.test/home')
    http = FakeHttp(response)

    result = verify_source_connectivity(
        _profile(),
        cast(requests.Session, http),
        timeout_seconds=3.5,
    )

    assert result.status == 'healthy'
    assert result.checked is True
    assert result.http_status == 204
    assert result.final_url == 'https://example.test/home'
    assert result.latency_seconds is not None
    assert result.latency_seconds >= 0
    assert http.calls == [
        (
            'https://example.test',
            {'timeout': 3.5, 'allow_redirects': True, 'stream': True},
        )
    ]
    assert response.closed is True


def test_verify_source_connectivity_marks_http_error_as_degraded():
    response = FakeResponse(403, 'https://example.test/challenge')

    result = verify_source_connectivity(
        _profile(),
        cast(requests.Session, FakeHttp(response)),
    )

    assert result.status == 'degraded'
    assert result.http_status == 403
    assert result.error_type is None
    assert '可连接' in (result.message or '')


def test_verify_source_connectivity_marks_transport_error_as_unavailable():
    error = requests.ConnectionError(
        'proxy https://reader:secret@proxy.example.test connection refused'
    )

    result = verify_source_connectivity(
        _profile(),
        cast(requests.Session, FakeHttp(error=error)),
    )

    assert result.status == 'unavailable'
    assert result.http_status is None
    assert result.error_type == 'ConnectionError'
    assert result.message == ('proxy https://<credentials>@proxy.example.test connection refused')


def test_verification_store_round_trips_and_merges_latest_results(tmp_path):
    store = SourceVerificationStore(tmp_path)
    healthy = SourceVerification(
        status='healthy',
        checked_at='2026-08-08T00:00:00+00:00',
        latency_seconds=0.123,
        http_status=200,
        message='HTTP 200，连接正常。',
        final_url='https://example.test/',
    )
    degraded = SourceVerification(
        status='degraded',
        checked_at='2026-08-08T00:01:00+00:00',
        latency_seconds=0.456,
        http_status=403,
        message='站点可连接，但返回 HTTP 403。',
    )

    store.save_all({'one': healthy})
    store.save_all({'two': degraded})

    assert store.load_all() == {'one': healthy, 'two': degraded}
    payload = json.loads(store.store_path.read_text(encoding='utf-8'))
    assert payload['version'] == 1
    assert payload['sources']['one']['http_status'] == 200
    assert list(store.store_dir.glob('*.tmp')) == []


def test_verification_store_rejects_unknown_status(tmp_path):
    store = SourceVerificationStore(tmp_path)
    store.store_dir.mkdir(parents=True)
    store.store_path.write_text(
        '{"version": 1, "sources": {"example": {"status": "configured"}}}',
        encoding='utf-8',
    )

    with pytest.raises(SourceVerificationStoreError, match='未知来源验证状态'):
        store.load_all()
