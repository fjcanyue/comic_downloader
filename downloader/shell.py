import cmd
import pkgutil
import inspect
import importlib
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions

from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

from downloader.comic import ComicSource
import downloader


class Shell(cmd.Cmd):
    intro = """
    欢迎使用动漫下载器，输入 help 或者 ? 查看帮助。
    支持的命令有：
    * s: 搜索动漫，从所有支持的源中搜索。输入s <搜索关键字>。例如：输入 s 猎人
    * d: 全量下载动漫，输入d <搜索结果序号/动漫URL地址>。例如：输入 d 12，或者d https://www.maofly.com/manga/38316.html
    * i: 查看动漫详情，输入i <搜索结果序号/动漫URL地址>。例如：输入 i 12，或者i https://www.maofly.com/manga/13954.html
    * v: 按范围下载动漫，需要先执行查看动漫详情命令，根据详情的序号列表，指定下载范围。支持三种模式：
      - 输入v <章节序号>，下载该章节下的所有动漫。例如：输入 v 0。
      - 输入v <章节序号> <截止序号>，下载该章节下，从章节开始到截止序号的动漫。例如：输入 v 0 12
      - 输入v <章节序号> <起始序号> <截止序号>，下载该章节下，从起始位置到截止位置的动漫。例如：输入 v 0 12 18
    * source: 手动切换动漫下载网站源 (可选)。
    * q: 退出动漫下载器
    """
    prefix = '动漫下载器> '
    prompt = prefix

    def __init__(self, output_path, overwrite=False):
        super().__init__()
        self.console = Console()
        self.context = Context(self.console)
        self.context.create(output_path)
        self.overwrite = overwrite

        # 动态发现源
        self.source_map = self._discover_sources()
        self.source_options = list(self.source_map.keys())  # 存储源名称列表，方便按索引访问
        self.sources = {}

    def _discover_sources(self):
        """动态发现 downloader 包下的所有 ComicSource 实现"""
        sources = {}
        # 获取 downloader 包的路径
        package_path = os.path.dirname(downloader.__file__)

        for _, name, _ in pkgutil.iter_modules([package_path]):
            if name == 'comic' or name == 'shell' or name == 'scroll_loader':
                continue

            try:
                # 动态导入模块
                module = importlib.import_module(f'downloader.{name}')
                # 查找模块中的 ComicSource 子类
                for item_name, item in inspect.getmembers(module, inspect.isclass):
                    if issubclass(item, ComicSource) and item is not ComicSource:
                        # 使用模块名作为 key，或者可以添加一个 name 属性到 ComicSource 子类中
                        # 这里假设文件名对应源名称 (例如 boya.py -> boya)
                        sources[name] = item
            except Exception as e:
                self.console.print(f"Failed to load module {name}: {e}", style="bold red")

        return sources

    def do_source(self, arg):
        """选择动漫下载网站源。输入 source  后，根据提示选择源序号。"""
        self.console.print('请选择动漫下载网站源:')
        for index, source_name in enumerate(self.source_options):
            self.console.print(f'{index + 1}. {source_name}')

        while True:
            try:
                source_index_str = input('请输入网站源序号: ')
                if not source_index_str:  # 用户直接回车，重新显示列表
                    self.console.print('请选择动漫下载网站源:')
                    for index, source_name in enumerate(self.source_options):
                        self.console.print(f'{index + 1}. {source_name}')
                    continue  # 继续下一次循环，等待用户输入
                source_index = int(source_index_str) - 1  # 序号从1开始，索引从0开始
                if 0 <= source_index < len(self.source_options):
                    source_name = self.source_options[source_index]
                    self.__switch_source(source_name)
                    break  # 选择成功，退出循环
                self.console.print(f'无效的序号，请输入 1 到 {len(self.source_options)} 之间的序号。')
            except ValueError:
                self.console.print('请输入有效的数字序号。')

    def __switch_source(self, source_name):
        """切换动漫源"""
        if self.context.source and self.context.source.name == source_name:
            return
        self.console.print(f'正在切换到{source_name}动漫下载网站源...')

        if source_name not in self.sources:
             source_class = self.source_map[source_name]
             self.sources[source_name] = source_class(
                self.context.output_path, self.context.http, self.context.driver,
                overwrite=self.overwrite
            )

        self.context.source = self.sources[source_name]
        # self.prompt = self.prefix + self.context.source.name + '> '

    def do_s(self, arg):
        """搜索动漫，输入s <搜索关键字>，例如：s 猎人"""
        if not arg:
            self.console.print('请输入搜索关键字！')
            return

        self.context.reset_comic()
        self.context.searched_results = []

        # 遍历所有源进行搜索
        with self.console.status("正在搜索...", spinner="dots"):
            for source_name in self.source_options:
                try:
                    # 确保源已初始化
                    if source_name not in self.sources:
                        source_class = self.source_map[source_name]
                        self.sources[source_name] = source_class(
                            self.context.output_path, self.context.http, self.context.driver,
                            overwrite=self.overwrite
                        )

                    source = self.sources[source_name]
                    # self.console.print(f'正在 {source.name} 中搜索...')
                    results = source.search(arg)

                    # 每个源最多取10个结果
                    count = 0
                    for comic in results:
                        if count >= 10:
                            break
                        comic.source = source_name
                        self.context.searched_results.append(comic)
                        count += 1
                except Exception as e:
                    self.console.print(f'在 {source_name} 中搜索失败: {e}', style="bold red")

        table = Table(title="搜索结果")
        table.add_column("Index", justify="right", style="cyan", no_wrap=True)
        table.add_column("Source", style="magenta")
        table.add_column("Author", style="green")
        table.add_column("Name", style="bold yellow")
        table.add_column("URL", style="blue")

        for index, comic in enumerate(self.context.searched_results):
            source_obj = self.sources.get(comic.source)
            source_display = getattr(source_obj, 'name', comic.source)
            table.add_row(
                str(index),
                source_display,
                comic.author if comic.author else "N/A",
                comic.name if comic.name else "N/A",
                comic.url if comic.url else "N/A"
            )

        self.console.print(table)

    def do_i(self, arg):
        """查看动漫详情，输入i <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/13954.html"""
        if not arg:
            self.console.print('请输入动漫URL地址或者搜索结果序号！')
            return

        url = None
        if arg.isdigit():
            idx = int(arg)
            if self.context.searched_results and len(self.context.searched_results) > idx:
                comic = self.context.searched_results[idx]
                url = comic.url
                if comic.source:
                    self.__switch_source(comic.source)
            else:
                self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
                return
        else:
            # 尝试根据URL匹配源
            matched_source = None
            for source_name, source_class in self.source_map.items():
                if hasattr(source_class, 'base_url') and arg.startswith(source_class.base_url):
                    matched_source = source_name
                    break

            if matched_source:
                self.__switch_source(matched_source)
                url = arg
            else:
                 # 如果没有匹配到，检查当前是否已经选择了源
                 if self.context.source and hasattr(self.context.source, 'base_url') and arg.startswith(self.context.source.base_url):
                     url = arg
                 else:
                    self.console.print('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
                    return

        if not self.context.source:
             self.console.print('无法确定该动漫所属的源，请先搜索或手动选择源。')
             return

        with self.console.status("正在获取详情...", spinner="dots"):
            self.context.comic = self.context.source.info(url)

        if self.context.comic is None:
            self.console.print('未能获取动漫详情，请检查输入的地址或稍后重试。', style="bold red")
            return

        md_content = f"# {self.context.comic.name}\n\n"

        if self.context.comic.metadata:
            md_content += "## Metadata\n"
            for meta in self.context.comic.metadata:
                md_content += f"- **{meta['k']}**: {meta['v']}\n"

        self.console.print(Markdown(md_content))

        # Display chapters/volumes using tables
        for book_index, book in enumerate(self.context.comic.books):
            # Create a table for each book
            # Using a multi-column layout for compactness: 3 columns of (Index, Name)

            table = Table(title=f"{book_index}: {book.name}", show_header=False, box=None, padding=(0, 2))

            COLUMNS = 3
            for _ in range(COLUMNS):
                table.add_column("Index", justify="right", style="cyan")
                table.add_column("Name", style="white")

            row_buffer = []
            for index, vol in enumerate(book.vols):
                row_buffer.extend([str(index), vol.name])
                if len(row_buffer) == COLUMNS * 2:
                    table.add_row(*row_buffer)
                    row_buffer = []

            if row_buffer:
                # Pad the rest
                while len(row_buffer) < COLUMNS * 2:
                    row_buffer.extend(["", ""])
                table.add_row(*row_buffer)

            self.console.print(table)


    def do_v(self, arg):
        """下载动漫，输入v <章节序号> <起始序号> <截止序号>，例如：v 0 11 12"""
        if not self.context.source:
            self.console.print('请您先选择动漫下载网站源！')
            return
        if not arg:
            self.console.print('请输入动漫章节序号！')
            return
        if self.context.comic is None:
            self.console.print('请先查看动漫详情！')
            return

        args = arg.split()
        book_index = int(args[0])
        if len(self.context.comic.books) <= book_index:
            self.console.print('请输入正确的动漫章节序号！')
            return

        book = self.context.comic.books[book_index]
        if len(args) == 1:
            vols = book.vols
        elif len(args) == 2:
            vol_to = int(args[1])
            if len(book.vols) <= vol_to:
                self.console.print('请输入正确的截止序号！')
                return

            vols = book.vols[0 : vol_to + 1]
        elif len(args) == 3:
            vol_from = int(args[1])
            if len(book.vols) <= vol_from or vol_from < 0:
                self.console.print('请输入正确的起始序号！')
                return
            vol_to = int(args[2])
            if len(book.vols) <= vol_to or vol_from > vol_to:
                self.console.print('请输入正确的截止序号！')
                return
            vols = book.vols[vol_from : vol_to + 1]
        else:
            self.console.print('参数错误，请重新输入！')
            return
        self.context.source.download_vols(self.context.comic.name, book.name, vols)

    def do_d(self, arg):
        """全量下载动漫，输入d <搜索结果序号/动漫URL地址>，例如：d 12，或者d https://www.maofly.com/manga/38316.html"""
        if not arg:
            if self.context.comic is None:
                self.console.print('请先查看动漫详情！')
                return
            if not self.context.source:
                 self.console.print('当前没有选中的动漫源！')
                 return
            self.context.source.download_full(self.context.comic)
        elif arg.isdigit():
            idx = int(arg)
            if self.context.searched_results and len(self.context.searched_results) > idx:
                comic = self.context.searched_results[idx]
                if comic.source:
                    self.__switch_source(comic.source)

                if self.context.source:
                    self.context.source.download_full_by_url(comic.url)
                else:
                    self.console.print('无法确定源，无法下载。')
                    return
            else:
                self.console.print('请先搜索动漫，或输入正确的搜索结果序号！')
                return
        else:
            # Try to match URL to source
            matched_source = None
            for source_name, source_class in self.source_map.items():
                if hasattr(source_class, 'base_url') and arg.startswith(source_class.base_url):
                    matched_source = source_name
                    break

            if matched_source:
                 self.__switch_source(matched_source)
            elif self.context.source and hasattr(self.context.source, 'base_url') and arg.startswith(self.context.source.base_url):
                 pass # already in correct source context
            else:
                self.console.print('请输入完整的动漫地址，且确保该地址属于支持的动漫源！')
                return

            self.context.source.download_full_by_url(arg)

        # self.context.searched_results.clear() # Maybe don't clear results so user can download another one?
        self.console.print('下载完成', style="bold green")

    def do_q(self, arg):
        """退出动漫下载器"""
        self.context.destroy()
        self.console.print('感谢使用，再会！')
        return True


class Context:
    """
    命令行上下文类。
    """

    def __init__(self, console):
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
        self.console = console
        self.reset()

    def create(self, output_path):
        self.output_path = output_path
        print(f'动漫文件本机存储路径为: {output_path}')

        retry_strategy = Retry(
            total=3, status_forcelist=[400, 429, 500, 502, 503, 504], allowed_methods=['GET']
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.http = requests.Session()
        self.http.headers.update(
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            }
        )
        self.http.mount('https://', adapter)
        self.http.mount('http://', adapter)

        self.init_driver()

    def init_driver(self):
        """尝试初始化 WebDriver，支持 Firefox, Chrome, Edge"""
        drivers = [
            ('Firefox', webdriver.Firefox, FirefoxOptions),
            ('Chrome', webdriver.Chrome, ChromeOptions),
            ('Edge', webdriver.Edge, EdgeOptions)
        ]

        for name, driver_cls, options_cls in drivers:
            try:
                options = options_cls()
                options.add_argument('--headless')
                # 某些驱动可能需要特定的 options 设置才能在某些环境下运行
                if name == 'Chrome':
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')

                self.driver = driver_cls(options=options)
                # self.console.print(f"成功初始化 {name} 浏览器驱动", style="green")
                return
            except Exception as e:
                # self.console.print(f"初始化 {name} 驱动失败: {e}", style="yellow")
                continue

        self.console.print("所有浏览器驱动初始化失败，请确保已安装 Firefox/Chrome/Edge 及其对应驱动。", style="bold red")

    def destroy(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

    def reset(self):
        self.source = None
        self.reset_comic()

    def reset_comic(self):
        self.comic = None
        self.reset_result()

    def reset_result(self):
        self.searched_results = []
