"""Atomic JSON records and OS-backed locks for resumable download jobs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from downloader.download.job_browser import JobSummary
from downloader.download.jobs import JOB_STATES, DownloadJob, JobVolume, timestamp
from downloader.models import ImageDownloadFailure, VolumeDownloadResult

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class JobStore:
    def __init__(self, output_path: str, *, archived: bool = False):
        self.output_path = str(Path(output_path).resolve())
        self.lock_directory = Path(self.output_path) / '.comic_downloader' / 'jobs'
        self.directory = self.lock_directory / 'archive' if archived else self.lock_directory
        self._summaries: dict[Path, tuple[tuple[int, int, int, int], JobSummary]] = {}
        self._archive_store: JobStore | None = None

    def archive_view(self) -> JobStore:
        if self._archive_store is None:
            self._archive_store = JobStore(self.output_path, archived=True)
        return self._archive_store

    def archive(self, job_id: str) -> DownloadJob:
        return self._move_record(job_id, restoring=False)

    def restore(self, job_id: str) -> DownloadJob:
        return self._move_record(job_id, restoring=True)

    def _move_record(self, job_id: str, *, restoring: bool) -> DownloadJob:
        active = JobStore(self.output_path)
        archived = self.archive_view()
        source, destination = (archived, active) if restoring else (active, archived)
        job = source.load(job_id)
        with active.lock(job.id):
            # Reload after locking: another process may have moved or changed the plan.
            job = source.load(job.id)
            if not restoring and (job.state != 'completed' or job.remaining):
                raise ValueError('只能归档已完成的计划；未完成任务请先使用 retry 恢复。')
            destination.directory.mkdir(parents=True, exist_ok=True)
            target = destination.directory / f'{job.id}.json'
            if target.exists():
                raise ValueError('目标位置已存在相同 ID 的任务，未覆盖任何记录。')
            original = source.directory / f'{job.id}.json'
            # Both directories share the output filesystem and the same per-ID OS lock.
            original.rename(target)
            self._summaries.pop(original, None)
            self._summaries.pop(target, None)
        return job

    def save(self, job: DownloadJob) -> None:
        self._validate_id(job.id)
        job.updated_at = timestamp()
        data = asdict(job)
        _decode_job(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.directory,
                suffix='.tmp',
                delete=False,
            ) as stream:
                tmp_path = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, self.directory / f'{job.id}.json')
            self._summaries.pop(self.directory / f'{job.id}.json', None)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def load(self, job_id: str) -> DownloadJob:
        """Accept a full ID or an unambiguous prefix, never a filesystem path."""
        if not re.fullmatch(r'[0-9a-f]{4,32}', job_id):
            raise ValueError('任务 ID 应为至少 4 位的十六进制前缀；输入 tasks 查看。')
        matches = list(self.directory.glob(f'{job_id}*.json'))
        if not matches:
            if self.directory != self.lock_directory:
                raise ValueError('没有找到归档计划，请检查保存路径，或输入 archive 查看记录。')
            raise ValueError('没有找到任务，请检查保存路径，或输入 tasks 查看记录。')
        if len(matches) != 1:
            raise ValueError('任务 ID 前缀匹配多个任务，请输入更长的 ID。')
        return self._read(matches[0])

    def list_jobs(self) -> tuple[list[DownloadJob], list[str]]:
        jobs, errors = [], []
        for path in self.directory.glob('*.json'):
            try:
                jobs.append(self._read(path))
            except (ValueError, OSError) as exc:  # noqa: PERF203 - isolate corrupt records
                errors.append(f'{path.name}: {exc}')
        return sorted(jobs, key=lambda job: (job.updated_at, job.id), reverse=True), errors

    def list_summaries(self) -> tuple[list[JobSummary], list[str]]:
        """Re-scan metadata each time; retain no chapter/image lists between reads."""
        summaries, errors = [], []
        paths = set(self.directory.glob('*.json'))
        for stale in self._summaries.keys() - paths:
            del self._summaries[stale]
        for path in sorted(paths):
            try:
                before = self._signature(path)
                cached = self._summaries.get(path)
                if cached is not None and cached[0] == before:
                    summaries.append(cached[1])
                    continue
                summary = JobSummary.from_job(self._read(path))
                # A concurrent atomic replacement must not tag old data with new metadata.
                if self._signature(path) == before:
                    self._summaries[path] = (before, summary)
                else:
                    self._summaries.pop(path, None)
                summaries.append(summary)
            except (ValueError, OSError) as exc:
                self._summaries.pop(path, None)
                errors.append(f'{path.name}: {exc}')
        return sorted(summaries, key=lambda job: (job.updated_at, job.id), reverse=True), errors

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino

    @contextmanager
    def lock(self, job_id: str):
        """The OS releases locks on process exit, including forced termination."""
        self._validate_id(job_id)
        self.lock_directory.mkdir(parents=True, exist_ok=True)
        with (self.lock_directory / f'{job_id}.lock').open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                _lock_file(stream.fileno())
            except OSError as exc:
                raise ValueError('该任务正在其他进程中执行，请稍后再试。') from exc
            try:
                yield
            finally:
                _unlock_file(stream.fileno())

    @staticmethod
    def _validate_id(job_id: str) -> None:
        if not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise ValueError('无效的任务 ID。')

    def _read(self, path: Path) -> DownloadJob:
        try:
            self._validate_id(path.stem)
            data = json.loads(path.read_text(encoding='utf-8'))
            job = _decode_job(data)
            if job.id != path.stem:
                raise ValueError('任务 ID 与文件名不匹配')
            return job
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise ValueError(f'任务记录损坏或版本不支持：{exc}') from exc


def _decode_job(data: dict) -> DownloadJob:
    if type(data['version']) is not int or data['version'] != 1 or data['state'] not in JOB_STATES:
        raise ValueError('不支持的版本或状态')
    for key in ('source_name', 'comic_name', 'id', 'created_at', 'updated_at'):
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(f'无效的 {key}')
    if not isinstance(data['comic_url'], str) or not isinstance(data['error'], str):
        raise ValueError('无效的 URL 或错误信息')
    if not isinstance(data['volumes'], list) or not data['volumes']:
        raise ValueError('缺少章节计划')
    volumes = [_decode_volume(volume) for volume in data['volumes']]
    job = DownloadJob(**{**data, 'volumes': volumes})
    if job.state == 'completed' and job.remaining:
        raise ValueError('已完成任务仍有未完成章节')
    return job


def _decode_volume(data: dict) -> JobVolume:
    for key in ('book_name', 'name', 'url'):
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(f'无效的章节 {key}')
    raw_result = data['result']
    result = None
    if raw_result is not None:
        failed_images = [ImageDownloadFailure(**item) for item in raw_result['failed_images']]
        result = VolumeDownloadResult(**{**raw_result, 'failed_images': failed_images})
        if result.status not in {'downloaded', 'skipped', 'partial', 'failed'}:
            raise ValueError('无效的章节状态')
        if result.name != data['name'] or result.url != data['url']:
            raise ValueError('章节结果与计划不一致')
        if any(
            type(value) is not int or value < 0
            for value in (
                result.image_count,
                result.downloaded_count,
            )
        ):
            raise ValueError('无效的图片数量')
        if result.message is not None and not isinstance(result.message, str):
            raise ValueError('无效的章节错误信息')
        if result.archive_path is not None and not isinstance(result.archive_path, str):
            raise ValueError('无效的压缩包路径')
        for failure in failed_images:
            if (
                type(failure.index) is not int
                or failure.index < 1
                or not all(
                    isinstance(value, str)
                    for value in (failure.url, failure.file_path, failure.error)
                )
            ):
                raise ValueError('无效的失败图片记录')
    return JobVolume(**{**data, 'result': result})


def _lock_file(descriptor: int) -> None:
    if os.name == 'nt':
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(descriptor: int) -> None:
    if os.name == 'nt':
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
