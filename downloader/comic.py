import os
import shutil
from abc import ABC, abstractmethod
from time import sleep

from requests_html import HTMLSession
from tqdm import tqdm


class ComicSource(ABC):

    def __init__(self, output_dir, http, driver):
        """动漫源构造函数

        Args:
            output_dir (str): 下载根目录
            http (Session): requests 会话对象
            driver (WebDriver): Selenium 网页驱动对象
        """
        self.output_dir = output_dir
        '''下载根目录'''
        self.http = http
        '''requests 会话对象'''
        self.driver = driver
        '''Selenium 网页驱动对象'''

        self.http.headers.update({
            'referer': self.base_url
        })

        self.session = HTMLSession()
        '''requests_html 会话对象'''

    @abstractmethod
    def search(self, keyword):
        """搜索动漫

        Args:
            keyword (str): 搜索关键字

        Returns:
            array: 搜索结果
        """
        pass

    @abstractmethod
    def info(self, url):
        """查看动漫详细信息

        Args:
            url (str): 动漫URL地址
        """
        pass

    def download_full_by_url(self, url):
        """全量下载指定动漫

        Args:
            url (str): 动漫URL地址
        """
        self.__download_vol__(self.info(url))

    def download_full(self, comic):
        """全量下载指定动漫

        Args:
            comic (Comic): 动漫对象
        """
        path = os.path.join(self.output_dir, comic.name)
        os.makedirs(path, exist_ok=True)
        for book in comic.books:
            book_path = os.path.join(path, book.name)
            for vol in tqdm(book.vols, desc=book.name):
                self.__download_vol__(book_path, vol.name, vol.url)

    @abstractmethod
    def __parse_imgs__(self, url):
        """从动漫卷/话页面解析动漫图片URL地址数组

        Args:
            url (str): 动漫卷/话URL地址

        Returns:
            array: 图片URL地址数组
        """
        pass

    def download_vols(self, comic_name, book_name, vols):
        """按指定范围下载动漫

        Args:
            comic_name (str): 动漫名称
            book_name (str): 动漫章节名称
            vols (array): 待下载的动漫卷/话列表
        """
        path = os.path.join(self.output_dir, comic_name, book_name)
        os.makedirs(path, exist_ok=True)
        for vol in tqdm(vols, desc=book_name):
            self.__download_vol__(path, vol.name, vol.url)

    def __download_vol__(self, path, vol_name, url):
        """下载动漫卷/话

        Args:
            path (str): 下载路径
            vol_name (str): 动漫卷/话名称
            url (str): 动漫卷/话URL地址
        """
        imgs = self.__parse_imgs__(url)
        path = os.path.join(path, vol_name)
        self.__download_vol_images__(path, vol_name, imgs)
        pass

    def __download_vol_images__(self, path, vol_name, imgs):
        '下载图片'
        os.makedirs(path, exist_ok=True)
        for index, img in enumerate(tqdm(imgs, desc=vol_name)):
            sleep(self.download_interval)
            f = '%s/%04d.jpg' % (path, (index + 1))
            url = self.base_img_url + '/' + img
            # print('Downloading image: %s, to %s' % (url, f))
            r = self.http.get(url)
            # print('Status code: %d' % r.status_code)
            with open(f, 'wb') as f:
                f.write(r.content)
        shutil.make_archive(path, 'zip', path)


class Comic:
    def __init__(self):
        self.name = None
        self.author = None
        self.url = None
        self.books = []


class ComicBook:
    def __init__(self):
        self.name = None
        self.vols = []


class ComicVolume:
    def __init__(self, name, url, book_name=None):
        self.name = name
        self.url = url
        self.book_name = book_name
