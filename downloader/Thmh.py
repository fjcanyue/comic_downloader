import re
from io import StringIO

from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume


class TmhComic(ComicSource):
    name = '31漫画'
    base_url = 'https://www.31mh.com'
    #base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

        r = self.http.get('%s/static/js/string.min.js' % self.base_url)
        self.jsstring = r.text

        self.pattern_img_data = re.compile('let img_data\s*=\s*"(.+)"')

    def search(self, keyword):
        root = self.__parse_html__(
            '%s/search/?keywords=%s' % (self.base_url, keyword))
        main = root.xpath('//ul[contains(@class,"list_con_li")]')
        if len(main) == 0:
            print('没有找到页面关键元素，搜索失败，请检查XPath是否正确。')
            return
        else:
            main = main[0]
        result = main.xpath('//em[@class="c_6"]')[0].text
        print('共 %s 条相关的结果' % result)
        book_list = main.xpath('//li[contains(@class,"list-comic")]')
        arr = []
        for book in book_list:
            b = book.xpath('a')[0]
            comic = Comic()
            comic.url = b.attrib.get('href')
            comic.name = b.attrib.get('title')
            author_xpath = book.xpath('p[contains(@class,"auth")]')
            if len(author_xpath) > 0:
                comic.author = author_xpath[0].text
            arr.append(comic)
        return arr

    def info(self, url):
        root = self.__parse_html__(url)
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//div[contains(@class,"comic_deCon")]/h1')[0].text.strip()
        meta_table = root.xpath(
            '//ul[contains(@class,"comic_deCon_liO")]/li')
        for meta in meta_table:
            kvs = meta.text.split('：')
            link = meta.find('a')
            if link is None:
                value = kvs[1]
                if not value:
                    continue
            else:
                value = link.text
            comic.metadata.append({'k': kvs[0], 'v': value.strip()})
        book_list = root.xpath('//div[contains(@class,"zj_list")]')
        for book in book_list:
            book_xpath = book.xpath('div[contains(@class,"zj_list_head")]/h2')
            if len(book_xpath) == 0:
                break
            comic_book = ComicBook()
            comic_book.name = book_xpath[0].text.strip()
            vol_list = book.xpath('div[contains(@class,"zj_list_con")]/ul/li')
            for vol in vol_list:
                comic_book.vols.append(ComicVolume(vol.xpath('a/span[contains(@class,"list_con_zj")]')[0].text.strip(), vol.xpath('a')[0].attrib.get('href'), comic_book.name))
            comic_book.vols.reverse()
            comic.books.append(comic_book)
        return comic

    def __parse_imgs__(self, url):
        self.driver.get(url)
        return self.driver.execute_script('return chapterImages;')

