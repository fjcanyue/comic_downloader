from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from downloader.models import Comic

DETAIL_CACHE_SIZE = 20


def plain(value: object) -> str:
    """Render website text literally, without terminal control characters."""
    return ''.join(c if c >= ' ' and not '\x7f' <= c <= '\x9f' else ' ' for c in str(value or ''))


@dataclass(frozen=True)
class SearchItem:
    index: int
    source: str
    url: str
    name: str
    author: str

    @property
    def key(self) -> tuple[str, str]:
        return self.source, self.url

    @classmethod
    def from_comic(cls, index: int, comic: Comic) -> SearchItem:
        return cls(
            index, comic.source or '', comic.url or '', comic.name or '未命名', comic.author or ''
        )


@dataclass(frozen=True)
class DownloadAction:
    generation: int
    item: SearchItem

    def matches(self, generation: int, comics: list[Comic]) -> bool:
        if generation != self.generation or not 0 <= self.item.index < len(comics):
            return False
        comic = comics[self.item.index]
        return (comic.source or '', comic.url or '') == self.item.key


@dataclass
class Detail:
    lines: list[str]
    comic: Comic | None = None
    error: str = ''
    row: int = 0


def detail_lines(item: SearchItem, comic: Comic) -> list[str]:
    lines = [
        plain(comic.name or item.name),
        f'来源：{plain(item.source)}',
        f'作者：{plain(comic.author or item.author) or "未提供"}',
        f'URL：{plain(item.url)}',
    ]
    lines.extend(f'{plain(meta.get("k"))}：{plain(meta.get("v"))}' for meta in comic.metadata)
    total = sum(len(book.vols) for book in comic.books)
    lines.extend(['', f'{len(comic.books)} 个分组 · {total} 话'])
    if comic.parse_warnings:
        lines.append('章节解析提示：任务完成不代表网站全书已完整获取。')
        lines.extend(plain(note) for note in comic.parse_warnings)
    if not total:
        lines.append('没有解析到可下载章节，请检查页面或更换来源。')
    for group, book in enumerate(comic.books, 1):
        lines.extend(['', f'[{group}] {plain(book.name) or "默认章节"} · {len(book.vols)} 话'])
        lines.extend(
            f'  {number}  {plain(volume.name)}' for number, volume in enumerate(book.vols, 1)
        )
    return lines


@dataclass
class BrowserState:
    items: tuple[SearchItem, ...]
    keyword: str
    generation: int
    source_names: dict[str, str] = field(default_factory=dict)
    filter_text: str = ''
    indices: list[int] = field(default_factory=list)
    selected: int = 0
    focus: str = 'results'
    list_scroll: int = 0
    message: str = ''
    report: list[str] = field(default_factory=list)
    report_row: int = 0
    show_report: bool = False
    details: OrderedDict[tuple[str, str], Detail] = field(default_factory=OrderedDict)

    def __post_init__(self) -> None:
        self.apply_filter(self.filter_text)

    @property
    def current(self) -> SearchItem | None:
        return self.items[self.indices[self.selected]] if self.indices else None

    def apply_filter(self, text: str) -> None:
        old = self.current
        terms = text.casefold().split()
        self.filter_text = text
        self.indices = [
            index
            for index, item in enumerate(self.items)
            if all(
                term
                in f'{item.name}\n{item.author}\n{item.source}\n'
                f'{self.source_names.get(item.source, "")}'.casefold()
                for term in terms
            )
        ]
        self.selected = self.indices.index(old.index) if old and old.index in self.indices else 0
        self.list_scroll = 0
        self.show_report = False

    def move(self, delta: int) -> None:
        self.selected = min(max(0, self.selected + delta), max(0, len(self.indices) - 1))
        self.show_report = False

    def remember(self, item: SearchItem, detail: Detail) -> None:
        self.details[item.key] = detail
        self.details.move_to_end(item.key)
        while len(self.details) > DETAIL_CACHE_SIZE:
            self.details.popitem(last=False)

    def action(self) -> DownloadAction | None:
        item = self.current
        return DownloadAction(self.generation, item) if item and item.source and item.url else None
