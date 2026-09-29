from __future__ import annotations

import json
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest
import requests

from downloader.comic import ComicSource
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume, run_download_job
from downloader.download.progress import NoopDownloadProgress
from downloader.models import ImageDownloadFailure, VolumeDownloadResult


class JobSource(ComicSource):
    def __init__(self, output):
        super().__init__(str(output), cast(Any, object()), None, overwrite=False)
        self.calls = []
        self.outcomes = {}

    def search(self, keyword):
        return []

    def info(self, url):
        raise AssertionError('resume must use the saved plan without fetching comic details')

    def __parse_imgs__(self, url):
        return []

    def create_download_progress(self):
        return NoopDownloadProgress()

    def __download_vol__(self, path, name, url, parent_progress=None):
        self.calls.append((Path(path).name, url))
        outcome = self.outcomes.get(url, 'downloaded')
        if isinstance(outcome, BaseException):
            raise outcome
        return VolumeDownloadResult(
            name, url, outcome, message='超时' if outcome == 'failed' else ''
        )


@pytest.fixture
def job_store(tmp_path):
    store = JobStore(str(tmp_path))
    job = DownloadJob(
        'test',
        '漫画',
        'https://example.test/comic',
        [
            JobVolume('正篇', '第一话', 'https://example.test/1'),
            JobVolume('正篇', '第二话', 'https://example.test/2'),
            JobVolume('番外', '第三话', 'https://example.test/3'),
        ],
    )
    store.save(job)
    return store, job


def test_partial_job_survives_restart_and_retries_only_unsuccessful_volumes(job_store, tmp_path):
    store, job = job_store
    source = JobSource(tmp_path)
    source.outcomes = {job.volumes[1].url: 'partial', job.volumes[2].url: 'skipped'}
    first = run_download_job(store, job.id, source)
    assert first.state == 'failed'
    assert first.summary.partial == 1
    assert len(first.remaining) == 1

    restarted_store = JobStore(str(tmp_path))
    restarted_source = JobSource(tmp_path)
    final = run_download_job(restarted_store, job.id, restarted_source)
    assert restarted_source.calls == [('正篇', job.volumes[1].url)]
    assert final.state == 'completed'
    assert final.summary.skipped == 1
    assert final.summary.downloaded == 2
    assert restarted_store.load(job.id[:12]).state == 'completed'


def test_interrupt_keeps_each_completed_chapter_and_resumes_remaining_groups(job_store, tmp_path):
    store, job = job_store
    source = JobSource(tmp_path)
    source.outcomes[job.volumes[1].url] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_download_job(store, job.id, source)
    checkpoint = store.load(job.id)
    assert checkpoint.state == 'interrupted'
    assert checkpoint.volumes[0].complete
    assert len(checkpoint.remaining) == 2

    resumed = JobSource(tmp_path)
    final = run_download_job(store, job.id, resumed)
    assert resumed.calls == [('正篇', job.volumes[1].url), ('番外', job.volumes[2].url)]
    assert final.state == 'completed'


def test_completed_job_is_noop_even_with_overwrite_enabled(job_store, tmp_path):
    store, job = job_store
    source = JobSource(tmp_path)
    run_download_job(store, job.id, source)
    source.calls.clear()
    source.overwrite = True
    assert run_download_job(store, job.id, source).state == 'completed'
    assert source.calls == []


def test_crash_after_last_checkpoint_can_finalize_without_source(job_store, tmp_path):
    store, job = job_store
    completed = run_download_job(store, job.id, JobSource(tmp_path))
    completed.state = 'running'
    store.save(completed)
    assert run_download_job(store, job.id, None).state == 'completed'
    assert store.load(job.id).state == 'completed'


def test_forced_process_exit_preserves_checkpoint_for_next_process(job_store, tmp_path):
    store, job = job_store
    program = """
import os
import sys
from downloader.download.job_store import JobStore
from downloader.download.jobs import run_download_job
from downloader.models import VolumeDownloadResult
class CrashSource:
    def download_vols(self, comic_name, book_name, volumes, *, on_result):
        first = volumes[0]
        on_result(VolumeDownloadResult(first.name, first.url, 'downloaded'))
        os._exit(9)
run_download_job(JobStore(sys.argv[1]), sys.argv[2], CrashSource())
"""
    result = subprocess.run(  # noqa: S603 - fixed local Python test program
        [sys.executable, '-c', program, str(tmp_path), job.id],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 9, result.stderr
    checkpoint = store.load(job.id)
    assert checkpoint.state == 'running'
    assert checkpoint.volumes[0].complete
    resumed = JobSource(tmp_path)
    assert run_download_job(store, job.id, resumed).state == 'completed'
    assert resumed.calls == [('正篇', job.volumes[1].url), ('番外', job.volumes[2].url)]


def test_atomic_save_failure_preserves_previous_record(job_store, monkeypatch):
    store, job = job_store
    record = store.directory / f'{job.id}.json'
    previous = record.read_bytes()

    def fail_replace(*args):
        raise OSError('disk unavailable')

    monkeypatch.setattr('downloader.download.job_store.os.replace', fail_replace)
    job.state = 'running'
    with pytest.raises(OSError, match='disk unavailable'):
        store.save(job)
    assert record.read_bytes() == previous
    assert list(store.directory.glob('*.tmp')) == []


def test_checkpoint_failure_stops_before_next_chapter(job_store, tmp_path, monkeypatch):
    store, job = job_store
    source = JobSource(tmp_path)
    save = store.save

    def fail_after_first_result(record):
        if record.volumes[0].result:
            raise OSError('disk full')
        save(record)

    monkeypatch.setattr(store, 'save', fail_after_first_result)
    with pytest.raises(OSError, match='disk full'):
        run_download_job(store, job.id, source)
    assert source.calls == [('正篇', job.volumes[0].url)]
    assert len(store.load(job.id).remaining) == 3


def test_bad_record_does_not_hide_other_jobs(job_store):
    store, job = job_store
    (store.directory / f'{"a" * 32}.json').write_text('{broken', encoding='utf-8')
    jobs, errors = store.list_jobs()
    assert [item.id for item in jobs] == [job.id]
    assert len(errors) == 1
    assert '记录损坏' in errors[0]


@pytest.mark.parametrize('job_id', ['../outside', '', 'xyz!', 'abc'])
def test_invalid_ids_cannot_be_used_as_paths(job_store, job_id):
    store, _ = job_store
    with pytest.raises(ValueError, match='任务 ID'):
        store.load(job_id)


def test_ambiguous_prefix_requires_longer_id(job_store):
    store, job = job_store
    job.id = 'abcd' + '0' * 28
    store.save(job)
    job.id = 'abcd' + '1' * 28
    store.save(job)
    with pytest.raises(ValueError, match='多个任务'):
        store.load('abcd')
    assert store.load('abcd1').id == job.id


@pytest.mark.parametrize(
    'change',
    [
        {'version': 999},
        {'volumes': []},
        {'state': 'completed'},
        {'source_name': None},
    ],
)
def test_invalid_schema_is_reported_without_overwriting_record(job_store, change):
    store, job = job_store
    path = store.directory / f'{job.id}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data.update(change)
    serialized = json.dumps(data)
    path.write_text(serialized, encoding='utf-8')
    with pytest.raises(ValueError, match='记录损坏'):
        store.load(job.id)
    assert path.read_text(encoding='utf-8') == serialized


def test_failure_details_round_trip(job_store):
    store, job = job_store
    volume = job.volumes[0]
    volume.result = VolumeDownloadResult(
        volume.name,
        volume.url,
        'partial',
        2,
        1,
        [ImageDownloadFailure(2, 'https://image.test/2', '0002.jpg', '网络超时')],
    )
    store.save(job)
    result = store.load(job.id).volumes[0].result
    assert result.failed_images[0].error == '网络超时'
    assert result.downloaded_count == 1


def test_process_lock_blocks_duplicate_execution_and_releases_after_crash(job_store, tmp_path):
    store, job = job_store
    program = """
import os
import sys
from downloader.download.job_store import JobStore
store = JobStore(sys.argv[1])
with store.lock(sys.argv[2]):
    print('locked', flush=True)
    sys.stdin.readline()
    os._exit(7)
"""
    process = subprocess.Popen(  # noqa: S603 - fixed local Python test program
        [sys.executable, '-c', program, str(tmp_path), job.id],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError, match='其他进程'):
            run_download_job(store, job.id, JobSource(tmp_path))
        process.communicate('crash\n', timeout=10)
        assert process.returncode == 7
        assert run_download_job(store, job.id, JobSource(tmp_path)).state == 'completed'
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_real_image_pipeline_recovers_failed_image_and_preserves_completed_volume(tmp_path):
    failed = {'enabled': True}
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            if self.path == '/image2' and failed['enabled']:
                self.send_error(503)
                return
            data = b'\xff\xd8\xff\xe0' + (b'\x00' * 12) + self.path.encode() + b'\xff\xd9'
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    class LocalSource(ComicSource):
        def search(self, keyword):
            return []

        def info(self, url):
            raise AssertionError('saved task should not fetch comic details')

        def __parse_imgs__(self, url):
            names = ['image1', 'image2'] if url.endswith('/1') else ['image3']
            return [f'{self.base_url}/{name}' for name in names]

        def create_download_progress(self):
            return NoopDownloadProgress()

        def _create_image_http_session(self):
            return requests.Session()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    http = requests.Session()
    try:
        source = LocalSource(str(tmp_path), http, None, overwrite=False)
        source.base_url = f'http://127.0.0.1:{server.server_port}'
        job = DownloadJob(
            'local',
            '漫画',
            source.base_url,
            [
                JobVolume('正篇', '第一话', f'{source.base_url}/1'),
                JobVolume('正篇', '第二话', f'{source.base_url}/2'),
            ],
        )
        store = JobStore(str(tmp_path))
        store.save(job)
        initial = run_download_job(store, job.id, source)
        assert initial.state == 'failed'
        assert initial.volumes[0].result is not None
        assert initial.volumes[0].result.status == 'partial'
        assert initial.volumes[1].complete
        original_second_zip = (tmp_path / '漫画' / '正篇' / '第二话.zip').read_bytes()
        calls.clear()
        failed['enabled'] = False

        final = run_download_job(JobStore(str(tmp_path)), job.id, source)
        assert final.state == 'completed'
        assert calls == ['/image2']
        assert (tmp_path / '漫画' / '正篇' / '第二话.zip').read_bytes() == original_second_zip
        with zipfile.ZipFile(tmp_path / '漫画' / '正篇' / '第一话.zip') as archive:
            assert archive.namelist() == ['0001.jpg', '0002.jpg']
            assert (
                archive.read('0002.jpg')
                == b'\xff\xd8\xff\xe0' + (b'\x00' * 12) + b'/image2\xff\xd9'
            )
    finally:
        http.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
