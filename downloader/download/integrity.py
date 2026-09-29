from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MIN_IMAGE_SIZE = 12
PNG_IHDR_SIZE = 13
TIFF_HEADER_SIZE = 8
ISO_FTYP_MIN_SIZE = 16
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
JPEG_START = b'\xff\xd8\xff'
JPEG_END = b'\xff\xd9'
GIF_SIGNATURES = (b'GIF87a', b'GIF89a')
TIFF_SIGNATURES = (b'II*\x00', b'MM\x00*')
ISO_IMAGE_BRANDS = {
    b'avif',
    b'avis',
    b'heic',
    b'heix',
    b'hevc',
    b'hevx',
    b'mif1',
    b'msf1',
}


@dataclass(frozen=True)
class IntegrityCheck:
    ok: bool
    media_type: str | None = None
    reason: str | None = None


def validate_image_file(path: str | os.PathLike[str]) -> IntegrityCheck:
    try:
        with open(path, 'rb') as image_file:
            data = image_file.read()
    except OSError as exc:
        return IntegrityCheck(False, reason=f'无法读取文件: {exc}')
    return validate_image_bytes(data)


def validate_image_bytes(data: bytes) -> IntegrityCheck:
    if len(data) < MIN_IMAGE_SIZE:
        return IntegrityCheck(False, reason='文件过小，无法构成有效图片')
    validator = None
    if data.startswith(JPEG_START):
        validator = _validate_jpeg
    elif data.startswith(PNG_SIGNATURE):
        validator = _validate_png
    elif data.startswith(GIF_SIGNATURES):
        validator = _validate_gif
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        validator = _validate_webp
    elif data.startswith(b'BM'):
        validator = _validate_bmp
    elif data.startswith(TIFF_SIGNATURES):
        validator = _validate_tiff
    elif data[4:8] == b'ftyp':
        validator = _validate_iso_image
    if validator is None:
        return IntegrityCheck(False, reason='文件头不是受支持的图片格式')
    return validator(data)


def validate_comic_archive(path: str | os.PathLike[str]) -> IntegrityCheck:
    try:
        if os.path.getsize(path) <= 0:
            return IntegrityCheck(False, media_type='zip', reason='归档为空')
        image_count = 0
        with ZipFile(path) as archive:
            for info in archive.infolist():
                entry_path = PurePosixPath(info.filename)
                if entry_path.is_absolute() or '..' in entry_path.parts:
                    return IntegrityCheck(
                        False,
                        media_type='zip',
                        reason=f'归档包含不安全路径: {info.filename}',
                    )
                if info.is_dir() or not info.filename.lower().endswith('.jpg'):
                    continue
                image_check = validate_image_bytes(archive.read(info))
                if not image_check.ok:
                    return IntegrityCheck(
                        False,
                        media_type='zip',
                        reason=f'{info.filename}: {image_check.reason}',
                    )
                image_count += 1
        if image_count == 0:
            return IntegrityCheck(False, media_type='zip', reason='归档中没有图片')
    except (BadZipFile, OSError, RuntimeError) as exc:
        return IntegrityCheck(False, media_type='zip', reason=f'归档损坏: {exc}')
    return IntegrityCheck(True, media_type='zip')


def _validate_jpeg(data: bytes) -> IntegrityCheck:
    if not data.endswith(JPEG_END):
        return IntegrityCheck(False, media_type='jpeg', reason='JPEG 缺少结束标记')
    return IntegrityCheck(True, media_type='jpeg')


def _validate_png(data: bytes) -> IntegrityCheck:
    offset = len(PNG_SIGNATURE)
    saw_header = False
    while offset + 12 <= len(data):
        chunk_length = struct.unpack('>I', data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(data):
            return IntegrityCheck(False, media_type='png', reason='PNG 数据块被截断')
        payload = data[offset + 8 : offset + 8 + chunk_length]
        expected_crc = struct.unpack('>I', data[offset + 8 + chunk_length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return IntegrityCheck(False, media_type='png', reason='PNG 数据块校验失败')
        if not saw_header:
            if chunk_type != b'IHDR' or chunk_length != PNG_IHDR_SIZE:
                return IntegrityCheck(False, media_type='png', reason='PNG 缺少有效 IHDR')
            saw_header = True
        offset = chunk_end
        if chunk_type == b'IEND':
            if chunk_length != 0 or offset != len(data):
                return IntegrityCheck(False, media_type='png', reason='PNG IEND 结构无效')
            return IntegrityCheck(True, media_type='png')
    return IntegrityCheck(False, media_type='png', reason='PNG 缺少 IEND')


def _validate_gif(data: bytes) -> IntegrityCheck:
    if data[-1:] != b';':
        return IntegrityCheck(False, media_type='gif', reason='GIF 缺少结束标记')
    return IntegrityCheck(True, media_type='gif')


def _validate_webp(data: bytes) -> IntegrityCheck:
    declared_size = struct.unpack('<I', data[4:8])[0] + 8
    if declared_size != len(data):
        return IntegrityCheck(False, media_type='webp', reason='WebP 文件长度不匹配')
    if data[12:16] not in {b'VP8 ', b'VP8L', b'VP8X'}:
        return IntegrityCheck(False, media_type='webp', reason='WebP 缺少有效图像块')
    return IntegrityCheck(True, media_type='webp')


def _validate_bmp(data: bytes) -> IntegrityCheck:
    declared_size = struct.unpack('<I', data[2:6])[0]
    pixel_offset = struct.unpack('<I', data[10:14])[0]
    if declared_size > len(data) or pixel_offset >= len(data):
        return IntegrityCheck(False, media_type='bmp', reason='BMP 文件长度或像素偏移无效')
    return IntegrityCheck(True, media_type='bmp')


def _validate_tiff(data: bytes) -> IntegrityCheck:
    byte_order = '<' if data.startswith(b'II') else '>'
    first_ifd = struct.unpack(f'{byte_order}I', data[4:8])[0]
    if first_ifd < TIFF_HEADER_SIZE or first_ifd >= len(data):
        return IntegrityCheck(False, media_type='tiff', reason='TIFF IFD 偏移无效')
    return IntegrityCheck(True, media_type='tiff')


def _validate_iso_image(data: bytes) -> IntegrityCheck:
    box_size = struct.unpack('>I', data[:4])[0]
    if box_size < ISO_FTYP_MIN_SIZE or box_size > len(data):
        return IntegrityCheck(False, media_type='iso-image', reason='ISO 图片 ftyp 长度无效')
    brands = {data[8:12]}
    brands.update(data[offset : offset + 4] for offset in range(16, box_size, 4))
    if not brands.intersection(ISO_IMAGE_BRANDS):
        return IntegrityCheck(False, media_type='iso-image', reason='ISO 容器不是受支持的图片')
    return IntegrityCheck(True, media_type='iso-image')
