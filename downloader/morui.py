from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser_modes import CLOAKBROWSER_MODE
from downloader.comic import ComicSource, logger
from downloader.source_templates import (
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    JsImageSourceMixin,
)


class MoruiComic(
    ConfigurableSearchMixin,
    GroupedChapterInfoMixin,
    JsImageSourceMixin,
    ComicSource,
):
    name = '摩锐漫画'
    base_url = 'https://www.morui.com'
    base_img_url = 'http://lao.haotu90.top'
    browser_mode = CLOAKBROWSER_MODE
    browser_wait_selector = '.page-main'
    browser_wait_seconds = 60.0
    browser_headless = False
    download_interval = 5
    download_requires_driver = True
    seleniumbase_wait_selector = '.page-main'
    seleniumbase_wait_seconds = 60.0
    seleniumbase_headless = False
    config_file = 'morui.json'
    enable = True

    search_url_template = '{base_url}/search/?keywords={keyword}'
    search_root_xpath = '//div[contains(@class,"page-main")]'
    search_count_xpath = './/h4[@class="fl"]'

    def __init__(self, output_dir, http, driver, overwrite=True, *, profile=None):
        super().__init__(output_dir, http, driver, overwrite, profile=profile)

    def _append_metadata(self, root, comic):
        meta_table = root.xpath(self.config['info_meta_xpath'])
        for meta in meta_table:
            self._append_metadata_item(comic, meta)

    def _append_metadata_item(self, comic, meta):
        try:
            for span in meta.xpath('.//span'):
                self._append_metadata_span(comic, span)
        except Exception as e:
            logger.warning(
                '解析元数据时出错: {}, 错误: {}',
                etree.tostring(meta, encoding='unicode'),
                e,
                exc_info=True,
            )

    def _append_metadata_span(self, comic, span):
        key = ''
        value = ''

        strong_node = span.find('strong')
        if strong_node is not None and strong_node.text:
            key = strong_node.text.strip().rstrip('：')
        if not key:
            return

        values = [
            link.text.strip() for link in span.xpath('.//a') if link.text and link.text.strip()
        ]
        if values:
            value = ' | '.join(values)

        if key and value:
            logger.debug('元数据: {} - {}', key, value)
            comic.metadata.append({'k': key, 'v': value})
        elif key:
            logger.debug("元数据项 '{}' 的值为空或未找到.", key)
