"""Durable download plans; chapter execution stays in the source pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import groupby
from typing import TYPE_CHECKING
from uuid import uuid4

from loguru import logger

from downloader.models import ComicVolume, DownloadSummary, VolumeDownloadResult

if TYPE_CHECKING:
    from downloader.comic import ComicSource
    from downloader.download.job_store import JobStore

JOB_STATES = {'pending', 'running', 'interrupted', 'failed', 'completed'}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class JobVolume:
    book_name: str
    name: str
    url: str
    result: VolumeDownloadResult | None = None

    @property
    def complete(self) -> bool:
        return self.result is not None and self.result.ok


@dataclass
class DownloadJob:
    source_name: str
    comic_name: str
    comic_url: str
    volumes: list[JobVolume]
    id: str = field(default_factory=lambda: uuid4().hex)
    version: int = 1
    state: str = 'pending'
    created_at: str = field(default_factory=timestamp)
    updated_at: str = field(default_factory=timestamp)
    error: str = ''

    @property
    def remaining(self) -> list[JobVolume]:
        return [volume for volume in self.volumes if not volume.complete]

    @property
    def summary(self) -> DownloadSummary:
        return DownloadSummary([volume.result for volume in self.volumes if volume.result])


def run_download_job(store: JobStore, job_id: str, source: ComicSource | None) -> DownloadJob:
    """Lock and reload the plan; persist each completed attempt before proceeding."""
    with store.lock(job_id):
        job = store.load(job_id)
        remaining = job.remaining
        if not remaining:
            if job.state != 'completed':
                job.state = 'completed'
                job.error = ''
                store.save(job)
            return job
        if source is None:
            raise ValueError('未完成任务需要可用的下载源。')
        job.state = 'running'
        job.error = ''
        store.save(job)
        try:
            for book_name, group in groupby(remaining, key=lambda volume: volume.book_name):
                _download_group(store, job, source, book_name, list(group))
            job.state = 'failed' if job.remaining else 'completed'
            store.save(job)
        except (KeyboardInterrupt, SystemExit):
            _save_stopped_job(store, job, 'interrupted', '下载被中断，可继续未完成章节。')
            raise
        except Exception as exc:
            _save_stopped_job(store, job, 'failed', str(exc))
            raise
        return job


def _download_group(
    store: JobStore,
    job: DownloadJob,
    source: ComicSource,
    book_name: str,
    volumes: list[JobVolume],
) -> None:
    completed = 0

    def record(result: VolumeDownloadResult) -> None:
        nonlocal completed
        volume = volumes[completed]
        if result.url != volume.url or result.name != volume.name:
            raise ValueError('下载结果与保存的章节计划不匹配。')
        volume.result = result
        store.save(job)
        completed += 1

    source.download_vols(
        job.comic_name,
        book_name,
        [ComicVolume(volume.name, volume.url) for volume in volumes],
        on_result=record,
    )
    if completed != len(volumes):
        raise RuntimeError('下载未返回全部章节结果，未完成章节可通过 retry 继续。')


def _save_stopped_job(store: JobStore, job: DownloadJob, state: str, error: str) -> None:
    job.state = state
    job.error = error
    try:
        store.save(job)
    except (OSError, ValueError):
        # Retain the original failure/interrupt. The previous atomic checkpoint is recoverable.
        logger.exception('保存任务状态失败；保留上次记录: {}', job.id)
