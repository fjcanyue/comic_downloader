from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, cast

from downloader.comic import ComicSource


class NoNetworkHttp:
    headers: ClassVar[dict[str, str]] = {}

    def get(self, *args, **kwargs):
        raise AssertionError('existing image should be reused without a network request')


class ResumeSource(ComicSource):
    name = 'resume-source'
    base_url = 'https://example.test'
    max_download_workers = 4

    def search(self, keyword):
        return []

    def info(self, url):
        return None

    def __parse_imgs__(self, url):
        return []


def test_existing_images_are_reused_when_overwrite_is_disabled(tmp_path):
    image_dir = tmp_path / 'chapter'
    image_dir.mkdir()
    existing_image = image_dir / '0001.jpg'
    existing_image.write_bytes(b'existing')

    source = ResumeSource(str(tmp_path), cast(Any, NoNetworkHttp()), None, overwrite=False)

    result = source.__download_vol_images__(
        str(image_dir),
        'chapter',
        'https://example.test/chapter',
        ['https://example.test/0001.jpg'],
    )

    assert result.status == 'downloaded'
    assert result.downloaded_count == 1
    assert existing_image.read_bytes() == b'existing'
    assert result.archive_path is not None
    assert Path(result.archive_path).exists()
