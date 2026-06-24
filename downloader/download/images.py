from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from urllib.parse import urljoin

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from downloader.browser.modes import SELENIUMBASE_MODE
from downloader.download.progress import DownloadProgress, ensure_download_progress
from downloader.models import (
    ImageDownloadCancelledError,
    ImageDownloadContext,
    ImageDownloadFailure,
    VolumeDownloadResult,
)

IMAGE_RETRY_STATUS_CODES = [400, 429, 500, 502, 503, 504]


class ImageDownloadMixin:
    def __download_vol_images__(
        self,
        path: str,
        vol_name: str,
        source_url: str,
        imgs: list[str],
        progress: DownloadProgress | None = None,
    ) -> VolumeDownloadResult:
        """下载图片"""
        logger.info('开始下载图片到目录: {} (共 {} 张)', path, len(imgs))
        os.makedirs(path, exist_ok=True)
        context = ImageDownloadContext(
            path=path,
            use_base_img_url=bool(self._source_base_img_url()),
            session_factory=self._create_image_http_session,
        )
        failed_images = self._run_image_downloads(context, imgs, progress, vol_name)
        return self._finalize_volume_download(path, vol_name, source_url, len(imgs), failed_images)

    def _run_image_downloads(
        self,
        context: ImageDownloadContext,
        imgs: list[str],
        progress: DownloadProgress | None,
        vol_name: str,
    ) -> list[ImageDownloadFailure]:
        progress = ensure_download_progress(progress)
        failed_images: list[ImageDownloadFailure] = []
        max_workers = max(1, min(self._source_max_download_workers(), len(imgs)))
        task_id = progress.add_task(description=f'[cyan]🖼  {vol_name}', total=len(imgs))
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        futures: list[concurrent.futures.Future] = []
        try:
            futures = [
                executor.submit(self._download_image, context, index, img_url_part)
                for index, img_url_part in enumerate(imgs)
            ]
            for future in concurrent.futures.as_completed(futures):
                failure = future.result()
                if failure:
                    failed_images.append(failure)
                progress.advance(task_id)
            executor.shutdown(wait=True)
        except (KeyboardInterrupt, SystemExit):
            context.cancel_event.set()
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            self._close_active_image_downloads(context)
            concurrent.futures.wait(futures, timeout=1)
            raise
        except ImageDownloadCancelledError as exc:
            context.cancel_event.set()
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            self._close_active_image_downloads(context)
            raise KeyboardInterrupt from exc
        except Exception:
            context.cancel_event.set()
            executor.shutdown(wait=True)
            raise
        finally:
            self._remove_progress_task(progress, task_id)
            self._close_image_http_sessions(context)
        return failed_images

    def _raise_if_image_download_cancelled(self, context: ImageDownloadContext) -> None:
        if context.cancel_event.is_set():
            raise ImageDownloadCancelledError('image download cancelled')

    def _acquire_download_lock(self, lock: threading.Lock, context: ImageDownloadContext) -> None:
        while not context.cancel_event.is_set():
            if lock.acquire(timeout=0.1):
                return
        raise ImageDownloadCancelledError('image download cancelled')

    def _close_active_image_downloads(self, context: ImageDownloadContext | None = None) -> None:
        if context is not None:
            self._close_image_http_sessions(context)
        close_http = getattr(self.http, 'close', None)
        if callable(close_http):
            try:
                close_http()
            except Exception:
                logger.debug(
                    'Failed to close HTTP session during image download cancellation.',
                    exc_info=True,
                )

    def _create_image_http_session(self):
        retry_strategy = Retry(
            total=3,
            status_forcelist=IMAGE_RETRY_STATUS_CODES,
            allowed_methods=['GET'],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=self._source_max_download_workers(),
            pool_maxsize=self._source_max_download_workers(),
        )
        session = requests.Session()
        source_headers = getattr(self.http, 'headers', None)
        if source_headers:
            session.headers.update(source_headers)
        source_cookies = getattr(self.http, 'cookies', None)
        if source_cookies:
            session.cookies.update(source_cookies)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session

    def _image_http_session(self, context: ImageDownloadContext):
        session = getattr(context.thread_local, 'session', None)
        if session is not None:
            return session
        session_factory = context.session_factory or self._create_image_http_session
        session = session_factory()
        context.thread_local.session = session
        with context.session_lock:
            context.sessions.append(session)
        return session

    def _close_image_http_sessions(self, context: ImageDownloadContext) -> None:
        with context.session_lock:
            sessions = list(context.sessions)
            context.sessions.clear()
        for session in sessions:
            close = getattr(session, 'close', None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug('Failed to close image HTTP session.', exc_info=True)

    def _download_image(
        self, context: ImageDownloadContext, index: int, img_url_part: str
    ) -> ImageDownloadFailure | None:
        file_path = os.path.join(context.path, f'{index + 1:04d}.jpg')
        tmp_path = file_path + '.tmp'
        full_img_url = self._build_image_url(img_url_part, context.use_base_img_url)
        retry_count = int(self._source_profile_value('image_retry_count', 1) or 1)
        last_error = ''

        self._raise_if_image_download_cancelled(context)

        if self._can_reuse_image(file_path):
            logger.debug('图片已存在，跳过: {file_path}', file_path=file_path)
            return None

        logger.debug('下载图片: {} 到 {}', full_img_url, file_path)
        for attempt in range(1, retry_count + 2):
            response = None
            try:
                self._raise_if_image_download_cancelled(context)
                self._wait_for_download_slot(context)
                if not self._download_image_with_browser(
                    full_img_url, context, tmp_path, file_path
                ):
                    response = self._request_image(full_img_url, context)
                    self._write_image_response(response, context, tmp_path, file_path)
                logger.debug('图片 {} 下载成功.', file_path)
                return None
            except ImageDownloadCancelledError:
                self._remove_tmp_file(tmp_path)
                raise
            except (requests.exceptions.RequestException, OSError, RuntimeError) as e:
                last_error = str(e)
                self._handle_image_download_error(tmp_path, full_img_url, attempt, retry_count, e)
            finally:
                if response is not None and hasattr(response, 'close'):
                    response.close()
        return ImageDownloadFailure(index + 1, full_img_url, file_path, last_error)

    def _can_reuse_image(self, file_path: str) -> bool:
        return not self.overwrite and os.path.exists(file_path) and os.path.getsize(file_path) > 0

    def _build_image_url(self, img_url_part: str, use_base_img_url: bool) -> str:
        if use_base_img_url and not img_url_part.startswith('http'):
            return urljoin(self._source_base_img_url().rstrip('/') + '/', img_url_part)
        return img_url_part

    def _source_profile_value(self, key: str, default=None):
        profile = getattr(self, 'profile', None)
        if profile is not None:
            return getattr(profile, key)
        return getattr(self, key, default)

    def _source_base_url(self) -> str:
        return str(self._source_profile_value('base_url', ''))

    def _source_base_img_url(self) -> str:
        return str(self._source_profile_value('base_img_url', ''))

    def _source_max_download_workers(self) -> int:
        return max(1, int(self._source_profile_value('max_download_workers', 5) or 5))

    def _wait_for_download_slot(self, context: ImageDownloadContext) -> None:
        self._raise_if_image_download_cancelled(context)
        interval = self._image_request_interval_seconds()
        if interval <= 0:
            return
        self._acquire_download_lock(context.rate_lock, context)
        try:
            now = time.monotonic()
            elapsed = now - context.last_request_at[0]
            if (
                context.last_request_at[0] > 0
                and elapsed < interval
                and context.cancel_event.wait(interval - elapsed)
            ):
                raise ImageDownloadCancelledError('image download cancelled')
            context.last_request_at[0] = time.monotonic()
        finally:
            context.rate_lock.release()

    def _request_image(self, full_img_url: str, context: ImageDownloadContext):
        headers = {'referer': self._source_base_url()}
        self._raise_if_image_download_cancelled(context)
        session = self._image_http_session(context)
        self._raise_if_image_download_cancelled(context)
        response = session.get(full_img_url, timeout=30, headers=headers, stream=True)
        response.raise_for_status()
        return response

    def _download_image_with_browser(
        self, full_img_url: str, context: ImageDownloadContext, tmp_path: str, file_path: str
    ) -> bool:
        if self._source_browser_mode() != SELENIUMBASE_MODE:
            return False
        download_to_file = getattr(self.driver, 'download_to_file', None)
        if not callable(download_to_file):
            return False

        self._raise_if_image_download_cancelled(context)
        self._acquire_download_lock(context.http_lock, context)
        try:
            self._raise_if_image_download_cancelled(context)
            download_to_file(full_img_url, tmp_path, referer=self._source_base_url())
        finally:
            context.http_lock.release()
        self._raise_if_image_download_cancelled(context)
        os.replace(tmp_path, file_path)
        return True

    def _write_image_response(
        self, response, context: ImageDownloadContext, tmp_path: str, file_path: str
    ) -> None:
        self._raise_if_image_download_cancelled(context)
        with open(tmp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                self._raise_if_image_download_cancelled(context)
                if chunk:
                    f.write(chunk)
        self._raise_if_image_download_cancelled(context)
        os.replace(tmp_path, file_path)

    def _handle_image_download_error(
        self,
        tmp_path: str,
        full_img_url: str,
        attempt: int,
        retry_count: int,
        error: Exception,
    ) -> None:
        self._remove_tmp_file(tmp_path)
        if attempt <= retry_count:
            logger.warning(
                '下载图片失败，将重试: {}, 第 {}/{} 次, 错误: {}',
                full_img_url,
                attempt,
                retry_count + 1,
                error,
            )
        else:
            logger.error('下载图片失败: {}, 错误: {}', full_img_url, error)

    def _remove_tmp_file(self, tmp_path: str) -> None:
        if not os.path.exists(tmp_path):
            return
        try:
            os.remove(tmp_path)
        except OSError:
            logger.warning('清理临时文件失败: {}', tmp_path, exc_info=True)

    def _image_request_interval_seconds(self) -> float:
        configured = self._source_profile_value('image_request_interval', None)
        if configured is None:
            configured = self._source_profile_value('download_interval', 0)
        return float(configured or 0)
