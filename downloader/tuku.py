from urllib.parse import quote

from downloader.browser_modes import REQUESTS_MODE
from downloader.comic import ComicSource, logger
from downloader.source_templates import (
    ConfigurableSearchMixin,
    SingleBookChapterInfoMixin,
    XPathImageSourceMixin,
)


class TukuComic(
    ConfigurableSearchMixin,
    SingleBookChapterInfoMixin,
    XPathImageSourceMixin,
    ComicSource,
):
    name = '图库漫画'
    base_url = 'https://www.tuku.cc'
    browser_mode = REQUESTS_MODE
    download_interval = 2
    config_file = 'tuku.json'
    enable = True

    single_book_name = '连载'
    require_absolute_image_url = True

    def _build_search_url(self, keyword: str) -> str:
        return f'{self.base_url}/search?title={quote(keyword)}&language=1&f=2'

    @staticmethod
    def _text_content(node):
        return ''.join(node.itertext()) if hasattr(node, 'itertext') else (node.text or '')

    def _append_metadata(self, root, comic):
        author_nodes = root.xpath(self.config['info_author_xpath'])
        if author_nodes:
            author_text = author_nodes[0].text
            if author_text:
                comic.metadata.append({'k': '作者', 'v': author_text.strip()})
                logger.debug('元数据: 作者 - {}', author_text.strip())

        status_nodes = root.xpath(self.config['info_status_xpath'])
        if status_nodes:
            status_full = self._text_content(status_nodes[0]).strip()
            if '状态：' in status_full:
                status_value = status_full.split('状态：', 1)[1].strip()
            elif '状态' in status_full:
                status_value = status_full.split('状态', 1)[1].strip()
            else:
                status_value = status_full
            if status_value:
                comic.metadata.append({'k': '状态', 'v': status_value})
                logger.debug('元数据: 状态 - {}', status_value)

        genre_nodes = root.xpath(self.config['info_genre_xpath'])
        if genre_nodes:
            genres = []
            for node in genre_nodes:
                genre_text = node.text
                if genre_text:
                    genres.append(genre_text.strip())
            if genres:
                genre_value = ' | '.join(genres)
                comic.metadata.append({'k': '题材', 'v': genre_value})
                logger.debug('元数据: 题材 - {}', genre_value)
