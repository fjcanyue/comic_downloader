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
    请您先输入动漫下载网站源，目前支持的网站有：
    * maofly: 漫画猫
    输入动漫下载网站源后，支持的命令有：
    * s: 搜索动漫，输入s <搜索关键字>，例如：s 猎人
    * d: 下载动漫，输入s <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html    
    通用命令有：
    * q: 退出动漫下载器
    '''
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(self, output_path):
        super(Shell, self).__init__()
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
        self.search_arr = []

    def do_maofly(self, arg):
        '选择漫画猫做为动漫下载网站源'
        print('正在初始化漫画猫动漫下载网站源，请稍等...')
        self.comic = MaoflyComic(self.output_path, self.http, self.driver)
        self.prompt = self.prefix + '漫画猫> '
        self.search_arr.clear()

    def do_s(self, arg):
        '搜索动漫，输入s <搜索关键字>，例如：s 猎人'
        if hasattr(self, 'comic'):
            self.search_arr = self.comic.search(arg)
            for index, i in enumerate(self.search_arr):
                print('%d: %s %s %s' %
                      (index, i['author'], i['name'], i['url']))
        else:
            print('请您先选择动漫下载网站源！')

    def do_d(self, arg):
        '下载动漫，输入s <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html'
        if not hasattr(self, 'comic'):
            print('请您先选择动漫下载网站源！')
            return
        if arg is None:
            print('请输入动漫URL地址或者搜索结果序号！')
            return
        url = arg
        if arg.isdigit():
            if hasattr(self, 'search_arr'):
                url = self.search_arr[int(arg)]['url']
            else:
                print('请您先搜索动漫！')
                return
        self.comic.download_comic(url)
        self.search_arr.clear()
        print('下载完成')

    def do_q(self, arg):
        '退出动漫下载器'
        self.driver.close()
        print('感谢使用，再会！')
        return True
