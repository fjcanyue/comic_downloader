from __future__ import annotations

import os
from typing import Any

from loguru import logger

from downloader.download.progress import DownloadProgress, ensure_download_progress
from downloader.models import VolumeDownloadResult, filter_dir_name


def download_volume(
    source: Any,
    path: str,
    vol_name: str,
    url: str,
    parent_progress: DownloadProgress | Any | None = None,
) -> VolumeDownloadResult:
    logger.info('开始下载卷/话: {} 从 {}', vol_name, url)

    target_path = os.path.join(path, filter_dir_name(vol_name))
    task_id = _start_download_task(source, target_path, vol_name, url)
    existing_archive_path = source._find_existing_archive(path, vol_name)
    if existing_archive_path:
        logger.info('文件已存在，跳过: {}', existing_archive_path)
        result = VolumeDownloadResult(
            name=vol_name,
            url=url,
            status='skipped',
            archive_path=existing_archive_path,
            message='文件已存在',
        )
        _finish_download_task(source, task_id, result)
        return result

    progress = ensure_download_progress(parent_progress)
    parse_task_id = progress.add_task(
        description=f'[yellow]解析章节图片 · {vol_name}',
        total=None,
    )

    try:
        imgs = source.parse_images(url)
        source._remove_progress_task(progress, parse_task_id)
        parse_task_id = None

        if not imgs:
            logger.warning('未解析到任何图片: {} ({})', vol_name, url)
            result = VolumeDownloadResult(
                name=vol_name,
                url=url,
                status='failed',
                message='未解析到任何图片',
            )
            _finish_download_task(source, task_id, result)
            return result

        _update_download_task_images(source, task_id, imgs)
        result = source.__download_vol_images__(
            target_path,
            vol_name,
            url,
            imgs,
            progress,
        )
        if result.ok:
            logger.info('卷/话 {} 下载完成.', vol_name)
        else:
            logger.warning(
                '卷/话 {} 下载未完全成功: 状态={}, 成功图片={}/{}',
                vol_name,
                result.status,
                result.downloaded_count,
                result.image_count,
            )
        _finish_download_task(source, task_id, result)
        return result
    except Exception as e:
        source._remove_progress_task(progress, parse_task_id)
        logger.error('处理卷/话失败: {} ({}), 错误: {}', vol_name, url, e, exc_info=True)
        result = VolumeDownloadResult(name=vol_name, url=url, status='failed', message=str(e))
        _finish_download_task(source, task_id, result)
        return result


def _start_download_task(
    source: Any, target_path: str, volume_name: str, source_url: str
) -> str | None:
    start_task = getattr(source, '_start_download_task', None)
    if not callable(start_task):
        return None
    task_id = start_task(target_path, volume_name, source_url)
    return task_id if isinstance(task_id, str) else None


def _update_download_task_images(source: Any, task_id: str | None, image_urls: list[str]) -> None:
    update_task = getattr(source, '_update_download_task_images', None)
    if callable(update_task):
        update_task(task_id, image_urls)


def _finish_download_task(source: Any, task_id: str | None, result: VolumeDownloadResult) -> None:
    finish_task = getattr(source, '_finish_download_task', None)
    if callable(finish_task):
        finish_task(task_id, result)
