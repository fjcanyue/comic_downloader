from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.comic import ComicSource, logger
from downloader.source_templates import (
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    XPathImageSourceMixin,
)


class BoyaComic(
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    XPathImageSourceMixin,
    ComicSource,
):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '博雅漫画'
    base_url = 'http://www.boyamh.com'
    config_file = 'boya.json'
    enable = False

    search_url_template = '{base_url}/search/{keyword}/'
    search_root_xpath = '//ul[contains(@class,"cartoon-block-box")]'
    search_encoding = 'gbk'
    info_encoding = 'gbk'
    image_encoding = 'gbk'

    def _append_metadata(self, root, comic):
        meta_table = root.xpath(self.config['info_meta_xpath'])
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            key_node = meta.xpath('span')
            if not key_node:
                return
            key = key_node[0].text.strip()
            value = ''
            link_node = meta.find('a')
            if link_node is not None and link_node.text:
                value = link_node.text.strip()
            else:
                p_text_content = meta.text_content().strip()
                if p_text_content.startswith(key):
                    value = p_text_content[len(key) :].strip()
                if not value and meta.xpath('text()'):
                    p_direct_texts = meta.xpath('text()')
                    value = ' '.join(t.strip() for t in p_direct_texts if t.strip())

            if key and value:
                logger.debug('元数据: {} - {}', key, value)
                comic.metadata.append({'k': key, 'v': value})
            elif key:
                logger.debug("元数据项 '{}' 的值为空或未找到", key)
        except Exception as e:
            logger.warning(
                '解析元数据时出错: {}, 错误: {}',
                etree.tostring(meta, encoding='unicode'),
                e,
                exc_info=True,
            )
