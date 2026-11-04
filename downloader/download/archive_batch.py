"""Persistent, reviewable snapshots for explicitly confirmed batch archiving."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from downloader.download.job_browser import JobSummary, matching_jobs
from downloader.download.job_store import JobStore, job_fingerprint
from downloader.download.jobs import timestamp

ENTRY_STATES = {'pending', 'applying', 'archived', 'skipped', 'failed'}
BATCH_STATES = {'ready', 'running', 'finished', 'cancelled'}


@dataclass
class ArchiveEntry:
    summary: JobSummary
    digest: str
    status: str = 'pending'
    message: str = ''


@dataclass
class ArchiveBatch:
    id: str
    output_path: str
    keyword: str
    created_at: str
    entries: list[ArchiveEntry]
    errors: list[str] = field(default_factory=list)
    state: str = 'ready'
    version: int = 1

    @property
    def successful(self) -> bool:
        return (
            self.state == 'finished'
            and not self.errors
            and all(entry.status == 'archived' for entry in self.entries)
        )


class ArchiveBatchStore:
    def __init__(self, jobs: JobStore):
        self.jobs = jobs
        self.directory = jobs.lock_directory / 'archive_batches'

    def create(self, keyword: str = '') -> ArchiveBatch:
        summaries, errors = self.jobs.list_summaries()
        entries = []
        for summary in matching_jobs(summaries, 'completed', keyword):
            try:
                job = self.jobs.load(summary.id)
                current = JobSummary.from_job(job)
                if not matching_jobs([current], 'completed', keyword) or job.remaining:
                    errors.append(f'{summary.id}: 预览期间任务已变化，未纳入批次。')
                    continue
                entries.append(ArchiveEntry(current, job_fingerprint(job)))
            except (OSError, ValueError) as exc:
                errors.append(f'{summary.id}: {exc}')
        # Use the existing OS lock namespace, with a distinct randomly generated batch ID.
        batch_id = uuid.uuid4().hex
        while batch_id in {entry.summary.id for entry in entries} or self._path(batch_id).exists():
            batch_id = uuid.uuid4().hex
        batch = ArchiveBatch(batch_id, self.jobs.output_path, keyword, timestamp(), entries, errors)
        self._save(batch)
        return batch

    def load(self, batch_id: str) -> ArchiveBatch:
        path = self._path(batch_id)
        if not path.exists():
            raise ValueError('没有找到归档批次，请检查保存路径或使用 archive batch 重新预览。')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            entries = [
                ArchiveEntry(**{**entry, 'summary': JobSummary(**entry['summary'])})
                for entry in data.pop('entries')
            ]
            batch = ArchiveBatch(**data, entries=entries)
            self._validate(batch, batch_id)
            if batch.state == 'running':
                for index, entry in enumerate(batch.entries):
                    journal = self.directory / batch.id / f'{entry.summary.id}.json'
                    if journal.exists():
                        record = json.loads(journal.read_text(encoding='utf-8'))
                        restored = ArchiveEntry(
                            **{**record, 'summary': JobSummary(**record['summary'])}
                        )
                        if (
                            restored.summary != entry.summary
                            or restored.digest != entry.digest
                            or restored.status == 'pending'
                        ):
                            raise ValueError('执行记录与批次候选不一致')
                        batch.entries[index] = restored
                self._validate(batch, batch_id)
            return batch
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(f'归档批次损坏或版本不支持：{exc}') from exc

    def apply(self, batch_id: str) -> ArchiveBatch:
        self._path(batch_id)
        with self.jobs.lock(batch_id):
            batch = self.load(batch_id)
            if batch.state == 'cancelled':
                raise ValueError('该批次已取消，不会执行归档；请重新预览。')
            if batch.state == 'finished':
                return batch  # Never re-archive records that the user subsequently restored.
            batch.state = 'running'
            self._save(batch)
            for entry in batch.entries:
                if entry.status == 'applying':
                    self._recover_entry(entry)
                    self._save_entry(batch.id, entry)
                elif entry.status == 'pending':
                    entry.status = 'applying'
                    self._save_entry(batch.id, entry)  # Persist intent before moving a record.
                    self._apply_entry(entry)
                    self._save_entry(batch.id, entry)
            batch.state = 'finished'
            self._save(batch)
            return batch

    def list_batches(self) -> tuple[list[ArchiveBatch], list[str]]:
        batches, errors = [], []
        for path in self.directory.glob('*.json'):
            try:
                batches.append(self.load(path.stem))
            except (ValueError, OSError) as exc:  # noqa: PERF203 - isolate corrupt batch files
                errors.append(f'{path.name}: {exc}')
        return sorted(batches, key=lambda batch: (batch.created_at, batch.id), reverse=True), errors

    def cancel(self, batch_id: str) -> ArchiveBatch:
        self._path(batch_id)
        with self.jobs.lock(batch_id):
            batch = self.load(batch_id)
            if batch.state == 'cancelled':
                return batch
            if batch.state != 'ready':
                raise ValueError('只能取消尚未执行的批次；执行结果请用 archive batch show 查看。')
            batch.state = 'cancelled'
            self._save(batch)
            return batch

    def _apply_entry(self, entry: ArchiveEntry) -> None:
        try:
            self.jobs.archive(entry.summary.id, expected_digest=entry.digest)
            entry.status = 'archived'
            entry.message = ''
        except ValueError as exc:
            entry.status, entry.message = 'skipped', str(exc)
        except OSError as exc:
            entry.status, entry.message = 'failed', str(exc)

    def _recover_entry(self, entry: ArchiveEntry) -> None:
        """Resolve interrupted intent without repeating an ambiguous file move."""
        entry.status = 'skipped'
        entry.message = '上次执行中断，未重复移动此任务；请检查任务及归档后重新预览。'
        try:
            with self.jobs.lock(entry.summary.id):
                active_path = self.jobs.directory / f'{entry.summary.id}.json'
                archived = self.jobs.archive_view().load(entry.summary.id)
                if not active_path.exists() and job_fingerprint(archived) == entry.digest:
                    entry.status = 'archived'
                    entry.message = '中断恢复：已核对归档记录与原候选一致。'
        except (OSError, ValueError) as exc:
            entry.message += f'（核对失败：{exc}）'

    def _path(self, batch_id: str) -> Path:
        if not isinstance(batch_id, str) or not re.fullmatch(r'[0-9a-f]{32}', batch_id):
            raise ValueError('请使用预览中完整的 32 位批次 ID。')
        return self.directory / f'{batch_id}.json'

    def _save(self, batch: ArchiveBatch) -> None:
        self._write_json(self._path(batch.id), asdict(batch))

    def _save_entry(self, batch_id: str, entry: ArchiveEntry) -> None:
        # Per-entry journals avoid rewriting the entire candidate set for every task.
        self._write_json(self.directory / batch_id / f'{entry.summary.id}.json', asdict(entry))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _validate(self, batch: ArchiveBatch, batch_id: str) -> None:
        if type(batch.version) is not int or batch.version != 1 or batch.id != batch_id:
            raise ValueError('批次版本或 ID 无效')
        if not isinstance(batch.output_path, str) or os.path.normcase(
            batch.output_path
        ) != os.path.normcase(self.jobs.output_path):
            raise ValueError('批次不属于当前保存路径')
        if (
            batch.state not in BATCH_STATES
            or not isinstance(batch.keyword, str)
            or not isinstance(batch.created_at, str)
            or not isinstance(batch.errors, list)
            or not all(isinstance(error, str) for error in batch.errors)
        ):
            raise ValueError('批次元数据无效')
        ids = set()
        for entry in batch.entries:
            summary = entry.summary
            self._path(summary.id)
            if (
                summary.id == batch_id
                or summary.id in ids
                or summary.state != 'completed'
                or type(summary.total) is not int
                or summary.total < 1
                or type(summary.remaining) is not int
                or summary.remaining != 0
                or not all(
                    isinstance(value, str)
                    for value in (summary.comic_name, summary.source_name, summary.updated_at)
                )
                or not isinstance(entry.digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', entry.digest)
                or entry.status not in ENTRY_STATES
                or not isinstance(entry.message, str)
            ):
                raise ValueError('候选任务无效或重复')
            ids.add(summary.id)
        if batch.state == 'ready' and any(entry.status != 'pending' for entry in batch.entries):
            raise ValueError('未执行批次包含执行结果')
        if batch.state == 'finished' and any(
            entry.status in {'pending', 'applying'} for entry in batch.entries
        ):
            raise ValueError('已结束批次包含未结束任务')
