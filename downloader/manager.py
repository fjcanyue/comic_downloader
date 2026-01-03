from typing import Callable, List, Optional
import requests
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from loguru import logger

from downloader.comic import Comic
from downloader.dumanwu import DumanwuComic
from downloader.morui import MoruiComic
from downloader.thmh import TmhComic

class ComicManager:
    def __init__(self, output_path: str):
        self.output_path = output_path
        self.http = self._create_http_session()
        self.driver = self._create_webdriver()
        self.searched_results: List[Comic] = []
        self.current_comic: Optional[Comic] = None
        self.current_source = None

        self.source_map = {
            'morui': MoruiComic,
            'dumanwu': DumanwuComic,
            'thmh': TmhComic,
        }
        self.sources = {}

    def _create_http_session(self) -> requests.Session:
        retry_strategy = Retry(
            total=3, status_forcelist=[400, 429, 500, 502, 503, 504], allowed_methods=['GET']
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.headers.update(
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            }
        )
        http.mount('https://', adapter)
        http.mount('http://', adapter)
        return http

    def _create_webdriver(self):
        options = Options()
        options.add_argument('--headless')
        try:
            return webdriver.Firefox(options=options)
        except Exception as e:
            logger.error(f"Failed to initialize Firefox driver: {e}")
            # Try Chrome as fallback? Or just return None and handle it later?
            # Existing code expects a driver.
            # Let's try to just log and re-raise, or return None.
            # If we return None, `_get_source` will pass None to source constructor.
            # Sources use driver for parsing images (dumanwu).
            return None

    def _get_source(self, source_name: str):
        if source_name not in self.sources:
            source_class = self.source_map[source_name]
            self.sources[source_name] = source_class(
                self.output_path, self.http, self.driver
            )
        return self.sources[source_name]

    def search(self, keyword: str) -> List[Comic]:
        self.searched_results = []
        for source_name in self.source_map:
            try:
                source = self._get_source(source_name)
                results = source.search(keyword)
                # Take top 10
                count = 0
                for comic in results:
                    if count >= 10:
                        break
                    comic.source = source_name
                    self.searched_results.append(comic)
                    count += 1
            except Exception as e:
                logger.error(f"Error searching in {source_name}: {e}")
        return self.searched_results

    def get_comic_info(self, url: str) -> Optional[Comic]:
        source_name = self._match_source(url)
        if not source_name:
            # Try to see if we have a current source
            if self.current_source and url.startswith(self.current_source.base_url):
                 source = self.current_source
            else:
                return None
        else:
            source = self._get_source(source_name)
            self.current_source = source

        self.current_comic = source.info(url)
        return self.current_comic

    def _match_source(self, url: str) -> Optional[str]:
        for source_name, source_class in self.source_map.items():
            if url.startswith(source_class.base_url):
                return source_name
        return None

    def download_full(self, url: str, progress_callback: Optional[Callable] = None):
        # progress_callback would need to be passed down to source methods
        # For now, we reuse existing source logic which uses tqdm.
        # Ideally, we should patch or modify source to use callback.
        # But let's first get the logic right.
        source_name = self._match_source(url)
        if source_name:
             source = self._get_source(source_name)
             self.current_source = source
             source.download_full_by_url(url)
        elif self.current_source:
             self.current_source.download_full_by_url(url)

    def close(self):
        if self.driver:
            self.driver.quit()
