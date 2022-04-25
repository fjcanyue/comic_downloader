import cmd

import requests
from requests.adapters import HTTPAdapter
from downloader.maofly import MaoflyComic
from requests.packages.urllib3.util.retry import Retry
from selenium import webdriver
from selenium.webdriver.firefox.options import Options


class Shell(cmd.Cmd):
    intro = '''
    欢迎使用动漫下载器，输入 help 或者 ? 查看帮助。
    您可以输入下列命令来切换动漫下载网站源，目前支持的网站有：
    * maofly: 漫画猫（默认）
    输入动漫下载网站源后，支持的命令有：
    * s: 搜索动漫，输入s <搜索关键字>，例如：s 猎人
    * i: 查看动漫详情，输入i <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html
    * d: 全量下载动漫，输入s <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html  
    通用命令有：
    * q: 退出动漫下载器
    '''
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(self, output_path):
        super(Shell, self).__init__()
        self.context = Context()
        self.context.create(output_path)
        # sources = ComicSource.__subclasses__()
        # if len(sources) == 1:
        self.do_maofly()

    def do_maofly(self):
        '选择漫画猫做为动漫下载网站源'
        print('正在初始化漫画猫动漫下载网站源，请稍等...')
        self.context.reset()
        self.context.source = MaoflyComic(
            self.context.output_path, self.context.http, self.context.driver)
        self.prompt = self.prefix + self.context.source.name + '> '

    def do_s(self, arg):
        '搜索动漫，输入s <搜索关键字>，例如：s 猎人'
        if self.context.source:
            self.context.reset_comic()
            self.context.searched_results = self.context.source.search(arg)
            for index, comic in enumerate(self.context.searched_results):
                print('%d: %s %s %s' %
                      (index, comic.author, comic.name, comic.url))
        else:
            print('请您先选择动漫下载网站源！')

    def do_i(self, arg):
        '查看动漫详情，输入i <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html'
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if arg is None:
            print('请输入动漫URL地址或者搜索结果序号！')
            return
        url = arg
        if arg.isdigit():
            if self.context.searched_results:
                url = self.context.searched_results[int(arg)].url
            else:
                print('请您先搜索动漫！')
                return
        self.context.comic = self.context.source.info(url)

        for book_index, book in enumerate(self.context.comic.books):
            print('{:=^80}'.format('%2d: %s' % (book_index, book.name)))
            line = None
            for index, vol in enumerate(book.vols):
                s = '%3d: %s' % (index, vol.name)
                s = '{:-<40}'.format(s)
                if index % 2 == 1:
                    print(line + s)
                    line = ''
                else:
                    line = s

    def do_dv(self, arg):
        '下载动漫，输入dv <序号> <地址>，例如：d 0 11 12'
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if arg is None:
            print('请输入动漫URL地址或者搜索结果序号！')
            return
        if self.context.comic is None:
            print('请先查看动漫详情！')
            return
        args = arg.split()
        book_index = int(args[0])
        book = self.context.comic.books[book_index]
        if len(args) == 1:
            vols = book.vols
        elif len(args) == 2:
            vol_to = int(args[1])
            vols = book.vols[0:vol_to + 1]
        elif len(args) == 3:
            vol_from = int(args[1])
            vol_to = int(args[2])
            vols = book.vols[vol_from:vol_to + 1]
        self.context.source.download_vols(self.context.comic.name, book.name, vols)

    def do_d(self, arg):
        '下载动漫，输入d <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html'
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if arg is None:
            print('请输入动漫URL地址或者搜索结果序号！')
            return
        url = arg
        if arg.isdigit():
            if self.context.searched_results:
                url = self.context.searched_results[int(arg)].url
            else:
                print('请您先搜索动漫！')
                return
        self.context.source.download_comic(url)
        self.context.searched_results.clear()
        print('下载完成')

    def do_q(self, arg):
        '退出动漫下载器'
        self.context.destory()
        print('感谢使用，再会！')
        return True


class Context:
    '''
    命令行上下文类。
    '''

    def __init__(self):
        self.reset()

    def create(self, output_path):
        self.output_path = output_path
        print('动漫文件本机存储路径为: %s' % output_path)

        retry_strategy = Retry(
            total=3,
            status_forcelist=[400, 429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"
        })
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)

        options = Options()
        options.add_argument('--headless')
        self.driver = webdriver.Firefox(options=options)
        # self.driver = webdriver.Chrome(options=options)
        # self.driver.get(url)

    def destory(self):
        self.driver.close()

    def reset(self):
        self.source = None
        self.reset_comic()

    def reset_comic(self):
        self.comic = None
        self.reset_result()

    def reset_result(self):
        self.searched_results = []
