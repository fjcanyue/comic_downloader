"""Shared text, URL and chapter-catalog checks for source adapters."""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlsplit

from loguru import logger

from downloader.models import Comic, ComicBook


def http_url(value: str | None, base_url: str) -> str | None:
    if not isinstance(value, str) or not value.strip() or value.strip().startswith('#'):
        return None
    try:
        resolved = urljoin(base_url, value.strip())
        parts = urlsplit(resolved)
        if (
            parts.scheme not in {'http', 'https'}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            return None
        # Accessing port also validates malformed/out-of-range port values.
        _ = parts.port
        return urldefrag(resolved)[0]
    except ValueError:
        return None


def node_text(node) -> str:
    if isinstance(node, str):
        return node.strip()
    return ''.join(node.itertext()).strip() if hasattr(node, 'itertext') else ''


def parse_warning(target: Comic | ComicBook, message: str) -> None:
    if message not in target.parse_warnings:
        target.parse_warnings.append(message)
        logger.warning('章节解析提示：{}', message)


def finalize_comic_info(comic: Comic, page_url: str) -> Comic:
    """Normalize links and deduplicate within each group, retaining source order."""
    for book in comic.books:
        seen: set[str] = set()
        volumes = []
        duplicates = 0
        for volume in book.vols:
            resolved = http_url(volume.url, page_url)
            if not resolved or not volume.name.strip():
                parse_warning(book, '部分章节缺少有效名称或 HTTP 地址，已保留其余章节。')
                continue
            if resolved in seen:
                duplicates += 1
                continue
            seen.add(resolved)
            volume.url = resolved
            volumes.append(volume)
        book.vols = volumes
        if duplicates:
            parse_warning(book, f'已合并 {duplicates} 个重复章节地址。')
        for warning in book.parse_warnings:
            parse_warning(comic, f'{book.name or "默认章节"}：{warning}')
    if not any(book.vols for book in comic.books):
        parse_warning(comic, '未解析到可下载章节；页面可能没有章节，或页面结构已变化。')
    return comic
