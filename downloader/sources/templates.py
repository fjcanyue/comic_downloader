from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from loguru import logger
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.models import Comic, ComicBook, ComicVolume


class SourceUrlMixin:
    def absolute_url(self, url_part: str | None, base_url: str | None = None) -> str | None:
        if not url_part:
            return None
        if url_part.startswith('http'):
            return url_part
        return urljoin((base_url or self.base_url).rstrip('/') + '/', url_part)

    def _parse_html_with_encoding(self, url: str, encoding: str = 'utf-8'):
        if encoding == 'utf-8':
            return self.__parse_html__(url)
        return self.__parse_html__(url, encoding=encoding)

    def _first_xpath_value(self, node: Any, xpath: str) -> Any:
        values = node.xpath(xpath)
        if not values:
            return None
        if all(isinstance(value, str) for value in values):
            text = ''.join(value.strip() for value in values if value.strip())
            return text or None
        value = values[0]
        text = getattr(value, 'text', None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        text_content = value.xpath('string()') if hasattr(value, 'xpath') else None
        return (
            text_content.strip()
            if isinstance(text_content, str) and text_content.strip()
            else value
        )

    def _node_debug_string(self, node) -> str:
        try:
            return etree.tostring(node, encoding='unicode')
        except Exception:
            return str(node)


class ConfigurableSearchMixin(SourceUrlMixin):
    search_url_template: str = ''
    search_root_xpath: str | None = None
    search_count_xpath: str | None = None
    search_encoding: str = 'utf-8'

    def _build_search_url(self, keyword: str) -> str:
        if not self.search_url_template:
            raise RuntimeError(f'{type(self).__name__} must define search_url_template')
        return self.search_url_template.format(base_url=self.base_url, keyword=keyword)

    def _search_root(self, root):
        if not self.search_root_xpath:
            return root
        main_nodes = root.xpath(self.search_root_xpath)
        if not main_nodes:
            return None
        return main_nodes[0]

    def _log_search_count(self, main) -> None:
        if not self.search_count_xpath:
            return
        result_count_nodes = main.xpath(self.search_count_xpath)
        if result_count_nodes:
            result_text = getattr(result_count_nodes[0], 'text', None) or str(result_count_nodes[0])
            logger.info('Found {} related results', result_text.strip())
        else:
            logger.info('Search result count was not found')

    def search(self, keyword):
        logger.info('Start searching {}: {}', self.name, keyword)
        search_url = self._build_search_url(keyword)
        results = []
        try:
            root = self._parse_html_with_encoding(search_url, self.search_encoding)
            if root is None:
                logger.error("Search '{}' failed, could not parse page: {}", keyword, search_url)
                return results

            main = self._search_root(root)
            if main is None:
                logger.info(
                    "No main search content found on {} for '{}'",
                    self.name,
                    keyword,
                )
                return results

            self._log_search_count(main)
            items = self.parse_xpath_list(
                main,
                self.config['search_xpath'],
                self.config['search_extract'],
            )
            for item in items:
                comic = self._comic_from_search_item(item)
                if comic is not None:
                    results.append(comic)
        except Exception as e:
            logger.error(
                "Error while searching {} for '{}': {}",
                self.name,
                keyword,
                e,
                exc_info=True,
            )
            return results
        logger.info("{} search '{}' completed, found {} results", self.name, keyword, len(results))
        return results

    def _comic_from_search_item(self, item: dict[str, Any]) -> Comic | None:
        url_part = item.get('url')
        comic_url = self.absolute_url(url_part)
        if not comic_url:
            logger.warning('Parsed comic item without URL, skipped')
            return None

        comic = Comic()
        comic.url = comic_url
        comic.name = item.get('name') or '未知漫画'
        comic.author = item.get('author') or ''
        logger.debug('Found comic: {}, author: {}, URL: {}', comic.name, comic.author, comic.url)
        return comic


class InfoFlowMixin(SourceUrlMixin):
    """Standard info() orchestration: parse page → header → metadata → books."""

    info_encoding: str = 'utf-8'

    def info(self, url):
        logger.info('Start fetching {} comic info: {}', self.name, url)
        root = self._parse_html_with_encoding(url, self.info_encoding)
        if root is None:
            logger.error('Failed to fetch or parse comic info page: {}', url)
            return None

        comic = self._parse_comic_header(root, url)
        if comic is None:
            return None
        self._append_metadata(root, comic)
        self._append_books(root, comic, url)
        logger.info(
            '{} comic info completed: {}, {} chapter groups',
            self.name,
            comic.name,
            len(comic.books),
        )
        return comic

    def _parse_comic_header(self, root, url) -> Comic | None:
        raise NotImplementedError

    def _append_metadata(self, root, comic) -> None:
        pass

    def _append_books(self, root, comic, url) -> None:
        raise NotImplementedError


class GroupedChapterInfoMixin(InfoFlowMixin):
    reverse_volumes: bool = True

    def _parse_comic_header(self, root, url):
        try:
            comic = Comic()
            comic.url = url
            name_nodes = root.xpath(self.config['info_name_xpath'])
            if not name_nodes:
                logger.error('Failed to parse comic name: {}, page structure may have changed', url)
                return None
            name = self._first_xpath_value(root, self.config['info_name_xpath'])
            if not isinstance(name, str) or not name:
                logger.error('Failed to parse comic name: {}, page structure may have changed', url)
                return None
            comic.name = name
            logger.debug('Comic name: {}', comic.name)
            return comic
        except Exception as e:
            logger.error(
                'Initial comic info parse failed for {}: {}, error: {}',
                self.name,
                url,
                e,
                exc_info=True,
            )
            return None

    def _append_books(self, root, comic, url) -> None:
        book_list = root.xpath(self.config['info_books_xpath'])
        for book in book_list:
            book_name = self._first_xpath_value(book, self.config['info_book_name_xpath'])
            if not isinstance(book_name, str) or not book_name:
                logger.warning('Chapter group title was not found, skipped: {}', url)
                continue
            comic_book = ComicBook()
            comic_book.name = book_name
            logger.debug('Processing chapter group: {}', comic_book.name)
            self._append_book_volumes(book, comic_book)
            if self.reverse_volumes:
                comic_book.vols.reverse()
            if comic_book.vols:
                comic.books.append(comic_book)
            else:
                logger.warning("Chapter group '{}' has no valid volumes, skipped.", comic_book.name)

    def _append_book_volumes(self, book, comic_book) -> None:
        vol_list = book.xpath(self.config['info_vols_xpath'])
        extract = self.config['info_vol_extract']
        for vol_node in vol_list:
            vol_title = self._first_xpath_value(vol_node, extract['name'])
            vol_href = self._first_xpath_value(vol_node, extract['url'])
            if not isinstance(vol_title, str) or not isinstance(vol_href, str) or not vol_href:
                logger.warning('Incomplete volume info: {}', self._node_debug_string(vol_node))
                continue

            full_vol_url = self.absolute_url(vol_href)
            if not full_vol_url:
                logger.warning("Volume '{}' has empty URL part, skipped.", vol_title)
                continue
            comic_book.vols.append(ComicVolume(vol_title, full_vol_url, comic_book.name))
            logger.debug('  Found volume: {} ({})', vol_title, full_vol_url)


class SingleBookChapterInfoMixin(GroupedChapterInfoMixin):
    single_book_name: str = '连载'

    def _append_books(self, root, comic, url) -> None:
        comic_book = ComicBook()
        comic_book.name = self.single_book_name

        chapter_nodes = root.xpath(self.config['info_chapters_xpath'])
        if not chapter_nodes:
            logger.warning('No chapter list found: {}, page structure may have changed.', url)
            return

        extract = self.config['info_chapter_extract']
        for chapter_node in chapter_nodes:
            try:
                vol_name = self._extract_volume_name(chapter_node, extract)
                vol_href = self._extract_volume_href(chapter_node, extract)
                if not vol_href:
                    logger.warning(
                        'Incomplete volume info: {}',
                        self._node_debug_string(chapter_node)[:200],
                    )
                    continue
                if not vol_name:
                    vol_name = chapter_node.get('title', '').strip()
                if not vol_name:
                    vol_name = '未知章节'

                full_vol_url = self.absolute_url(vol_href)
                if not full_vol_url:
                    logger.warning("Volume '{}' has empty URL part, skipped.", vol_name)
                    continue
                comic_book.vols.append(ComicVolume(vol_name, full_vol_url, comic_book.name))
                logger.debug('  Found volume: {} ({})', vol_name, full_vol_url)
            except Exception:
                logger.warning(
                    'Failed to parse chapter item: {}',
                    self._node_debug_string(chapter_node)[:200],
                    exc_info=True,
                )
                continue

        if self.reverse_volumes:
            comic_book.vols.reverse()
        if comic_book.vols:
            comic.books.append(comic_book)
        else:
            logger.warning('Chapter group contains no valid volumes and was skipped: {}', url)

    def _extract_volume_name(self, chapter_node, extract: dict[str, str]) -> str:
        vol_name = self._first_xpath_value(chapter_node, extract['name'])
        return vol_name if isinstance(vol_name, str) else ''

    def _extract_volume_href(self, chapter_node, extract: dict[str, str]) -> str:
        href = chapter_node.get('href', '')
        if href:
            return href
        vol_href = self._first_xpath_value(chapter_node, extract['url'])
        return vol_href if isinstance(vol_href, str) else ''


class XPathImageSourceMixin(SourceUrlMixin):
    image_encoding: str = 'utf-8'
    image_xpath_config_key: str = 'imgs_xpath'
    image_attr_config_key: str = 'imgs_attr'
    require_absolute_image_url: bool = False

    def __parse_imgs__(self, url):
        logger.info('Start parsing images from {}: {}', self.name, url)
        try:
            root = self._parse_html_with_encoding(url, self.image_encoding)
            if root is None:
                logger.error('Failed to fetch or parse image page: {}', url)
                return []

            img_values = root.xpath(self.config[self.image_xpath_config_key])
            if not img_values:
                logger.warning('No image elements found: {}', url)
                return []

            processed_imgs = []
            for img_value in img_values:
                img_url = self._image_url_from_xpath_value(img_value)
                if not img_url:
                    logger.warning(
                        'Image node does not contain a URL: {}', self._image_debug(img_value)
                    )
                    continue
                if self.require_absolute_image_url and not img_url.startswith('http'):
                    continue
                full_img_url = self.absolute_url(img_url)
                if not full_img_url:
                    continue
                processed_imgs.append(full_img_url)
                logger.debug('Found image URL: {}', full_img_url)

            logger.info('Parsed {} images from {}', len(processed_imgs), url)
            return processed_imgs
        except Exception as e:
            logger.error('Error while parsing image list from {}: {}', url, e, exc_info=True)
            return []

    def _image_url_from_xpath_value(self, img_value) -> str | None:
        if isinstance(img_value, str):
            return img_value.strip()

        configured_attr = self.config.get(self.image_attr_config_key)
        if configured_attr:
            img_url = img_value.attrib.get(configured_attr)
            if img_url:
                return img_url.strip()

        img_url = img_value.attrib.get('src')
        return img_url.strip() if img_url else None

    def _image_debug(self, img_value) -> str:
        if isinstance(img_value, str):
            return img_value
        return self._node_debug_string(img_value)


class JsImageSourceMixin:
    image_js_config_key = 'imgs_js'

    def __parse_imgs__(self, url):
        logger.info('Start parsing images from {}: {}', self.name, url)
        try:
            self.driver.get(url)
            self._prepare_driver_for_image_parse()
            img_urls = self.execute_js_safely(
                self.driver, self.config[self.image_js_config_key], []
            )
            if not img_urls:
                logger.warning('Could not read image variable from page: {}', url)
                return []

            processed_imgs = self._process_js_image_urls(img_urls)
            logger.info('Parsed {} images from {}', len(processed_imgs), url)
            return processed_imgs
        except Exception as e:
            logger.error('Error while parsing image list from {}: {}', url, e, exc_info=True)
            return []

    def _prepare_driver_for_image_parse(self):
        """Hook called after driver.get() and before JS execution."""

    def _process_js_image_urls(self, img_urls):
        return [img for img in img_urls if img and isinstance(img, str)]


class JsDictImageSourceMixin(JsImageSourceMixin):
    image_dict_url_key = 'url'

    def _process_js_image_urls(self, img_urls):
        processed_imgs = []
        for img_url in img_urls:
            if (
                isinstance(img_url, dict)
                and self.image_dict_url_key in img_url
                and isinstance(img_url[self.image_dict_url_key], str)
            ):
                processed_imgs.append(img_url[self.image_dict_url_key])
                logger.debug('Parsed image URL: {}', img_url[self.image_dict_url_key])
            else:
                logger.warning('Invalid image URL entry: {}', img_url)
        return processed_imgs
