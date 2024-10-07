import re
from io import StringIO

from lxml import etree

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume

class ManhuaguiComic(ComicSource):
    name = '看漫画'
    base_url = 'https://www.manhuagui.com/'
    #base_img_url = 'http://imgpc.31mh.com/images/comic'
    download_interval = 5
    
    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        root = self.__parse_html__(
            '%s/s/%s.html' % (self.base_url, keyword))
        main = root.xpath('//div[contains(@class,"book-result")]/ul')
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
            comic.url = '%s/%s' % (self.base_url, b.attrib.get('href'))
            author_list = book.xpath('div[contains(@class,"book-detail")]/dl/dd[3]/span/a')
            authors = []
            for author in author_list:
                authors.append(author.text)
            comic.author = ', '.join(authors)
            comic.name = b.attrib.get('title')
            arr.append(comic)
        return arr

    def info(self, url):
        root = self.__parse_html__(url)
        comic = Comic()
        comic.url = url
        comic.name = root.xpath('//div[contains(@class,"book-title")]/h1')[0].text.strip()
        meta_table = root.xpath(
            '//ul[contains(@class,"detail-list")]/li')
        for meta in meta_table:
            kvs = [meta.xpath('span/strong')[0].text, '']
            link = meta.find('span/a')
            if link is None:
                value = kvs[1]
                if not value:
                    continue
            else:
                value = link.text
            comic.metadata.append({'k': kvs[0], 'v': value.strip()})
        book_list = root.xpath('//div[contains(@class,"chapter-list")]')
        book_index = 0
        for book in book_list:
            comic_book = ComicBook()
            comic_book.name = book.xpath('preceding::h4/span')[book_index].text.strip()
            vol_list = book.xpath('ul/li')
            for vol in vol_list:
                v = vol.xpath('a')[0]
                comic_book.vols.append(ComicVolume(v.xpath('span')[0].text.strip(), self.base_url + '/' + v.attrib.get('href'), comic_book.name))
            comic_book.vols.reverse()
            comic.books.append(comic_book)
            book_index = book_index + 1
        return comic

    def __parse_imgs__(self, url):
        self.driver.get(url)
        imgs = self.driver.execute_script(
            'var _page = 1;var images = [];while(true) {SMH.utils.goPage(_page);if (pVars.page != _page) {break;}images.push(pVars.curFile);_page++;}return images;')
        return imgs
