from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.comic import ComicSource, logger
from downloader.source_templates import GroupedChapterInfoMixin, JsDictImageSourceMixin


class ManhuazhanComic(GroupedChapterInfoMixin, JsDictImageSourceMixin, ComicSource):
    """
    This class is deprecated and will be removed in future versions.
    """

    name = '漫画站'
    base_url = 'https://www.manhuazhan.com'
    download_interval = 5
    download_requires_driver = True
    config_file = 'manhuazhan.json'
    enable = True

    reverse_volumes = False

    def search(self, keyword):
        logger.info(
            '网站开启了验证码验证，无法使用搜索功能，请手动输入漫画地址。例如：i https://www.manhuazhan.com/comic/255423'
        )
        logger.info('跳过 {} 搜索: {}', self.name, keyword)
        return []

    def _append_metadata(self, root, comic):
        meta_table = root.xpath(self.config['info_meta_xpath'])
        try:
            for meta in meta_table:
                self._append_metadata_item(comic, meta)
        except Exception as e:
            logger.warning('解析元数据时出错，跳过剩余元数据项，错误: {}', e, exc_info=True)

    def _append_metadata_item(self, comic, meta):
        key = ''
        value = ''
        span_node = meta.find('span')
        if span_node is not None and span_node.text:
            key = span_node.text.strip().rstrip('：')
        em_node = meta.find('em')
        a_node = meta.find('a')
        if em_node is not None and em_node.text:
            value = em_node.text.strip()
        elif a_node is not None and a_node.text:
            value = a_node.text.strip()
        elif span_node is not None and span_node.tail:
            value = span_node.tail.strip()
        elif meta.text and not key:
            kvs = meta.text.split('：', 1)
            key = kvs[0].strip()
            if len(kvs) > 1:
                value = kvs[1].strip()
        if key and value:
            logger.debug('元数据: {} - {}', key, value)
            comic.metadata.append({'k': key, 'v': value})
        elif key:
            logger.debug("元数据项 '{}' 的值为空或未找到", key)
        else:
            logger.warning('无法解析元数据项: {}', etree.tostring(meta, encoding='unicode'))
