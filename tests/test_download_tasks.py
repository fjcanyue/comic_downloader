from __future__ import annotations

import json
from dataclasses import replace

import pytest

from downloader.download.tasks import (
    DownloadTask,
    DownloadTaskStore,
    DownloadTaskStoreError,
)
from downloader.models import ImageDownloadFailure, VolumeDownloadResult


def test_task_store_persists_failed_task_and_completes_same_task_on_retry(tmp_path):
    store = DownloadTaskStore(tmp_path)
    target_path = tmp_path / 'comic' / 'book' / 'chapter'

    first = store.start(
        source_name='morui',
        volume_name='chapter',
        source_url='https://example.test/chapter',
        target_path=target_path,
    )
    store.update_images(first.task_id, ['https://example.test/0001.jpg'])
    store.finish(
        first.task_id,
        VolumeDownloadResult(
            name='chapter',
            url='https://example.test/chapter',
            status='failed',
            failed_images=[
                ImageDownloadFailure(
                    index=1,
                    url='https://example.test/0001.jpg',
                    file_path=str(target_path / '0001.jpg'),
                    error='invalid image',
                )
            ],
            message='invalid image',
        ),
    )

    reloaded = DownloadTaskStore(tmp_path)
    pending = reloaded.list_pending()
    assert len(pending) == 1
    assert pending[0].task_id == first.task_id
    assert pending[0].status == 'failed'
    assert pending[0].image_urls == ('https://example.test/0001.jpg',)
    assert pending[0].failed_count == 1

    second = reloaded.start(
        source_name='morui',
        volume_name='chapter',
        source_url='https://example.test/chapter',
        target_path=target_path,
    )
    reloaded.finish(
        second.task_id,
        VolumeDownloadResult(
            name='chapter',
            url='https://example.test/chapter',
            status='downloaded',
            archive_path=str(tmp_path / 'comic' / 'book' / 'chapter.zip'),
        ),
    )

    completed = reloaded.get(first.task_id)
    assert completed is not None
    assert completed.status == 'completed'
    assert completed.attempts == 2
    assert reloaded.list_pending() == []


def test_task_store_uses_relative_paths_and_atomic_json(tmp_path):
    store = DownloadTaskStore(tmp_path)
    target_path = tmp_path / 'comic' / 'book' / 'chapter'

    task = store.start(
        source_name='morui',
        volume_name='chapter',
        source_url='https://example.test/chapter',
        target_path=target_path,
    )

    raw = json.loads(store.store_path.read_text(encoding='utf-8'))
    assert raw['version'] == 1
    assert raw['tasks'][0]['target_path'] == 'comic/book/chapter'
    assert task.target_path == 'comic/book/chapter'
    assert list(store.store_dir.glob('*.tmp')) == []


def test_task_store_rejects_targets_outside_output_directory(tmp_path):
    store = DownloadTaskStore(tmp_path / 'downloads')

    with pytest.raises(DownloadTaskStoreError, match='下载目录内'):
        store.start(
            source_name='morui',
            volume_name='chapter',
            source_url='https://example.test/chapter',
            target_path=tmp_path / 'outside' / 'chapter',
        )


def test_task_store_revalidates_persisted_target_before_retry(tmp_path):
    store = DownloadTaskStore(tmp_path)
    task = DownloadTask(
        task_id='unsafe',
        source_name='morui',
        volume_name='chapter',
        source_url='https://example.test/chapter',
        target_path='comic/book/chapter',
    )

    with pytest.raises(DownloadTaskStoreError, match='章节名称不匹配'):
        store.resolve_target_path(replace(task, target_path='comic/book/not-chapter'))

    with pytest.raises(DownloadTaskStoreError, match='超出下载目录'):
        store.resolve_target_path(replace(task, target_path='../outside/chapter'))


def test_task_store_reports_corrupt_json_without_overwriting_it(tmp_path):
    store = DownloadTaskStore(tmp_path)
    store.store_dir.mkdir(parents=True)
    store.store_path.write_text('{broken', encoding='utf-8')

    with pytest.raises(DownloadTaskStoreError, match='读取失败'):
        store.list_pending()

    assert store.store_path.read_text(encoding='utf-8') == '{broken'
