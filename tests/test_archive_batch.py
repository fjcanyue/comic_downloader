from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import main as main_module
import pytest

from downloader.download.archive_batch import ArchiveBatchStore
from downloader.download.job_archive import parse_archive_query
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume
from downloader.models import VolumeDownloadResult


def save_job(store, name='星海', *, state='completed'):
    volume = JobVolume('正篇', '第一话', 'https://example.test/chapter')
    if state == 'completed':
        volume.result = VolumeDownloadResult(volume.name, volume.url, 'downloaded')
    job = DownloadJob('test', name, 'https://example.test/comic', [volume], state=state)
    store.save(job)
    return job


@pytest.fixture
def batch_store(tmp_path):
    return ArchiveBatchStore(JobStore(str(tmp_path)))


def test_preview_freezes_matching_completed_plans_without_moving_files(batch_store, tmp_path):
    jobs = batch_store.jobs
    selected = save_job(jobs, '[red]星海')
    save_job(jobs, '其他漫画')
    save_job(jobs, '星海', state='failed')
    comic_file = tmp_path / '漫画.zip'
    comic_file.write_bytes(b'comic bytes')
    before = {path.name: path.read_bytes() for path in jobs.directory.glob('*.json')}
    batch = batch_store.create('星海 TEST')
    assert [entry.summary.id for entry in batch.entries] == [selected.id]
    assert batch.state == 'ready' and not batch.successful
    assert before == {path.name: path.read_bytes() for path in jobs.directory.glob('*.json')}
    assert not jobs.archive_view().directory.exists()

    new = save_job(jobs, '星海新任务')
    restarted = ArchiveBatchStore(JobStore(str(tmp_path)))
    assert restarted.load(batch.id) == batch
    result = restarted.apply(batch.id)
    assert result.successful and result.entries[0].status == 'archived'
    assert jobs.load(new.id).state == 'completed'
    assert (jobs.archive_view().directory / f'{selected.id}.json').read_bytes() == before[
        f'{selected.id}.json'
    ]
    assert comic_file.read_bytes() == b'comic bytes'


def test_changed_missing_conflicting_and_locked_records_are_skipped_individually(batch_store):
    jobs = batch_store.jobs
    changed, missing, conflict, locked, good = [save_job(jobs, str(i)) for i in range(5)]
    batch = batch_store.create()
    # Keep the timestamp and count unchanged: compare full content, not summary fields.
    changed.comic_url += '/changed'
    path = jobs.directory / f'{changed.id}.json'
    path.write_text(json.dumps(asdict(changed)), encoding='utf-8')
    jobs.archive(missing.id)
    destination = jobs.archive_view().directory / f'{conflict.id}.json'
    destination.write_bytes(b'conflicting contents')
    with jobs.lock(locked.id):
        result = batch_store.apply(batch.id)
    statuses = {entry.summary.id: entry.status for entry in result.entries}
    assert statuses == {
        changed.id: 'skipped',
        missing.id: 'skipped',
        conflict.id: 'skipped',
        locked.id: 'skipped',
        good.id: 'archived',
    }
    assert not result.successful
    assert jobs.load(changed.id).comic_url.endswith('/changed')
    assert jobs.load(locked.id).state == 'completed'
    assert destination.read_bytes() == b'conflicting contents'


def test_fingerprint_is_rechecked_after_acquiring_job_lock(batch_store, monkeypatch):
    jobs = batch_store.jobs
    job = save_job(jobs)
    batch = batch_store.create()
    original_lock = JobStore.lock

    @contextmanager
    def mutate_on_lock(store, job_id):
        with original_lock(store, job_id):
            if job_id == job.id:
                changed = store.load(job_id)
                changed.comic_name = '已改变'
                store.save(changed)
            yield

    monkeypatch.setattr(JobStore, 'lock', mutate_on_lock)
    result = batch_store.apply(batch.id)
    assert result.entries[0].status == 'skipped'
    assert '自预览后已变化' in result.entries[0].message
    assert jobs.load(job.id).comic_name == '已改变'


def test_finished_batch_never_rearchives_restored_records_or_retries_failures(
    batch_store, monkeypatch
):
    jobs = batch_store.jobs
    good, failed = save_job(jobs, '成功'), save_job(jobs, '失败')
    batch = batch_store.create()
    archive = jobs.archive

    def fail_one(job_id, **kwargs):
        if job_id == failed.id:
            raise OSError('disk unavailable')
        return archive(job_id, **kwargs)

    monkeypatch.setattr(jobs, 'archive', fail_one)
    first = batch_store.apply(batch.id)
    assert {e.status for e in first.entries} == {'archived', 'failed'}
    jobs.restore(good.id)
    monkeypatch.setattr(
        jobs, 'archive', lambda *a, **kw: pytest.fail('must not replay a finished batch')
    )
    assert batch_store.apply(batch.id) == first
    assert jobs.load(good.id).state == jobs.load(failed.id).state == 'completed'


@pytest.mark.parametrize('move_before_interrupt', [False, True])
def test_interrupted_entry_is_reconciled_without_replaying_ambiguous_moves(
    batch_store, monkeypatch, move_before_interrupt
):
    jobs = batch_store.jobs
    job = save_job(jobs)
    batch = batch_store.create()
    original = jobs.archive

    def interrupt(job_id, **kwargs):
        if move_before_interrupt:
            original(job_id, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(jobs, 'archive', interrupt)
    with pytest.raises(KeyboardInterrupt):
        batch_store.apply(batch.id)
    saved = batch_store.load(batch.id)
    assert saved.state == 'running' and saved.entries[0].status == 'applying'
    monkeypatch.setattr(
        jobs, 'archive', lambda *a, **kw: pytest.fail('ambiguous move must not be replayed')
    )
    recovered = batch_store.apply(batch.id)
    assert recovered.entries[0].status == ('archived' if move_before_interrupt else 'skipped')
    assert recovered.state == 'finished'
    if not move_before_interrupt:
        assert jobs.load(job.id).state == 'completed'


def test_cancel_is_persistent_and_apply_cannot_override_it(batch_store):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()
    cancelled = batch_store.cancel(batch.id)
    assert cancelled.state == 'cancelled'
    assert batch_store.cancel(batch.id) == cancelled
    with pytest.raises(ValueError, match='已取消'):
        batch_store.apply(batch.id)
    assert batch_store.jobs.load(job.id).state == 'completed'


def test_corrupt_records_are_reported_and_excluded_from_candidates(batch_store):
    jobs = batch_store.jobs
    save_job(jobs)
    broken = jobs.directory / ('f' * 32 + '.json')
    broken.write_text('{invalid json', encoding='utf-8')
    batch = batch_store.create()
    assert len(batch.errors) == 1 and len(batch.entries) == 1
    result = batch_store.apply(batch.id)
    assert result.entries[0].status == 'archived' and not result.successful
    assert broken.read_text(encoding='utf-8') == '{invalid json'


def test_batch_write_failure_prevents_unjournaled_moves(batch_store, monkeypatch):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()

    def fail_save(batch):
        raise OSError('cannot persist batch')

    monkeypatch.setattr(batch_store, '_save', fail_save)
    with pytest.raises(OSError, match='cannot persist'):
        batch_store.apply(batch.id)
    assert batch_store.jobs.load(job.id).state == 'completed'
    assert batch_store.load(batch.id).state == 'ready'


def test_entry_journal_failure_stops_before_moving_task(batch_store, monkeypatch):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()

    def fail_entry(*args):
        raise OSError('journal unavailable')

    monkeypatch.setattr(batch_store, '_save_entry', fail_entry)
    with pytest.raises(OSError, match='journal unavailable'):
        batch_store.apply(batch.id)
    assert batch_store.jobs.load(job.id).state == 'completed'
    assert batch_store.load(batch.id).entries[0].status == 'pending'


def test_interrupted_and_restored_entry_is_not_rearchived_while_pending_entries_continue(
    batch_store, monkeypatch
):
    jobs = batch_store.jobs
    save_job(jobs, '第一本')
    save_job(jobs, '第二本')
    batch = batch_store.create()
    first, second = [e.summary.id for e in batch.entries]
    original = jobs.archive

    def interrupt(job_id, **kwargs):
        original(job_id, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(jobs, 'archive', interrupt)
    with pytest.raises(KeyboardInterrupt):
        batch_store.apply(batch.id)
    jobs.restore(first)
    monkeypatch.setattr(jobs, 'archive', original)
    recovered = batch_store.apply(batch.id)
    assert [e.status for e in recovered.entries] == ['skipped', 'archived']
    assert jobs.load(first).state == 'completed'
    assert jobs.archive_view().load(second).state == 'completed'


def test_batch_execution_writes_linear_metadata_volume(batch_store, monkeypatch):
    for index in range(30):
        save_job(batch_store.jobs, f'漫画 {index}')
    batch = batch_store.create()
    snapshot_bytes = (batch_store.directory / f'{batch.id}.json').stat().st_size
    original = os.replace
    written = []

    def count_bytes(source, destination):
        if batch_store.directory in Path(destination).parents:
            written.append(Path(source).stat().st_size)
        original(source, destination)

    monkeypatch.setattr(os, 'replace', count_bytes)
    assert batch_store.apply(batch.id).successful
    # A large batch must not rewrite its full candidate set for every item.
    assert sum(written) < 10 * snapshot_bytes


def test_batch_history_survives_restart_and_isolates_corrupt_manifests(batch_store, tmp_path):
    save_job(batch_store.jobs)
    ready = batch_store.create()
    cancelled = batch_store.create('没有匹配')
    batch_store.cancel(cancelled.id)
    broken = batch_store.directory / ('f' * 32 + '.json')
    broken.write_text('broken', encoding='utf-8')
    batches, errors = ArchiveBatchStore(JobStore(str(tmp_path))).list_batches()
    assert {batch.id for batch in batches} == {ready.id, cancelled.id}
    assert len(errors) == 1
    listed = run_cli(batch_store, 'list')
    assert (
        listed.returncode == 1 and '批次历史' in listed.stdout and '无法读取批次' in listed.stdout
    )


@pytest.mark.parametrize(
    'change', ['duplicate', 'path', 'version', 'digest', 'status', 'invalid_id', 'unfinished']
)
def test_invalid_batch_is_rejected_without_moving_any_records(batch_store, change):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()
    path = batch_store.directory / f'{batch.id}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if change == 'duplicate':
        data['entries'].append(data['entries'][0])
    elif change == 'path':
        data['output_path'] += '/another-root'
    elif change == 'version':
        data['version'] = True
    elif change == 'digest':
        data['entries'][0]['digest'] = 'bad'
    elif change == 'status':
        data['entries'][0]['status'] = 'archived'
    elif change == 'invalid_id':
        data['entries'][0]['summary']['id'] = '../escape'
    else:
        data['entries'][0]['summary']['remaining'] = 1
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='批次损坏'):
        batch_store.apply(batch.id)
    assert batch_store.jobs.load(job.id).state == 'completed'


def test_batch_lock_is_respected_across_processes(batch_store):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()
    with batch_store.jobs.lock(batch.id):
        result = run_cli(batch_store, 'apply', batch.id)
    assert result.returncode == 1 and '其他进程' in result.stdout
    assert batch_store.load(batch.id).state == 'ready'
    assert batch_store.jobs.load(job.id).state == 'completed'


def run_cli(store, *args):
    return subprocess.run(  # noqa: S603 - fixed local CLI and fixture data
        [
            sys.executable,
            '-X',
            'utf8',
            'main.py',
            store.jobs.output_path,
            'archive',
            'batch',
            *args,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=30,
    )


def test_direct_cli_preview_show_apply_persists_results_and_returns_partial_failure(batch_store):
    job = save_job(batch_store.jobs)
    preview = run_cli(batch_store, 'find', '星海', 'TEST')
    assert preview.returncode == 0, preview.stderr
    assert '归档候选预览' in preview.stdout and '预览未移动' in preview.stdout
    batch_id = next(batch_store.directory.glob('*.json')).stem
    shown = run_cli(batch_store, 'show', batch_id)
    assert shown.returncode == 0 and '固定候选 1 项' in shown.stdout
    job.comic_name = '变动'
    batch_store.jobs.save(job)
    applied = run_cli(batch_store, 'apply', batch_id)
    assert applied.returncode == 1 and '已跳过' in applied.stdout
    assert batch_store.jobs.load(job.id).state == 'completed'


@pytest.mark.parametrize(
    'args',
    [
        [],
        ['find', '漫画', 'TEST'],
        ['show', 'a' * 32, '2'],
        ['apply', 'a' * 32],
        ['cancel', 'a' * 32],
    ],
)
def test_batch_commands_share_cli_validation(args):
    query = parse_archive_query(['batch', *args])
    assert query.action.startswith('batch-')
    assert main_module._parse_command(['archive', 'batch', *args])[1:] == (
        'archive',
        ['batch', *args],
    )


@pytest.mark.parametrize(
    'args',
    [
        ['find'],
        ['all'],
        ['apply'],
        ['show', '../path'],
        ['show', 'abcd'],
        ['show', 'a' * 32, '0'],
        ['apply', 'a' * 32, '2'],
        ['cancel', 'a' * 32, 'find', 'x'],
    ],
)
def test_invalid_batch_commands_fail_before_shell_creation(args):
    with pytest.raises(main_module.CommandUsageError):
        main_module._parse_command(['archive', 'batch', *args])


@pytest.mark.parametrize('field', ['status', 'digest'])
def test_inconsistent_interruption_journal_is_rejected_without_replaying_move(
    batch_store, monkeypatch, field
):
    job = save_job(batch_store.jobs)
    batch = batch_store.create()

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch_store.jobs, 'archive', interrupt)
    with pytest.raises(KeyboardInterrupt):
        batch_store.apply(batch.id)
    journal = batch_store.directory / batch.id / f'{job.id}.json'
    data = json.loads(journal.read_text(encoding='utf-8'))
    data[field] = 'pending' if field == 'status' else '0' * 64
    journal.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(
        batch_store.jobs, 'archive', lambda *a, **kw: pytest.fail('corrupt journal must not replay')
    )
    with pytest.raises(ValueError, match='执行记录与批次候选不一致'):
        batch_store.apply(batch.id)
    assert batch_store.jobs.load(job.id).state == 'completed'
