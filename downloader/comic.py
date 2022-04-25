from abc import ABC, abstractmethod


class ComicSource(ABC):
    @abstractmethod
    def search(self, keyword):
        """搜索动漫

        Args:
            keyword (string): 搜索关键字

        Returns:
            array: 搜索结果
        """
        pass

    @abstractmethod
    def info(self, url):
        """查看动漫详细信息

        Args:
            url (string): 动漫URL地址
        """
        pass

    @abstractmethod
    def download_comic(self, url):
        """下载指定动漫

        Args:
            url (string): 动漫URL地址
        """
        pass


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
    def __init__(self, name, url, book_name = None):
        self.name = name
        self.url = url
        self.book_name = book_name
