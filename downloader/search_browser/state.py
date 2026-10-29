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
class CatalogTarget:
    group: int
    chapter: int | None
    book_name: str
    chapters: tuple[tuple[str, str], ...]
    end_chapter: int | None = None

    @classmethod
    def from_comic(
        cls, comic: Comic, group: int, chapter: int | None, end_chapter: int | None = None
    ) -> CatalogTarget:
        book = comic.books[group - 1]
        if end_chapter is not None:
            if chapter is None or not 1 <= chapter <= end_chapter <= len(book.vols):
                raise ValueError('章节范围无效')
            if end_chapter == chapter:
                end_chapter = None
        volumes = book.vols if chapter is None else book.vols[chapter - 1 : end_chapter or chapter]
        return cls(
            group,
            chapter,
            book.name or '默认章节',
            tuple((v.name, v.url) for v in volumes),
            end_chapter,
        )

    @property
    def arguments(self) -> str:
        return (
            str(self.group)
            if self.chapter is None
            else f'{self.group} {self.chapter} {self.end_chapter or self.chapter}'
        )

    @property
    def description(self) -> str:
        group = f'第 {self.group} 卷「{plain(self.book_name)}」'
        if self.chapter is None:
            return f'{group}全部 {len(self.chapters)} 话'
        if self.end_chapter is not None:
            return (
                f'{group}第 {self.chapter}–{self.end_chapter} 话（共 {len(self.chapters)} 话）'
                f'；从「{plain(self.chapters[0][0])}」到「{plain(self.chapters[-1][0])}」'
            )
        return f'{group}第 {self.chapter} 话「{plain(self.chapters[0][0])}」（仅此一话）'

    def matches(self, comic: Comic) -> bool:
        if not 1 <= self.group <= len(comic.books) or not self.chapters:
            return False
        if self.chapter is not None and not 1 <= self.chapter <= len(
            comic.books[self.group - 1].vols
        ):
            return False
        if self.end_chapter is not None and (
            self.chapter is None
            or not self.chapter <= self.end_chapter <= len(comic.books[self.group - 1].vols)
        ):
            return False
        return self == self.from_comic(comic, self.group, self.chapter, self.end_chapter)


@dataclass(frozen=True)
class DownloadAction:
    generation: int
    item: SearchItem
    target: CatalogTarget | None = None

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
    targets: dict[int, tuple[int, int | None]] = field(default_factory=dict)
    range_start: tuple[int, int] | None = None

    @classmethod
    def from_comic(cls, item: SearchItem, comic: Comic) -> Detail:
        targets: dict[int, tuple[int, int | None]] = {}
        return cls(detail_lines(item, comic, targets=targets), comic, targets=targets)


def detail_lines(
    item: SearchItem, comic: Comic, *, targets: dict[int, tuple[int, int | None]] | None = None
) -> list[str]:
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
        if targets is not None:
            targets[len(lines) + 1] = (group, None)
        lines.extend(['', f'[{group}] {plain(book.name) or "默认章节"} · {len(book.vols)} 话'])
        for number, volume in enumerate(book.vols, 1):
            if targets is not None:
                targets[len(lines)] = (group, number)
            lines.append(f'  {number}  {plain(volume.name)}')
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
