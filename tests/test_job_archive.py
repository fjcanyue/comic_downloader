from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import main as main_module
import pytest

from downloader.download.job_archive import ArchiveQuery, parse_archive_query
from downloader.download.job_store import JobStore
from downloader.download.jobs import DownloadJob, JobVolume, run_download_job
from downloader.models import VolumeDownloadResult


@pytest.fixture
def completed_plan(tmp_path):
    store = JobStore(str(tmp_path))
    volume = JobVolume('正篇', '第一话', 'https://example.test/1')
    volume.result = VolumeDownloadResult(volume.name, volume.url, 'downloaded')
    job = DownloadJob('test', '归档测试', 'https://example.test/comic', [volume], state='completed')
    store.save(job)
    return store, job


def test_archive_restore_preserves_record_bytes_id_dates_and_comic_files(completed_plan, tmp_path):
    store, job = completed_plan
    path = store.directory / f'{job.id}.json'
    original = path.read_bytes()
    comic_file = tmp_path / '漫画.zip'
    comic_file.write_bytes(b'existing archive contents')
    chapter_records = store.directory.parent / 'tasks.json'
    chapter_records.write_bytes(b'chapter records stay untouched')
    assert len(store.list_summaries()[0]) == 1

    archived = store.archive_view()
    assert archived.list_summaries() == ([], [])
    assert store.archive(job.id[:12]) == job
    assert not path.exists()
    assert store.list_jobs() == ([], [])
    assert store.list_summaries() == ([], [])
    assert (archived.directory / path.name).read_bytes() == original
    assert len(archived.list_summaries()[0]) == 1
    with pytest.raises(ValueError, match='没有找到任务'):
        run_download_job(store, job.id, None)

    restarted = JobStore(str(tmp_path))
    assert restarted.archive_view().load(job.id) == job
    assert restarted.restore(job.id[:12]) == job
    assert path.read_bytes() == original
    assert archived.list_summaries() == ([], [])
    assert len(store.list_summaries()[0]) == 1
    assert comic_file.read_bytes() == b'existing archive contents'
    assert chapter_records.read_bytes() == b'chapter records stay untouched'


@pytest.mark.parametrize('state', ['pending', 'running', 'interrupted', 'failed'])
def test_non_completed_state_cannot_be_archived_even_if_chapters_complete(completed_plan, state):
    store, job = completed_plan
    job.state = state
    store.save(job)
    with pytest.raises(ValueError, match='只能归档已完成'):
        store.archive(job.id)
    assert store.load(job.id).state == state
    assert store.archive_view().list_jobs() == ([], [])


def test_corrupt_completed_record_with_unfinished_chapter_cannot_move(completed_plan):
    store, job = completed_plan
    path = store.directory / f'{job.id}.json'
    text = path.read_text(encoding='utf-8').replace('"downloaded"', '"failed"')
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='已完成任务仍有未完成章节'):
        store.archive(job.id)
    assert path.read_text(encoding='utf-8') == text


@pytest.mark.parametrize('restoring', [False, True])
def test_conflicting_destination_never_overwrites_either_record(completed_plan, restoring):
    store, job = completed_plan
    if restoring:
        store.archive(job.id)
    source = store.archive_view() if restoring else store
    destination = store if restoring else store.archive_view()
    destination.directory.mkdir(parents=True, exist_ok=True)
    conflicting = destination.directory / f'{job.id}.json'
    conflicting.write_bytes(b'conflicting record')
    before = (source.directory / conflicting.name).read_bytes()
    with pytest.raises(ValueError, match='未覆盖任何记录'):
        (store.restore if restoring else store.archive)(job.id)
    assert conflicting.read_bytes() == b'conflicting record'
    assert (source.directory / conflicting.name).read_bytes() == before


@pytest.mark.parametrize('restoring', [False, True])
def test_move_failure_leaves_original_record_readable(completed_plan, monkeypatch, restoring):
    store, job = completed_plan
    if restoring:
        store.archive(job.id)

    def fail_move(*args, **kwargs):
        raise OSError('disk unavailable')

    monkeypatch.setattr(Path, 'rename', fail_move)
    with pytest.raises(OSError, match='disk unavailable'):
        (store.restore if restoring else store.archive)(job.id)
    source = store.archive_view() if restoring else store
    assert source.load(job.id) == job


@pytest.mark.parametrize('restoring', [False, True])
def test_archive_and_restore_respect_download_lock_across_processes(completed_plan, restoring):
    store, job = completed_plan
    if restoring:
        store.archive(job.id)
    program = """
import sys
from downloader.download.job_store import JobStore
store = JobStore(sys.argv[1])
try:
    getattr(store, sys.argv[3])(sys.argv[2])
except ValueError as exc:
    print(str(exc))
    sys.exit(7)
"""
    with store.lock(job.id):
        result = subprocess.run(  # noqa: S603 - fixed local regression program
            [
                sys.executable,
                '-X',
                'utf8',
                '-c',
                program,
                store.output_path,
                job.id,
                'restore' if restoring else 'archive',
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=15,
        )
    assert result.returncode == 7, result.stderr
    assert '正在其他进程中执行' in result.stdout
    assert (store.archive_view() if restoring else store).load(job.id) == job


def test_archive_reloads_record_after_lock_acquisition(completed_plan, monkeypatch):
    store, job = completed_plan
    original_lock = JobStore.lock

    @contextmanager
    def changed_lock(instance, job_id):
        with original_lock(instance, job_id):
            changed = instance.load(job_id)
            changed.state = 'running'
            instance.save(changed)
            yield

    monkeypatch.setattr(JobStore, 'lock', changed_lock)
    with pytest.raises(ValueError, match='只能归档已完成'):
        store.archive(job.id)
    assert store.load(job.id).state == 'running'


def test_archive_prefix_ambiguity_and_corrupt_record_are_isolated(completed_plan):
    store, job = completed_plan
    store.archive(job.id)
    job.id = job.id[:12] + ('a' if job.id[12] != 'a' else 'b') + job.id[13:]
    store.save(job)
    store.archive(job.id)
    archived = store.archive_view()
    broken = archived.directory / ('f' * 32 + '.json')
    broken.write_text('invalid json', encoding='utf-8')
    jobs, errors = archived.list_summaries()
    assert len(jobs) == 2
    assert len(errors) == 1
    with pytest.raises(ValueError, match='匹配多个任务'):
        store.restore(job.id[:12])
    assert len(archived.list_summaries()[0]) == 2


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        ([], ArchiveQuery()),
        (['list', '2'], ArchiveQuery(page=2)),
        (['ABCD'], ArchiveQuery('archive', 'abcd')),
        (['show', '1234', '3'], ArchiveQuery('show', '1234', 3)),
        (['restore', 'ABCD'], ArchiveQuery('restore', 'abcd')),
        (['find', '漫画', 'MoRui'], ArchiveQuery(keyword='漫画 MoRui')),
        (['list', '2', 'find', '漫画'], ArchiveQuery(page=2, keyword='漫画')),
        (['LIST', 'FIND', 'all', 'next', 'find'], ArchiveQuery(keyword='all next find')),
    ],
)
def test_archive_syntax_shared_by_interactive_and_direct_commands(args, expected):
    assert parse_archive_query(args) == expected
    assert main_module._parse_command(['archive', *args])[1:] == ('archive', args)


@pytest.mark.parametrize(
    'args',
    [
        ['all'],
        ['../test'],
        ['restore'],
        ['show'],
        ['show', 'abcd', '0'],
        ['list', '0'],
        ['list', '-1'],
        ['list', 'next'],
        ['list', '1', 'extra'],
        ['abcd', 'extra'],
        ['restore', 'abcd', 'extra'],
        ['show', 'abc'],
        ['find'],
        ['list', '2', 'find'],
        ['list', '0', 'find', '漫画'],
        ['list', '2', 'extra', 'find', '漫画'],
        ['abcd', 'find', '漫画'],
        ['show', 'abcd', 'find', '漫画'],
        ['restore', 'abcd', 'find', '漫画'],
        ['next'],
        ['prev'],
        ['next', 'find', '漫画'],
    ],
)
def test_invalid_archive_syntax_fails_before_shell_creation(args):
    with pytest.raises(main_module.CommandUsageError):
        main_module._parse_command(['archive', *args])


@pytest.mark.parametrize(
    'query', [ArchiveQuery(page=2, keyword='漫画 MoRui'), ArchiveQuery('show', 'abcd', 2)]
)
def test_archive_relative_navigation_preserves_list_or_detail_context(query):
    assert parse_archive_query(['next'], query) == replace(query, page=3)
    assert parse_archive_query(['PREV'], query) == replace(query, page=1)
    with pytest.raises(ValueError, match='第一页'):
        parse_archive_query(['prev'], replace(query, page=1))
    for args in (['next', '2'], ['prev', 'find', '漫画']):
        with pytest.raises(ValueError):
            parse_archive_query(args, query)


def test_archive_mutations_cannot_be_repeated_by_relative_navigation():
    for action in ('archive', 'restore'):
        with pytest.raises(ValueError):
            parse_archive_query(['next'], ArchiveQuery(action, 'abcd'))


def test_direct_cli_archive_list_show_restore_round_trip(completed_plan):
    store, job = completed_plan
    commands = [
        ([job.id[:12]], '已归档'),
        ([], '已归档计划'),
        (['find', '归档', 'TEST'], '匹配 1 / 1 项'),
        (['find', job.id[:12]], '匹配 1 / 1 项'),
        (['find', '不匹配'], '没有符合查找条件的归档'),
        (['show', job.id[:12]], '归档计划详情'),
        (['restore', job.id[:12]], '已恢复到任务列表'),
    ]
    for args, expected in commands:
        result = subprocess.run(  # noqa: S603 - fixed CLI and local fixture data
            [sys.executable, '-X', 'utf8', 'main.py', store.output_path, 'archive', *args],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout
    assert store.load(job.id).state == 'completed'
