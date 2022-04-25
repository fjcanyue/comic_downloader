import os
import shutil
from time import sleep

from requests_html import HTMLSession
from tqdm import tqdm

from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume


class MaoflyComic(ComicSource):
    name = '漫画猫'
    base_url = 'https://www.maofly.com'
    base_img_url = 'https://mao.mhtupian.com/uploads'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        self.output_dir = output_dir
        self.http = http
        self.driver = driver

        self.http.headers.update({
            'referer': self.base_url
        })

        r = self.http.get('%s/static/js/string.min.js' % self.base_url)
        self.jsstring = r.text

        self.session = HTMLSession()

    def search(self, keyword):
        r = self.session.get('%s/search.html?q=%s' % (self.base_url, keyword))
        main = r.html.xpath('//div[contains(@class,"comic-main-section")]')
        if (len(main) == 0):
            print('没有找到页面关键元素，搜索失败，请检查XPath是否正确。')
            return
        else:
            main = main[0]
        result = main.xpath('//div[@class="text-muted"]')[0].text
        print(result)
        book_list = main.xpath('//div[contains(@class,"comicbook-index")]')
        arr = []
        for book in book_list:
            b = book.xpath('div/a')[0]
            comic = Comic()
            comic.url = b.attrs.get('href')
            comic.name = b.attrs.get('title')
            author_xpath = book.xpath(
                'div/div[contains(@class,"comic-author")]')
            if (len(author_xpath) > 0):
                comic.author = author_xpath[0].text
            arr.append(comic)
        return arr

    def info(self, url):
        r = self.session.get(url)
        comic = Comic()
        comic.url = url
        comic.name = r.html.xpath('//td[@class="comic-titles"]')[0].text
        meta_table = r.html.xpath(
            '//table[contains(@class,"comic-meta-data-table")]/tbody/tr')
        for meta in meta_table:
            print('%s: %s' % (meta.xpath('tr/th')
                  [0].text, meta.xpath('tr/td')[0].text))
        book_list = r.html.xpath('//div[@id="comic-book-list"]/div')
        for book in book_list:
            book_xpath = book.xpath('div/div/div/h2')
            if (len(book_xpath) == 0):
                break
            comic_book = ComicBook()
            comic_book.name = book_xpath[0].text
            vol_list = book.xpath('div/ol/li/a')
            for vol in vol_list:
                comic_book.vols.append(ComicVolume(vol.attrs.get(
                    'title'), vol.attrs.get('href'), comic_book.name))
            comic.books.append(comic_book)
        return comic

    def download_comic(self, url, reversed=False, end_url=None):
        r = self.session.get(url)
        name = r.html.xpath('//td[@class="comic-titles"]')[0].text
        path = os.path.join(self.output_dir, name)
        os.makedirs(path, exist_ok=True)
        book_list = r.html.xpath('//div[@id="comic-book-list"]/div')
        for book in book_list:
            book_xpath = book.xpath('div/div/div/h2')
            if (len(book_xpath) == 0):
                break
            book_name = book_xpath[0].text
            book_path = os.path.join(path, book_name)
            vol_list = book.xpath('div/ol/li/a')
            arr = []
            if reversed:
                vol_list.reverse()
            for vol in vol_list:
                vol_name = vol.attrs.get('title')
                vol_url = vol.attrs.get('href')
                if end_url and vol_url == end_url:
                    break
                else:
                    arr.append({'name': vol_name, 'url': vol_url})
            for vol in tqdm(arr, desc=book_name):
                self.download_vol(book_path, vol['name'], vol['url'])

    def download_vols(self, comic_name, book_name, vols):
        path = os.path.join(self.output_dir, comic_name, book_name)
        os.makedirs(path, exist_ok=True)
        for vol in tqdm(vols, desc=book_name):
            self.download_vol(path, vol.name, vol.url)

    def download_vol(self, path, vol_name, url):
        '下载漫画卷'
        img_data = self.__find_img_data__(url)
        # print(img_data)
        imgs = self.__decode_img_data__(img_data)
        # print(imgs)
        path = os.path.join(path, vol_name)
        self.__download_vol_images__(path, vol_name, imgs.split(','))

    def __find_img_data__(self, url):
        '查找img_data变量值'
        r = self.session.get(url)
        img_data = r.html.search('let img_data = "{}"')
        # print(img_data)
        return img_data[0]

    def __decode_img_data__(self, img_data):
        '解码img_data变量值'
        js = '%sreturn LZString.decompressFromBase64("%s");' % (
            self.jsstring, img_data)
        imgs = self.driver.execute_script(js)
        return imgs

    def __download_vol_images__(self, path, vol_name, imgs):
        '下载图片'
        os.makedirs(path, exist_ok=True)
        for index, img in enumerate(tqdm(imgs, desc=vol_name)):
            sleep(self.download_interval)
            f = '%s/%04d.jpg' % (path, (index + 1))
            # print('Downloading image: %s, to %s' % (img, f))
            r = self.http.get(self.base_img_url + '/' + img)
            # print('Status code: %d' % r.status_code)
            with open(f, 'wb') as f:
                f.write(r.content)
        shutil.make_archive(path, 'zip', path)
