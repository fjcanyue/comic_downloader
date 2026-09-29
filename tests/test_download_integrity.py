from __future__ import annotations

import base64
from zipfile import ZIP_DEFLATED, ZipFile

from downloader.download.integrity import (
    validate_comic_archive,
    validate_image_bytes,
    validate_image_file,
)

VALID_JPEG = b'\xff\xd8\xff\xe0' + (b'\x00' * 12) + b'\xff\xd9'
VALID_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


def test_image_integrity_accepts_supported_complete_images(tmp_path):
    jpeg_path = tmp_path / 'image.jpg'
    jpeg_path.write_bytes(VALID_JPEG)

    jpeg_check = validate_image_file(jpeg_path)
    png_check = validate_image_bytes(VALID_PNG)

    assert jpeg_check.ok is True
    assert jpeg_check.media_type == 'jpeg'
    assert png_check.ok is True
    assert png_check.media_type == 'png'


def test_image_integrity_rejects_html_and_truncated_images():
    html_check = validate_image_bytes(b'<html>blocked</html>')
    truncated_check = validate_image_bytes(VALID_JPEG[:-2])

    assert html_check.ok is False
    assert '图片格式' in str(html_check.reason)
    assert truncated_check.ok is False
    assert '结束标记' in str(truncated_check.reason)


def test_png_integrity_checks_chunk_crc():
    corrupted_png = bytearray(VALID_PNG)
    corrupted_png[-5] ^= 0x01

    check = validate_image_bytes(bytes(corrupted_png))

    assert check.ok is False
    assert '校验失败' in str(check.reason)


def test_comic_archive_validates_entries_and_image_contents(tmp_path):
    archive_path = tmp_path / 'chapter.zip'
    with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('0001.jpg', VALID_JPEG)
        archive.writestr('0002.jpg', VALID_PNG)

    check = validate_comic_archive(archive_path)

    assert check.ok is True
    assert check.media_type == 'zip'


def test_comic_archive_rejects_invalid_images_and_unsafe_paths(tmp_path):
    invalid_image_archive = tmp_path / 'invalid-image.zip'
    with ZipFile(invalid_image_archive, 'w') as archive:
        archive.writestr('0001.jpg', b'<html>blocked</html>')

    unsafe_archive = tmp_path / 'unsafe.zip'
    with ZipFile(unsafe_archive, 'w') as archive:
        archive.writestr('../0001.jpg', VALID_JPEG)

    invalid_check = validate_comic_archive(invalid_image_archive)
    unsafe_check = validate_comic_archive(unsafe_archive)

    assert invalid_check.ok is False
    assert '0001.jpg' in str(invalid_check.reason)
    assert unsafe_check.ok is False
    assert '不安全路径' in str(unsafe_check.reason)
