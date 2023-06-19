import re
from io import StringIO

from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume


class BoyaComic(ComicSource):
    name = '伯牙漫画人'
    base_url = 'https://www.tengyachem.com'
    #base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        root = self.__parse_html__(
            '%s/search/%s/' % (self.base_url, keyword), 'gbk')
        main = root.xpath('//ul[contains(@class,"cartoon-block-box")]')
        arr = []
        if len(main) == 0:
            print('没有找到页面关键元素，搜索失败。')
            return arr
        else:
            main = main[0]
        #result = main.xpath('//em[@class="c_6"]')[0].text
        #print('共 %s 条相关的结果' % result)
        book_list = main.xpath('li')
        for book in book_list:
            b = book.xpath('div/a')[0]
            comic = Comic()
            comic.url = b.attrib.get('href')
            comic.author = b.xpath('span')[0].text
            comic.name = book.xpath('div/div/p/a')[0].text
            arr.append(comic)
        return arr

    def info(self, url):
        root = self.__parse_html__(url, 'gbk')
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//div[contains(@class,"article-info-item")]/h1')[0].text.strip()
        meta_table = root.xpath(
            '//div[contains(@class,"info-item-bottom")]/p')
        for meta in meta_table:
            kvs = [meta.xpath('span')[0].text, '']
            link = meta.find('a')
            if link is None:
                value = kvs[1]
                if not value:
                    continue
            else:
                value = link.text
            comic.metadata.append({'k': kvs[0], 'v': value.strip()})
        book_list = root.xpath('//div[contains(@class,"article-chapter-list")]')
        for book in book_list:
            book_xpath = book.xpath('div/div[contains(@class,"cart-tag")]')
            if len(book_xpath) == 0:
                break
            comic_book = ComicBook()
            comic_book.name = book_xpath[0].text.strip()
            vol_list = book.xpath('ul[contains(@class,"chapter-list")]/li')
            for vol in vol_list:
                v = vol.xpath('a')[0]
                comic_book.vols.append(ComicVolume(v.text.strip(), self.base_url + '/' + v.attrib.get('href'), comic_book.name))
            comic_book.vols.reverse()
            comic.books.append(comic_book)
        return comic

    def __parse_imgs__(self, url):
        root = self.__parse_html__(url, 'gbk')
        img_list = root.xpath('//div[contains(@class,"chapter-content")]/img')
        arr = []
        for img in img_list:
            arr.append(img.attrib.get('data-original'))
        return arr

