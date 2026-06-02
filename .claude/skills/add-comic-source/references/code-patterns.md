# Code Patterns

Templates and patterns for creating a new comic source.

## Config JSON Template (`configs/{name}.json`)

```json
{
  "base_url": "https://www.example.com",
  "download_interval": 2,
  "search_xpath": "//div[contains(@class,'result-item')]",
  "search_extract": {
    "name": ".//h3/a/@title",
    "url": ".//h3/a/@href"
  },
  "info_name_xpath": "//div[contains(@class,'info-card')]//h1",
  "info_author_xpath": "//p[span[contains(text(),'作者')]]/a",
  "info_status_xpath": "//p[span[contains(text(),'状态')]]",
  "info_genre_xpath": "//h2/a",
  "info_chapters_xpath": "//div[contains(@class,'chapter-wrap')]/a",
  "info_chapter_extract": {
    "name": ".//span",
    "url": "./@href"
  },
  "imgs_xpath": "//img/@data-original"
}
```

For SeleniumBase/CloakBrowser modes, add:

```json
{
  "browser_mode": "seleniumbase",
  "seleniumbase_wait_selector": ".page-main",
  "seleniumbase_wait_seconds": 60.0,
  "seleniumbase_headless": false,
  "imgs_js": "return typeof chapterImages !== 'undefined' ? chapterImages : [];"
}
```

## Source Module Template (`downloader/{name}.py`)

```python
from urllib.parse import quote

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from downloader.browser_modes import REQUESTS_MODE
from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume, logger


class {SiteName}Comic(ComicSource):
    name = '{显示名称}'
    base_url = 'https://www.example.com'
    browser_mode = REQUESTS_MODE
    download_interval = 2
    config_file = '{name}.json'
    enable = True

    def __init__(self, output_dir, http, driver, overwrite=True):
        super().__init__(output_dir, http, driver, overwrite)

    @staticmethod
    def _text_content(node):
        """兼容 lxml.etree._Element 的文本提取"""
        return ''.join(node.itertext()) if hasattr(node, 'itertext') else (node.text or '')

    def search(self, keyword):
        logger.info('开始在 {} 搜索: {}', self.name, keyword)
        search_url = f'{self.base_url}/search?q={quote(keyword)}'
        arr = []
        try:
            root = self.__parse_html__(search_url)
            if root is None:
                logger.error("搜索 '{}' 失败", keyword)
                return arr

            items = self.parse_xpath_list(
                root, self.config['search_xpath'], self.config['search_extract']
            )
            for item in items:
                comic = Comic()
                try:
                    url_part = item.get('url')
                    if not url_part:
                        continue
                    comic.url = (
                        self.base_url + url_part
                        if url_part.startswith('/')
                        else url_part
                    )
                    comic.name = item.get('name') or '未知漫画'
                    comic.author = ''
                    arr.append(comic)
                except Exception as e:
                    logger.error('解析漫画条目时出错: {}', e, exc_info=True)
                    continue
        except Exception as e:
            logger.error("搜索 '{}' 发生错误: {}", keyword, e, exc_info=True)
        logger.info("{} 搜索完成, 共 {} 条结果.", self.name, len(arr))
        return arr

    def info(self, url):
        logger.info('开始获取 {} 详细信息: {}', self.name, url)
        root = self.__parse_html__(url)
        if root is None:
            return None

        comic = self._parse_comic_header(root, url)
        if comic is None:
            return None
        self._append_metadata(root, comic)
        self._append_books(root, comic, url)
        return comic

    def _parse_comic_header(self, root, url):
        comic = Comic()
        comic.url = url
        name_nodes = root.xpath(self.config['info_name_xpath'])
        if not name_nodes:
            return None
        name_text = name_nodes[0].text or self._text_content(name_nodes[0])
        comic.name = name_text.strip()
        return comic if comic.name else None

    def _append_metadata(self, root, comic):
        # 作者
        nodes = root.xpath(self.config['info_author_xpath'])
        if nodes and nodes[0].text:
            comic.metadata.append({'k': '作者', 'v': nodes[0].text.strip()})
        # 状态
        nodes = root.xpath(self.config['info_status_xpath'])
        if nodes:
            text = self._text_content(nodes[0]).strip()
            for sep in ('状态：', '状态:'):
                if sep in text:
                    text = text.split(sep, 1)[1].strip()
                    break
            if text:
                comic.metadata.append({'k': '状态', 'v': text})
        # 题材
        nodes = root.xpath(self.config['info_genre_xpath'])
        if nodes:
            genres = [n.text.strip() for n in nodes if n.text]
            if genres:
                comic.metadata.append({'k': '题材', 'v': ' | '.join(genres)})

    def _append_books(self, root, comic, url):
        comic_book = ComicBook()
        comic_book.name = '连载'

        chapter_nodes = root.xpath(self.config['info_chapters_xpath'])
        for ch in chapter_nodes:
            name_nodes = ch.xpath(self.config['info_chapter_extract']['name'])
            vol_name = ''
            if name_nodes:
                vol_name = name_nodes[0].text.strip() if name_nodes[0].text else ''
                if not vol_name:
                    vol_name = self._text_content(name_nodes[0]).strip()
            if not vol_name:
                vol_name = ch.get('title', '').strip() or '未知章节'

            href = ch.get('href', '')
            if not href:
                href_nodes = ch.xpath(self.config['info_chapter_extract']['url'])
                if href_nodes:
                    href = href_nodes[0]
            if not href:
                continue

            full_url = (
                self.base_url + href
                if href.startswith('/')
                else href if href.startswith('http') else f'{self.base_url}/{href}'
            )
            comic_book.vols.append(ComicVolume(vol_name, full_url, comic_book.name))

        comic_book.vols.reverse()
        if comic_book.vols:
            comic.books.append(comic_book)

    def __parse_imgs__(self, url):
        logger.info('开始从 {} 解析图片: {}', self.name, url)
        try:
            root = self.__parse_html__(url)
            if root is None:
                return []
            img_urls = root.xpath(self.config['imgs_xpath'])
            return [u for u in img_urls if u and isinstance(u, str) and u.startswith('http')]
        except Exception as e:
            logger.error('解析图片失败: {}', e, exc_info=True)
            return []
```

### If images require JS (SeleniumBase/CloakBrowser)

Replace `__parse_imgs__` with:

```python
def __parse_imgs__(self, url):
    try:
        self.driver.get(url)
        img_urls = self.execute_js_safely(self.driver, self.config['imgs_js'], [])
        return [u for u in img_urls if u and isinstance(u, str)]
    except Exception as e:
        logger.error('解析图片失败: {}', e, exc_info=True)
        return []
```

## Registration

### `downloader/sources.py`

Add to `SOURCE_DEFINITIONS` tuple:

```python
SourceDefinition('{name}', '{SiteName}Comic'),
```

Optional fields: `enabled=False`, `deprecated=True`.

### `downloader.spec`

Add `'downloader.{name}'` to the `hiddenimports` list so PyInstaller bundles the new source module:

```python
hiddenimports=[
    'downloader.boya',
    ...
    'downloader.{name}',
    ...
] + runtime_hiddenimports,
```

## Live XPath Test Script

Run this to validate XPaths against the live site before finalizing:

```bash
uv run python -c "
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from lxml import etree
import requests

with open('configs/{name}.json', encoding='utf-8') as f:
    config = json.load(f)
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': config['base_url']}

# Test search
r = requests.get('{search_url}', headers=headers)
r.encoding = 'utf-8'
root = etree.HTML(r.text)
items = root.xpath(config['search_xpath'])
print(f'Search: {len(items)} results')
for item in items[:3]:
    name = item.xpath(config['search_extract']['name'])
    url = item.xpath(config['search_extract']['url'])
    print(f'  {name[0] if name else \"?\"} -> {url[0] if url else \"?\"}')

# Test manga info
r2 = requests.get('{manga_url}', headers=headers)
r2.encoding = 'utf-8'
root2 = etree.HTML(r2.text)
print(f'Name: {root2.xpath(config[\"info_name_xpath\"])[0].text}')
print(f'Chapters: {len(root2.xpath(config[\"info_chapters_xpath\"]))}')

# Test chapter images
r3 = requests.get('{chapter_url}', headers=headers)
r3.encoding = 'utf-8'
root3 = etree.HTML(r3.text)
imgs = root3.xpath(config['imgs_xpath'])
print(f'Images: {len(imgs)}')
for img in imgs[:2]:
    print(f'  {img[:100]}')
"
```
