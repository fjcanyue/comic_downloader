from abc import ABC, abstractmethod


class Comic(ABC):
    @abstractmethod
    def search(self, keyword):
        '搜索漫画'
        pass

    @abstractmethod
    def download_comic(self, url):
        '下载指定漫画'
        pass
