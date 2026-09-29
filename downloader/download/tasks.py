from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from downloader.download.volume import download_volume
from downloader.models import VolumeDownloadResult, filter_dir_name

TASK_STORE_VERSION = 1
TASK_STORE_DIRECTORY = '.comic_downloader'
TASK_STORE_FILENAME = 'tasks.json'
RETRYABLE_TASK_STATUSES = frozenset({'in_progress', 'failed', 'partial'})
KNOWN_TASK_STATUSES = RETRYABLE_TASK_STATUSES | {'completed'}
TASK_ID_PATTERN = re.compile(r'^[0-9a-f]{12}$')


class DownloadTaskStoreError(Exception):
    pass


@dataclass(frozen=True)
class DownloadTask:
    task_id: str
    source_name: str
    volume_name: str
    source_url: str
    target_path: str
    image_urls: tuple[str, ...] = ()
    status: str = 'in_progress'
    attempts: int = 1
    failed_count: int = 0
    message: str | None = None
    archive_path: str | None = None
    created_at: str = ''
    updated_at: str = ''

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_TASK_STATUSES

    @classmethod
    def from_mapping(cls, raw: Any) -> DownloadTask:
        if not isinstance(raw, dict):
            raise DownloadTaskStoreError('任务记录必须是 JSON 对象。')
        try:
            image_urls = raw.get('image_urls', [])
            if not isinstance(image_urls, list) or not all(
                isinstance(url, str) for url in image_urls
            ):
                raise DownloadTaskStoreError('任务的 image_urls 必须是字符串数组。')
            task_id = str(raw['task_id'])
            status = str(raw.get('status', 'in_progress'))
            if not TASK_ID_PATTERN.fullmatch(task_id):
                raise DownloadTaskStoreError('任务 ID 格式无效。')
            if status not in KNOWN_TASK_STATUSES:
                raise DownloadTaskStoreError(f'未知任务状态: {status}')
            return cls(
                task_id=task_id,
                source_name=str(raw['source_name']),
                volume_name=str(raw['volume_name']),
                source_url=str(raw['source_url']),
                target_path=str(raw['target_path']),
                image_urls=tuple(image_urls),
                status=status,
                attempts=max(1, int(raw.get('attempts', 1))),
                failed_count=max(0, int(raw.get('failed_count', 0))),
                message=_optional_string(raw.get('message')),
                archive_path=_optional_string(raw.get('archive_path')),
                created_at=str(raw.get('created_at', '')),
                updated_at=str(raw.get('updated_at', '')),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DownloadTaskStoreError(f'任务记录字段无效: {exc}') from exc

    def to_mapping(self) -> dict[str, Any]:
        raw = asdict(self)
        raw['image_urls'] = list(self.image_urls)
        return raw


class DownloadTaskStore:
    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.store_dir = self.output_dir / TASK_STORE_DIRECTORY
        self.store_path = self.store_dir / TASK_STORE_FILENAME
        self._lock = threading.RLock()

    def list_all(self) -> list[DownloadTask]:
        with self._lock:
            tasks = self._load()
        return sorted(tasks.values(), key=lambda task: task.updated_at, reverse=True)

    def list_pending(self) -> list[DownloadTask]:
        return [task for task in self.list_all() if task.retryable]

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            return self._load().get(task_id)

    def start(
        self,
        *,
        source_name: str,
        volume_name: str,
        source_url: str,
        target_path: str | os.PathLike[str],
    ) -> DownloadTask:
        relative_target = self._relative_target_path(target_path)
        task_id = _task_id(source_name, source_url, relative_target)
        now = _timestamp()
        with self._lock:
            tasks = self._load()
            previous = tasks.get(task_id)
            task = DownloadTask(
                task_id=task_id,
                source_name=source_name,
                volume_name=volume_name,
                source_url=source_url,
                target_path=relative_target,
                image_urls=previous.image_urls if previous else (),
                status='in_progress',
                attempts=(previous.attempts + 1) if previous else 1,
                created_at=previous.created_at if previous else now,
                updated_at=now,
            )
            tasks[task_id] = task
            self._save(tasks)
        return task

    def update_images(self, task_id: str, image_urls: list[str]) -> DownloadTask | None:
        with self._lock:
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None:
                return None
            task = replace(task, image_urls=tuple(image_urls), updated_at=_timestamp())
            tasks[task_id] = task
            self._save(tasks)
            return task

    def finish(self, task_id: str, result: VolumeDownloadResult) -> DownloadTask | None:
        with self._lock:
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None:
                return None
            status = 'completed' if result.ok else result.status
            archive_path = self._relative_archive_path(result.archive_path)
            task = replace(
                task,
                status=status,
                failed_count=len(result.failed_images),
                message=result.message,
                archive_path=archive_path,
                updated_at=_timestamp(),
            )
            tasks[task_id] = task
            self._save(tasks)
            return task

    def resolve_target_path(self, task: DownloadTask) -> Path:
        target = (self.output_dir / Path(task.target_path)).resolve()
        try:
            target.relative_to(self.output_dir)
        except ValueError as exc:
            raise DownloadTaskStoreError('任务目标路径超出下载目录。') from exc
        expected_name = filter_dir_name(task.volume_name)
        if target.name != expected_name:
            raise DownloadTaskStoreError('任务目标目录与章节名称不匹配。')
        return target

    def _relative_target_path(self, target_path: str | os.PathLike[str]) -> str:
        target = Path(target_path).resolve()
        try:
            relative = target.relative_to(self.output_dir)
        except ValueError as exc:
            raise DownloadTaskStoreError('任务目标路径必须位于下载目录内。') from exc
        return relative.as_posix()

    def _relative_archive_path(self, archive_path: str | None) -> str | None:
        if not archive_path:
            return None
        archive = Path(archive_path).resolve()
        try:
            return archive.relative_to(self.output_dir).as_posix()
        except ValueError:
            logger.warning('归档路径超出下载目录，不写入任务记录: {}', archive)
            return None

    def _load(self) -> dict[str, DownloadTask]:
        if not self.store_path.exists():
            return {}
        try:
            with open(self.store_path, encoding='utf-8-sig') as task_file:
                raw = json.load(task_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise DownloadTaskStoreError(f'任务记录读取失败: {exc}') from exc
        if not isinstance(raw, dict) or raw.get('version') != TASK_STORE_VERSION:
            raise DownloadTaskStoreError('任务记录版本无效。')
        raw_tasks = raw.get('tasks', [])
        if not isinstance(raw_tasks, list):
            raise DownloadTaskStoreError('任务记录的 tasks 必须是数组。')
        tasks = [DownloadTask.from_mapping(item) for item in raw_tasks]
        if len({task.task_id for task in tasks}) != len(tasks):
            raise DownloadTaskStoreError('任务记录包含重复任务 ID。')
        return {task.task_id: task for task in tasks}

    def _save(self, tasks: dict[str, DownloadTask]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'version': TASK_STORE_VERSION,
            'tasks': [task.to_mapping() for task in tasks.values()],
        }
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.store_dir,
                prefix='tasks-',
                suffix='.tmp',
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write('\n')
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.store_path)
        except OSError as exc:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise DownloadTaskStoreError(f'任务记录写入失败: {exc}') from exc


class DownloadTaskMixin:
    output_dir: str
    _task_store_instance: DownloadTaskStore | None = None

    def _download_task_store(self) -> DownloadTaskStore:
        store = getattr(self, '_task_store_instance', None)
        if store is None:
            store = DownloadTaskStore(self.output_dir)
            self._task_store_instance = store
        return store

    def _download_task_source_name(self) -> str:
        profile = getattr(self, 'profile', None)
        source_name = getattr(profile, 'source_name', None)
        if source_name:
            return str(source_name)
        return self.__class__.__name__

    def _start_download_task(
        self, target_path: str, volume_name: str, source_url: str
    ) -> str | None:
        try:
            task = self._download_task_store().start(
                source_name=self._download_task_source_name(),
                volume_name=volume_name,
                source_url=source_url,
                target_path=target_path,
            )
            return task.task_id
        except DownloadTaskStoreError:
            logger.warning('无法创建下载任务记录。', exc_info=True)
            return None

    def _update_download_task_images(self, task_id: str | None, image_urls: list[str]) -> None:
        if task_id is None:
            return
        try:
            self._download_task_store().update_images(task_id, image_urls)
        except DownloadTaskStoreError:
            logger.warning('无法更新下载任务图片列表。', exc_info=True)

    def _finish_download_task(self, task_id: str | None, result: VolumeDownloadResult) -> None:
        if task_id is None:
            return
        try:
            self._download_task_store().finish(task_id, result)
        except DownloadTaskStoreError:
            logger.warning('无法完成下载任务记录。', exc_info=True)

    def retry_download_task(self, task: DownloadTask) -> VolumeDownloadResult:
        store = self._download_task_store()
        target_path = store.resolve_target_path(task)
        if task.source_name != self._download_task_source_name():
            raise DownloadTaskStoreError('任务所属动漫源与当前动漫源不一致。')
        return download_volume(
            self,
            str(target_path.parent),
            task.volume_name,
            task.source_url,
        )


def _task_id(source_name: str, source_url: str, relative_target: str) -> str:
    value = f'{source_name}\0{source_url}\0{relative_target}'.encode()
    return hashlib.sha256(value, usedforsecurity=False).hexdigest()[:12]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
