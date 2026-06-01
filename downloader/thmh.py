from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.comic import ComicSource, logger
from downloader.source_templates import (
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    JsImageSourceMixin,
)


class TmhComic(
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    JsImageSourceMixin,
    ComicSource,
):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '31漫画'
    base_url = 'https://www.31mh.cc'
    download_interval = 5
    download_requires_driver = True
    config_file = 'thmh.json'
    enable = True

    search_url_template = '{base_url}/search/?keywords={keyword}'
    search_root_xpath = '//ul[contains(@class,"list_con_li")]'
    search_count_xpath = './/em[@class="c_6"]'

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    def _append_metadata(self, root, comic):
        meta_table = root.xpath(self.config['info_meta_xpath'])
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            key, value = self._extract_metadata(meta)
            if key and value:
                logger.debug('元数据: {} - {}', key, value)
                comic.metadata.append({'k': key, 'v': value})
            elif key:
                logger.debug("元数据项 '{}' 的值为空或未找到.", key)
            else:
                logger.warning('无法解析元数据项: {}', etree.tostring(meta, encoding='unicode'))
        except Exception as e:
            logger.warning(
                '解析元数据时出错: {}, 错误: {}',
                etree.tostring(meta, encoding='unicode'),
                e,
                exc_info=True,
            )

    def _extract_metadata(self, meta):
        key = ''
        value = ''
        if meta.text:
            kvs = meta.text.split('：', 1)
            key = kvs[0].strip()
            if len(kvs) > 1:
                value = kvs[1].strip()

        link_node = meta.find('a')
        if link_node is not None and link_node.text:
            value = link_node.text.strip()
            if not key and meta.text and '：' in meta.text:
                key = meta.text.split('：')[0].strip()
            elif not key and link_node.getprevious() is not None and link_node.getprevious().tail:
                key = link_node.getprevious().tail.strip().rstrip('：')
            elif not key and link_node.getparent().text:
                key = link_node.getparent().text.split('：')[0].strip()
        return key, value
