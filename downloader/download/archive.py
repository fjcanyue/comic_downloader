from __future__ import annotations

import os
import re
import tempfile
import zipfile
import zlib
from pathlib import Path

from loguru import logger

from downloader.download.progress import DownloadProgress
from downloader.models import (
    ImageDownloadFailure,
    VolumeDownloadResult,
    VolumeFileState,
    filter_dir_name,
)


class ArchiveMixin:
    overwrite: bool

    def _find_existing_archive(self, path: str, vol_name: str) -> str | None:
        if self.overwrite:
            return None

        target_zip_name = filter_dir_name(vol_name) + '.zip'
        target_zip_path = os.path.join(path, target_zip_name)
        if self._archive_is_usable(target_zip_path):
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
            if self._archive_is_usable(padded_path):
                logger.info('文件已存在(补零匹配)，跳过: {}', padded_path)
                return padded_path
        return None

    @staticmethod
    def _archive_is_usable(path: str) -> bool:
        if not os.path.isfile(path):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                files = [info for info in archive.infolist() if not info.is_dir()]
                if (
                    files
                    and all(info.file_size > 0 for info in files)
                    and archive.testzip() is None
                ):
                    return True
        except (
            OSError,
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            EOFError,
            zlib.error,
        ):
            logger.warning('无法读取已有压缩包，将重新处理章节: {}', path)
            return False
        logger.warning('已有压缩包为空或校验失败，将重新处理章节: {}', path)
        return False

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
        expected_files = [f'{index:04d}.jpg' for index in range(1, expected_count + 1)]
        actual_files = [
            name
            for name in expected_files
            if os.path.isfile(os.path.join(path, name))
            and os.path.getsize(os.path.join(path, name)) > 0
        ]
        actual_count = len(actual_files)
        downloaded_count = min(actual_count, expected_count - len(failed_images))
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
        temporary_path = None
        try:
            target = Path(path).with_name(Path(path).name + '.zip')
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f'.{target.stem}-',
                suffix='.zip.tmp',
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
            with zipfile.ZipFile(temporary_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for index in range(1, expected_count + 1):
                    name = f'{index:04d}.jpg'
                    archive.write(Path(path) / name, arcname=name)
            os.replace(temporary_path, target)
            archive_path = str(target.resolve())
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
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

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
