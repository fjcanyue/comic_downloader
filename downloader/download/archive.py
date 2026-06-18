from __future__ import annotations

import os
import re
import shutil

from loguru import logger

from downloader.download.progress import DownloadProgress
from downloader.models import (
    ImageDownloadFailure,
    VolumeDownloadResult,
    VolumeFileState,
    filter_dir_name,
)


class ArchiveMixin:
    def _find_existing_archive(self, path: str, vol_name: str) -> str | None:
        if self.overwrite:
            return None

        target_zip_name = filter_dir_name(vol_name) + '.zip'
        target_zip_path = os.path.join(path, target_zip_name)
        if os.path.exists(target_zip_path):
            return target_zip_path

        base_name = filter_dir_name(vol_name)
        match = re.match(r'^(\d+)(.*)$', base_name)
        if not match:
            return None

        num_part = match.group(1)
        rest_part = match.group(2)
        for i in range(1, 3):
            padded_num = num_part.zfill(len(num_part) + i)
            padded_path = os.path.join(path, padded_num + rest_part + '.zip')
            if os.path.exists(padded_path):
                logger.info('文件已存在(补零匹配)，跳过: {}', padded_path)
                return padded_path
        return None

    def _remove_progress_task(self, progress: DownloadProgress | None, task_id) -> None:
        if progress is None or task_id is None:
            return
        try:
            progress.remove_task(task_id)
        except KeyError:
            logger.debug('进度任务已被移除: {task_id}', task_id=task_id)

    def _finalize_volume_download(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
    ) -> VolumeDownloadResult:
        if not os.path.exists(path):
            return self._failed_volume_result(
                vol_name, source_url, expected_count, failed_images, '目录不存在'
            )
        if not os.listdir(path):
            return self._failed_volume_result(
                vol_name, source_url, expected_count, failed_images, '目录为空'
            )
        return self._finalize_existing_download_dir(
            path, vol_name, source_url, expected_count, failed_images
        )

    def _finalize_existing_download_dir(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
    ) -> VolumeDownloadResult:
        actual_files = sorted(os.listdir(path))
        actual_count = len(actual_files)
        downloaded_count = expected_count - len(failed_images)
        if expected_count == actual_count and not failed_images:
            return self._archive_volume(
                path, vol_name, source_url, expected_count, downloaded_count
            )
        return self._partial_volume_result(
            path,
            vol_name,
            source_url,
            expected_count,
            VolumeFileState(
                downloaded_count=downloaded_count,
                failed_images=failed_images,
                actual_files=actual_files,
                actual_count=actual_count,
            ),
        )

    def _archive_volume(
        self, path: str, vol_name: str, source_url: str, expected_count: int, downloaded_count: int
    ) -> VolumeDownloadResult:
        logger.info('开始压缩目录: {}', path)
        try:
            archive_path = shutil.make_archive(path, 'zip', path)
            logger.info('目录 {} 压缩完成.', path)
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='downloaded',
                image_count=expected_count,
                downloaded_count=downloaded_count,
                archive_path=archive_path,
            )
        except Exception as e:
            logger.error('压缩目录失败: {}, 错误: {}', path, e, exc_info=True)
            return VolumeDownloadResult(
                name=vol_name,
                url=source_url,
                status='failed',
                image_count=expected_count,
                downloaded_count=downloaded_count,
                message=f'压缩目录失败: {e}',
            )

    def _partial_volume_result(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        expected_count: int,
        file_state: VolumeFileState,
    ) -> VolumeDownloadResult:
        missing_files = self._missing_image_files(expected_count, file_state.actual_files)
        logger.warning(
            '目录 {} 图片数量不匹配，跳过压缩. 预期 {} 张，实际 {} 张. 缺少文件: {}',
            path,
            expected_count,
            file_state.actual_count,
            missing_files,
        )
        status = 'partial' if file_state.downloaded_count > 0 else 'failed'
        return VolumeDownloadResult(
            name=vol_name,
            url=source_url,
            status=status,
            image_count=expected_count,
            downloaded_count=file_state.downloaded_count,
            failed_images=file_state.failed_images,
            message='图片数量不匹配，跳过压缩',
        )

    def _missing_image_files(self, expected_count: int, actual_files: list[str]) -> list[str]:
        return [
            f'{index:04d}.jpg'
            for index in range(1, expected_count + 1)
            if f'{index:04d}.jpg' not in actual_files
        ]

    def _failed_volume_result(
        self,
        vol_name: str,
        source_url: str,
        expected_count: int,
        failed_images: list[ImageDownloadFailure],
        message: str,
    ) -> VolumeDownloadResult:
        logger.warning('{}, 跳过压缩.', message)
        return VolumeDownloadResult(
            name=vol_name,
            url=source_url,
            status='failed',
            image_count=expected_count,
            downloaded_count=0,
            failed_images=failed_images,
            message=message,
        )
