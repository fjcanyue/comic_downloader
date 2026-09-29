from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from downloader.download.archive import ArchiveMixin


class ArchiveSource(ArchiveMixin):
    overwrite = False


def make_archive(path, content=b'valid image bytes'):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('0001.jpg', content)


def test_existing_valid_archive_can_be_reused(tmp_path):
    target = tmp_path / 'chapter.zip'
    make_archive(target)
    assert ArchiveSource()._find_existing_archive(str(tmp_path), 'chapter') == str(target)


def test_zero_padded_valid_archive_can_be_reused(tmp_path):
    target = tmp_path / '001.zip'
    make_archive(target)
    assert ArchiveSource()._find_existing_archive(str(tmp_path), '1') == str(target)


@pytest.mark.parametrize('kind', ['truncated', 'empty', 'zero-image', 'bad-crc'])
def test_incomplete_archives_are_not_mistaken_for_completed_downloads(tmp_path, kind):
    target = tmp_path / 'chapter.zip'
    if kind == 'truncated':
        target.write_bytes(b'PK\x03\x04broken')
    elif kind == 'empty':
        with zipfile.ZipFile(target, 'w'):
            pass
    elif kind == 'zero-image':
        make_archive(target, b'')
    else:
        make_archive(target)
        target.write_bytes(target.read_bytes().replace(b'valid image bytes', b'wrong image bytes'))
    assert ArchiveSource()._find_existing_archive(str(tmp_path), 'chapter') is None


def test_archive_contains_only_expected_images_and_ignores_unrelated_files(tmp_path):
    directory = tmp_path / 'chapter'
    directory.mkdir()
    (directory / '0001.jpg').write_bytes(b'image1')
    (directory / '0002.jpg').write_bytes(b'image2')
    (directory / 'notes.txt').write_text('personal notes', encoding='utf-8')
    (directory / '0003.jpg.tmp').write_bytes(b'incomplete')
    (directory / 'old').mkdir()
    result = ArchiveSource()._finalize_volume_download(str(directory), 'chapter', 'url', 2, [])
    assert result.status == 'downloaded'
    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == ['0001.jpg', '0002.jpg']
        assert archive.read('0002.jpg') == b'image2'
    assert (directory / 'notes.txt').exists()


def test_unrelated_file_cannot_substitute_for_a_missing_image(tmp_path):
    directory = tmp_path / 'chapter'
    directory.mkdir()
    (directory / '0001.jpg').write_bytes(b'image1')
    (directory / 'notes.txt').write_text('not an image', encoding='utf-8')
    result = ArchiveSource()._finalize_volume_download(str(directory), 'chapter', 'url', 2, [])
    assert result.status == 'partial'
    assert result.downloaded_count == 1
    assert not (tmp_path / 'chapter.zip').exists()


@pytest.mark.parametrize('error', [KeyboardInterrupt, OSError])
def test_interrupted_archive_creation_preserves_previous_zip(tmp_path, monkeypatch, error):
    directory = tmp_path / 'chapter'
    directory.mkdir()
    (directory / '0001.jpg').write_bytes(b'replacement')
    target = tmp_path / 'chapter.zip'
    make_archive(target, b'original')
    previous = target.read_bytes()

    def fail_write(self, *args, **kwargs):
        raise error('interrupted while writing ZIP')

    monkeypatch.setattr(zipfile.ZipFile, 'write', fail_write)
    if error is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            ArchiveSource()._archive_volume(str(directory), 'chapter', 'url', 1, 1)
    else:
        result = ArchiveSource()._archive_volume(str(directory), 'chapter', 'url', 1, 1)
        assert result.status == 'failed'
    assert target.read_bytes() == previous
    assert list(tmp_path.glob('*.zip.tmp')) == []


def test_archive_replace_failure_preserves_previous_zip(tmp_path, monkeypatch):
    directory = tmp_path / 'chapter'
    directory.mkdir()
    (directory / '0001.jpg').write_bytes(b'replacement')
    target = tmp_path / 'chapter.zip'
    make_archive(target, b'original')
    previous = target.read_bytes()

    def fail_replace(*args):
        raise OSError('file locked')

    monkeypatch.setattr('downloader.download.archive.os.replace', fail_replace)
    result = ArchiveSource()._archive_volume(str(directory), 'chapter', 'url', 1, 1)
    assert result.status == 'failed'
    assert target.read_bytes() == previous
    assert list(tmp_path.glob('*.zip.tmp')) == []


def test_completed_archive_atomically_replaces_old_file(tmp_path):
    directory = tmp_path / 'chapter'
    directory.mkdir()
    (directory / '0001.jpg').write_bytes(b'replacement')
    target = tmp_path / 'chapter.zip'
    target.write_bytes(b'old corrupt archive')
    result = ArchiveSource()._archive_volume(str(directory), 'chapter', 'url', 1, 1)
    assert result.status == 'downloaded'
    assert Path(result.archive_path) == target
    with zipfile.ZipFile(target) as archive:
        assert archive.read('0001.jpg') == b'replacement'
    assert list(tmp_path.glob('*.zip.tmp')) == []
