from downloader.comic import Comic, ComicBook, ComicSource, ComicVolume


class DmzjComic(ComicSource):
    name = '动漫之家'
    base_url = 'http://manhua.dmzj.com'
    base_img_url = 'http://images.dmzj.com'
    download_interval = 5

    def __init__(self, output_dir, http, driver):
        super().__init__(output_dir, http, driver)

    def search(self, keyword):
        r = self.http.get(
            'http://sacg.dmzj.com/comicsum/search.php?s=%s' % (keyword))
        js = r.text + 'return g_search_data;'
        results = self.driver.execute_script(js)
        arr = []
        for book in results:
            comic = Comic()
            comic.url = 'http:' + book['comic_url_raw']
            comic.name = book['comic_name']
            comic.author = book['comic_author']
            arr.append(comic)
        return arr

    def info(self, url):
        r = self.session.get(url)
        comic = Comic()
        comic.url = url
        comic.name = r.html.xpath(
            '//span[@class="anim_title_text"] //h1')[0].text
        meta_table = r.html.xpath('//div[@class="anim-main_list"]/table/tr')
        for meta in meta_table:
            print('%s %s' % (meta.xpath('tr/th')
                  [0].text, meta.xpath('tr/td')[0].text))
        book_list = r.html.xpath(
            '//div[@class="middleright"]/div[@class="middleright_mr"]/div[@class="photo_part"]')
        vol_divs = r.html.xpath(
            '//div[@class="cartoon_online_border" or @class="cartoon_online_border_other"]')
        for index, book in enumerate(book_list):
            book_xpath = book.xpath('//h2')
            if (len(book_xpath) == 0):
                break
            comic_book = ComicBook()
            comic_book.name = book_xpath[0].text
            vol_list = vol_divs[index].xpath('div/ul/li')
            for vol in vol_list:
                comic_book.vols.append(ComicVolume(
                    vol.text, self.base_url + '/' + vol.xpath('li/a/@href')[0], comic_book.name))
            comic.books.append(comic_book)
        return comic

    def __parse_imgs__(self, url):
        self.driver.get(url)
        imgs = self.driver.execute_script(
            'eval("var __a__=" + pages);return __a__;')
        return imgs
