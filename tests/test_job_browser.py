from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from downloader.download.job_browser import (
    JobSummary,
    TaskQuery,
    matching_jobs,
    matching_volumes,
    parse_task_query,
    unique_job_prefixes,
)
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume
from downloader.models import VolumeDownloadResult


def make_job(job_id='a' * 32):
    volumes = [JobVolume('正篇', f'第{i}话', f'https://example.test/{i}') for i in range(5)]
    for volume, status in zip(
        volumes, ['downloaded', 'skipped', 'partial', 'failed'], strict=False
    ):
        volume.result = VolumeDownloadResult(volume.name, volume.url, status)
    return DownloadJob(
        'fixture', '[red]漫画[/]', 'https://example.test/comic', volumes, id=job_id, state='failed'
    )


@pytest.mark.parametrize(
    'args, expected',
    [
        ([], TaskQuery()),
        (['unfinished', '2'], TaskQuery(status='unfinished', page=2)),
        (['ABCD', 'failed', '3'], TaskQuery('abcd', 'failed', 3)),
        (['1234'], TaskQuery('1234')),
        (['abcd', '2'], TaskQuery('abcd', page=2)),
        (['running'], TaskQuery(status='running')),
    ],
)
def test_task_command_syntax_preserves_numeric_id_prefixes(args, expected):
    assert parse_task_query(args) == expected


@pytest.mark.parametrize(
    'args',
    [
        ['2'],
        ['next'],
        ['prev'],
        ['unknown'],
        ['all', '0'],
        ['all', '-1'],
        ['abcd', 'running'],
        ['all', '2', 'extra'],
        ['abcd', 'all', '2', 'extra'],
    ],
)
def test_invalid_task_command_is_rejected(args):
    with pytest.raises(ValueError):
        parse_task_query(args)


def test_relative_navigation_preserves_filter_and_task_id():
    query = TaskQuery('a' * 32, 'failed', 2)
    assert parse_task_query(['next'], query) == replace(query, page=3)
    assert parse_task_query(['prev'], query) == replace(query, page=1)
    with pytest.raises(ValueError, match='第一页'):
        parse_task_query(['prev'], replace(query, page=1))


def test_summary_and_filters_count_skipped_and_partial_results_correctly():
    job = make_job()
    summary = JobSummary.from_job(job)
    assert summary.total == 5
    assert summary.remaining == 3
    assert matching_volumes(job, 'completed') == [0, 1]
    assert matching_volumes(job, 'failed') == [2, 3]
    assert matching_volumes(job, 'unfinished') == [2, 3, 4]
    assert matching_volumes(job, 'pending') == [4]
    assert matching_jobs([summary], 'completed') == []
    assert matching_jobs([summary], 'unfinished') == [summary]
    assert matching_jobs([summary], 'failed') == [summary]
    assert matching_jobs([replace(summary, remaining=0, state='running')], 'unfinished') == []


def test_colliding_prefixes_are_unique_across_filtered_pages():
    jobs = [JobSummary.from_job(make_job('a' * 12 + suffix * 20)) for suffix in ('0', '1', '2')]
    other = JobSummary.from_job(make_job('b' * 32))
    labels = unique_job_prefixes([*jobs, other])
    assert len(set(labels.values())) == 4
    for job in jobs:
        assert labels[job.id] == job.id[:13]
    assert labels[other.id] == other.id[:12]


def test_summary_cache_reuses_unchanged_records_and_tracks_external_writes(tmp_path, monkeypatch):
    store = JobStore(str(tmp_path))
    external = JobStore(str(tmp_path))
    job = make_job()
    external.save(job)
    reads = []
    original_read = store._read

    def read(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(store, '_read', read)
    first, errors = store.list_summaries()
    assert not errors
    assert store.list_summaries()[0] == first
    assert len(reads) == 1
    job.comic_name = '其他进程已更新'
    external.save(job)
    assert store.list_summaries()[0][0].comic_name == '其他进程已更新'
    assert len(reads) == 2
    second = make_job('b' * 32)
    external.save(second)
    assert len(store.list_summaries()[0]) == 2
    assert len(reads) == 3
    (store.directory / f'{job.id}.json').unlink()
    summaries, errors = store.list_summaries()
    assert [summary.id for summary in summaries] == [second.id]
    assert not errors
    assert len(store._summaries) == 1


def test_cache_does_not_keep_stale_summary_for_corrupt_or_repaired_record(tmp_path):
    store = JobStore(str(tmp_path))
    job = make_job()
    store.save(job)
    assert len(store.list_summaries()[0]) == 1
    record = store.directory / f'{job.id}.json'
    record.write_text('{broken', encoding='utf-8')
    summaries, errors = store.list_summaries()
    assert summaries == []
    assert len(errors) == 1
    assert not store._summaries
    store.save(job)
    assert store.list_summaries()[1] == []
    assert len(store.list_summaries()[0]) == 1


def test_atomic_replacement_with_same_size_and_mtime_invalidates_cache(tmp_path):
    store = JobStore(str(tmp_path))
    job = make_job()
    store.save(job)
    store.list_summaries()
    record = store.directory / f'{job.id}.json'
    stat = record.stat()
    changed = record.read_bytes().replace(b'fixture', b'changed')
    temporary = record.with_suffix('.tmp')
    temporary.write_bytes(changed)
    os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(temporary, record)
    assert store.list_summaries()[0][0].source_name == 'changed'


def test_replacement_during_read_does_not_cache_mismatched_snapshot(tmp_path, monkeypatch):
    store = JobStore(str(tmp_path))
    external = JobStore(str(tmp_path))
    job = make_job()
    store.save(job)
    original_read = store._read

    def replace_during_read(path):
        before = original_read(path)
        job.comic_name = '替换后的漫画'
        external.save(job)
        return before

    monkeypatch.setattr(store, '_read', replace_during_read)
    assert store.list_summaries()[0][0].comic_name == '[red]漫画[/]'
    assert not store._summaries
    monkeypatch.setattr(store, '_read', original_read)
    assert store.list_summaries()[0][0].comic_name == '替换后的漫画'


def test_summary_reads_do_not_modify_records_and_sort_equal_timestamps_by_id(tmp_path):
    store = JobStore(str(tmp_path))
    for suffix in ('a', 'b'):
        store.save(make_job(suffix * 32))
    before = {}
    for record in store.directory.glob('*.json'):
        data = json.loads(record.read_text(encoding='utf-8'))
        data['updated_at'] = '2026-10-13T00:00:00+00:00'
        record.write_text(json.dumps(data), encoding='utf-8')
        before[record] = record.read_bytes()
    summaries, errors = store.list_summaries()
    assert not errors
    assert [summary.id for summary in summaries] == ['b' * 32, 'a' * 32]
    assert all(path.read_bytes() == content for path, content in before.items())


def test_empty_summary_read_does_not_create_directory(tmp_path):
    store = JobStore(str(tmp_path))
    assert store.list_summaries() == ([], [])
    assert not store.directory.exists()
