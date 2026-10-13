"""Read-only task browsing: compact summaries, filters, and command syntax."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from os.path import commonprefix

from downloader.download.jobs import JOB_STATES, DownloadJob, JobVolume

TASK_PAGE_SIZE = 20
TASK_VOLUME_PAGE_SIZE = 30
LIST_FILTERS = JOB_STATES | {'all', 'unfinished'}
VOLUME_FILTERS = {'all', 'unfinished', 'failed', 'completed', 'pending'}
TASK_FILTER_LABELS = {
    'all': '全部',
    'unfinished': '未完成',
    'failed': '有失败',
    'completed': '已完成',
    'pending': '待下载',
    'running': '未结束',
    'interrupted': '已中断',
}
TASK_USAGE = (
    'tasks [状态] [页码]；tasks <任务ID> [状态] [页码]；'
    'tasks next / prev 连续翻页。状态：all / unfinished / failed / completed / pending；'
    '任务列表另支持 running / interrupted。'
)


@dataclass(frozen=True)
class JobSummary:
    id: str
    comic_name: str
    source_name: str
    state: str
    updated_at: str
    total: int
    remaining: int

    @classmethod
    def from_job(cls, job: DownloadJob) -> JobSummary:
        return cls(
            job.id,
            job.comic_name,
            job.source_name,
            job.state,
            job.updated_at,
            len(job.volumes),
            sum(not volume.complete for volume in job.volumes),
        )


@dataclass(frozen=True)
class TaskQuery:
    job_id: str | None = None
    status: str = 'all'
    page: int = 1


def parse_task_query(args: list[str], current: TaskQuery | None = None) -> TaskQuery:
    """Keep hex IDs (including numeric prefixes) distinct from explicit list pages."""
    tokens = [arg.casefold() for arg in args]
    if not tokens:
        return TaskQuery()
    if tokens[0] in {'next', 'prev'}:
        if len(tokens) != 1 or current is None:
            raise ValueError('请先使用 tasks 或 tasks <任务ID> 打开列表，再连续翻页。')
        page = current.page + (1 if tokens[0] == 'next' else -1)
        if page < 1:
            raise ValueError('已是第一页。')
        return replace(current, page=page)
    job_id = None
    if tokens[0] not in LIST_FILTERS:
        job_id = tokens.pop(0)
        if not re.fullmatch(r'[0-9a-f]{4,32}', job_id):
            raise ValueError(TASK_USAGE)
    status = 'all'
    if tokens and tokens[0] in LIST_FILTERS:
        status = tokens.pop(0)
    if job_id and status not in VOLUME_FILTERS:
        raise ValueError('章节筛选支持 all / unfinished / failed / completed / pending。')
    if len(tokens) > 1 or (tokens and (not tokens[0].isdecimal() or int(tokens[0]) < 1)):
        raise ValueError('页码必须是正整数。' + TASK_USAGE)
    return TaskQuery(job_id, status, int(tokens[0]) if tokens else 1)


def matching_jobs(jobs: list[JobSummary], status: str) -> list[JobSummary]:
    if status == 'all':
        return jobs
    if status == 'unfinished':
        return [job for job in jobs if job.remaining]
    return [job for job in jobs if job.state == status]


def matching_volumes(job: DownloadJob, status: str) -> list[int]:
    return [index for index, volume in enumerate(job.volumes) if _matches_volume(volume, status)]


def _matches_volume(volume: JobVolume, status: str) -> bool:
    if status == 'all':
        return True
    if status == 'unfinished':
        return not volume.complete
    if status == 'completed':
        return volume.complete
    if status == 'pending':
        return volume.result is None
    return volume.result is not None and volume.result.status in {'failed', 'partial'}


def unique_job_prefixes(jobs: list[JobSummary]) -> dict[str, str]:
    """Lengthen colliding 12-digit labels, considering every job before filtering."""
    ids = sorted(job.id for job in jobs)
    prefixes = {}
    for index, job_id in enumerate(ids):
        neighbors = ids[max(0, index - 1) : index] + ids[index + 1 : index + 2]
        length = max([12, *(len(commonprefix([job_id, other])) + 1 for other in neighbors)])
        prefixes[job_id] = job_id[:length]
    return prefixes
