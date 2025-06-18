import cmd

import requests
from requests.adapters import HTTPAdapter
from downloader.dmzj import DmzjComic
from downloader.manhuagui import ManhuaguiComic
from downloader.maofly import MaoflyComic
from downloader.thmh import TmhComic
from downloader.boya import BoyaComic
from downloader.dumanwu import DumanwuComic

from requests.packages.urllib3.util.retry import Retry

from selenium import webdriver
from selenium.webdriver.firefox.options import Options


class Shell(cmd.Cmd):
    intro = '''
    欢迎使用动漫下载器，输入 help 或者 ? 查看帮助。
    您可以输入下列命令来切换动漫下载网站源，目前支持的网站有：
    * dumanwu: 读漫屋
    输入动漫下载网站源后，支持的命令有：
    * s: 搜索动漫，输入s <搜索关键字>。例如：输入 s 猎人
    * d: 全量下载动漫，输入d <搜索结果序号/动漫URL地址>。例如：输入 d 12，或者d https://www.maofly.com/manga/38316.html
    * i: 查看动漫详情，输入i <搜索结果序号/动漫URL地址>。例如：输入 i 12，或者i https://www.maofly.com/manga/13954.html
    * v: 按范围下载动漫，需要先执行查看动漫详情命令，根据详情的序号列表，指定下载范围。支持三种模式：
      - 输入v <章节序号>，下载该章节下的所有动漫。例如：输入 v 0。
      - 输入v <章节序号> <截止序号>，下载该章节下，从章节开始到截止序号的动漫。例如：输入 v 0 12
      - 输入v <章节序号> <起始序号> <截止序号>，下载该章节下，从起始位置到截止位置的动漫。例如：输入 v 0 12 18
    通用命令有：
    * q: 退出动漫下载器
    '''
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(self, output_path):
        super(Shell, self).__init__()
        self.context = Context()
        self.context.create(output_path)
        # 定义支持的漫画源映射
        self.source_map = {
            'dumanwu': DumanwuComic,
        }
        self.source_options = list(self.source_map.keys()) # 存储源名称列表，方便按索引访问
        self.do_source(None)

    def do_source(self, arg):
        """选择动漫下载网站源。输入 source  后，根据提示选择源序号。"""
        print('请选择动漫下载网站源:')
        for index, source_name in enumerate(self.source_options):
            print(f'{index + 1}. {source_name}')

        while True:
            try:
                source_index_str = input('请输入网站源序号: ')
                if not source_index_str: # 用户直接回车，重新显示列表
                    print('请选择动漫下载网站源:')
                    for index, source_name in enumerate(self.source_options):
                        print(f'{index + 1}. {source_name}')
                    continue # 继续下一次循环，等待用户输入
                source_index = int(source_index_str) - 1 # 序号从1开始，索引从0开始
                if 0 <= source_index < len(self.source_options):
                    source_name = self.source_options[source_index]
                    print(f'正在初始化{source_name}动漫下载网站源，请稍等...')
                    self.context.reset()
                    source_class = self.source_map[source_name]
                    self.context.source = source_class(
                        self.context.output_path, self.context.http, self.context.driver)
                    self.prompt = self.prefix + self.context.source.name + '> '
                    break # 选择成功，退出循环
                else:
                    print(f'无效的序号，请输入 1 到 {len(self.source_options)} 之间的序号。')
            except ValueError:
                print('请输入有效的数字序号。')

    def do_s(self, arg):
        """搜索动漫，输入s <搜索关键字>，例如：s 猎人"""
        if not arg:
            print('请输入搜索关键字！')
            return
        if self.context.source:
            self.context.reset_comic()
            self.context.searched_results = self.context.source.search(arg)
            for index, comic in enumerate(self.context.searched_results):
                print('%d: %s %s %s' %
                      (index, comic.author, comic.name, comic.url))
        else:
            print('请您先选择动漫下载网站源！')

    def do_i(self, arg):
        """查看动漫详情，输入i <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html"""
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if not arg:
            print('请输入动漫URL地址或者搜索结果序号！')
            return

        if arg.isdigit():
            if self.context.searched_results and len(self.context.searched_results) > int(arg):
                url = self.context.searched_results[int(arg)].url
            else:
                print('请先搜索动漫，或输入正确的搜索结果序号！')
                return
        elif arg.startswith(self.context.source.base_url):
            url = arg
        else:
            print('请输入完整的动漫地址！')
            return

        self.context.comic = self.context.source.info(url)

        print(__build_fixed_string__(' %s ' %
              self.context.comic.name, 100, '{:=^{len}}'))

        for meta in self.context.comic.metadata:
            print('%s: %s' % (meta['k'], meta['v']))

        for book_index, book in enumerate(self.context.comic.books):
            print(__build_fixed_string__(' %d: %s ' %
                  (book_index, book.name), 100, '{:=^{len}}'))
            line = ''
            for index, vol in enumerate(book.vols):
                s = '%3d: %s' % (index, vol.name)
                s = __build_fixed_string__(s, 40, '{:<{len}}')
                if index % 3 == 2 or index == len(book.vols) - 1:
                    print(line + s)
                    line = ''
                else:
                    line += s

    def do_v(self, arg):
        """下载动漫，输入v <章节序号> <起始序号> <截止序号>，例如：v 0 11 12"""
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if not arg:
            print('请输入动漫章节序号！')
            return
        if self.context.comic is None:
            print('请先查看动漫详情！')
            return

        args = arg.split()
        book_index = int(args[0])
        if len(self.context.comic.books) <= book_index:
            print('请输入正确的动漫章节序号！')
            return

        book = self.context.comic.books[book_index]
        if len(args) == 1:
            vols = book.vols
        elif len(args) == 2:
            vol_to = int(args[1])
            if len(book.vols) <= vol_to:
                print('请输入正确的截止序号！')
                return

            vols = book.vols[0:vol_to + 1]
        elif len(args) == 3:
            vol_from = int(args[1])
            if len(book.vols) <= vol_from or vol_from < 0:
                print('请输入正确的起始序号！')
                return
            vol_to = int(args[2])
            if len(book.vols) <= vol_to or vol_from > vol_to:
                print('请输入正确的截止序号！')
                return
            vols = book.vols[vol_from:vol_to + 1]
        self.context.source.download_vols(
            self.context.comic.name, book.name, vols)

    def do_d(self, arg):
        """全量下载动漫，输入d <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html"""
        if not self.context.source:
            print('请您先选择动漫下载网站源！')
            return
        if not arg:
            if self.context.comic is None:
                print('请先查看动漫详情！')
                return
            self.context.source.download_full(self.context.comic)
        elif arg.isdigit():
            if self.context.searched_results and len(self.context.searched_results) > int(arg):
                self.context.source.download_full_by_url(
                    self.context.searched_results[int(arg)].url)
            else:
                print('请先搜索动漫，或输入正确的搜索结果序号！')
                return
        elif arg.startswith(self.context.source.base_url):
            self.context.source.download_full_by_url(arg)
        else:
            print('请输入完整的动漫地址！')
            return
        self.context.searched_results.clear()
        print('下载完成')

    def do_q(self, arg):
        """退出动漫下载器"""
        self.context.destory()
        print('感谢使用，再会！')
        return True


class Context:
    """
    命令行上下文类。
    """

    def __init__(self):
        self.output_path = None
        '本机存储路径'
        self.http = None
        '本机存储路径'
        self.searched_results = None
        '动漫搜索结果数组对象'
        self.comic = None
        '当前查看的动漫对象'
        self.source = None
        '动漫网站源'
        self.driver = None
        '网页驱动'
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6"
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


def __build_fixed_string__(string, length, formatter):
    # 修复 GBK 编码无法处理特殊字符导致的 UnicodeEncodeError
    format_len = length - len(string.encode('GBK', errors='ignore')) + len(string)
    if (0 > format_len):
        format_len = 0
    return formatter.format(string, len=format_len)
