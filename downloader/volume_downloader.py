from __future__ import annotations

import os
from typing import Any

from loguru import logger
from rich.progress import Progress

from downloader.models import VolumeDownloadResult, filter_dir_name


def download_volume(
    source: Any,
    path: str,
    vol_name: str,
    url: str,
    parent_progress: Progress | None = None,
) -> VolumeDownloadResult:
    logger.info('开始下载卷/话: {} 从 {}', vol_name, url)

    existing_archive_path = source._find_existing_archive(path, vol_name)
    if existing_archive_path:
        logger.info('文件已存在，跳过: {}', existing_archive_path)
        return VolumeDownloadResult(
            name=vol_name,
            url=url,
            status='skipped',
            archive_path=existing_archive_path,
            message='文件已存在',
        )

    parse_task_id = None
    if parent_progress:
        parse_task_id = parent_progress.add_task(
            description=f'[yellow]正在解析 {vol_name} 图片...',
            total=None,
        )
    else:
        print(f'正在解析 {vol_name} 图片...')

    try:
        imgs = source.parse_images(url)
        source._remove_progress_task(parent_progress, parse_task_id)
        parse_task_id = None

        if not imgs:
            logger.warning('未解析到任何图片: {} ({})', vol_name, url)
            return VolumeDownloadResult(
                name=vol_name,
                url=url,
                status='failed',
                message='未解析到任何图片',
            )

        target_path = os.path.join(path, filter_dir_name(vol_name))
        result = source.__download_vol_images__(
            target_path,
            vol_name,
            url,
            imgs,
            parent_progress,
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
        return result
    except Exception as e:
        source._remove_progress_task(parent_progress, parse_task_id)
        logger.error('处理卷/话失败: {} ({}), 错误: {}', vol_name, url, e, exc_info=True)
        return VolumeDownloadResult(name=vol_name, url=url, status='failed', message=str(e))
