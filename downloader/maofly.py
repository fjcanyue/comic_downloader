import re
from io import StringIO

from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume


class MaoflyComic(ComicSource):
    name = '漫画猫'
    base_url = 'https://www.maofly.com'
    base_img_url = 'https://mao.mhtupian.com/uploads'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

        r = self.http.get('%s/static/js/string.min.js' % self.base_url)
        self.jsstring = r.text

        self.pattern_img_data = re.compile('let img_data\s*=\s*"(.+)"')

    def search(self, keyword):
        root = self.__parse_html__(
            '%s/search.html?q=%s' % (self.base_url, keyword))
        main = root.xpath('//div[contains(@class,"comic-main-section")]')
        if len(main) == 0:
            print('没有找到页面关键元素，搜索失败，请检查XPath是否正确。')
            return
        else:
            main = main[0]
        result = main.xpath('//div[@class="text-muted"]')[0].text
        print(result)
        book_list = main.xpath('//div[contains(@class,"comicbook-index")]')
        arr = []
        for book in book_list:
            b = book.xpath('a')[0]
            comic = Comic()
            comic.url = b.attrib.get('href')
            comic.name = b.attrib.get('title')
            author_xpath = book.xpath('div/a')
            if len(author_xpath) > 0:
                comic.author = author_xpath[0].text
            arr.append(comic)
        return arr

    def info(self, url):
        root = self.__parse_html__(url)
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//td[@class="comic-titles"]')[0].text.strip()
        meta_table = root.xpath(
            '//table[contains(@class,"comic-meta-data-table")]/tbody/tr')
        for meta in meta_table:
            link = meta.find('td/a')
            if link is None:
                value = meta.find('td').text
                if not value:
                    continue
            else:
                value = link.text
            comic.metadata.append({'k': meta.xpath('th')[0].text, 'v': value.strip()})
        book_list = root.xpath('//div[@id="comic-book-list"]/div')
        for book in book_list:
            book_xpath = book.xpath('div/div/h2')
            if len(book_xpath) == 0:
                break
            comic_book = ComicBook()
            comic_book.name = book_xpath[0].text.strip()
            vol_list = book.xpath('ol/li/a')
            for vol in vol_list:
                comic_book.vols.append(ComicVolume(vol.attrib[
                    'title'], vol.attrib['href'], comic_book.name))
            comic.books.append(comic_book)
        return comic

    def __parse_imgs__(self, url):
        img_data = self.__find_img_data__(url)
        imgs = self.__decode_img_data__(img_data)
        return imgs

    def __find_img_data__(self, url):
        """查找img_data变量值"""
        root = self.__parse_html__(url)
        scripts = root.xpath('//script[not(@src)]/text()')
        for script in scripts:
            result = self.pattern_img_data.findall(script)
            if len(result) > 0:
                return result[0]

    def __decode_img_data__(self, img_data):
        """解码img_data变量值"""
        js = '%sreturn LZString.decompressFromBase64("%s");' % (
            self.jsstring, img_data)
        imgs = self.driver.execute_script(js)
        return imgs.split(',')
