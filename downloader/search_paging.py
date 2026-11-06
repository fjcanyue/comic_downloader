"""Session-only cursors and append-only results for explicit search-page loading."""

from __future__ import annotations

from dataclasses import dataclass, field

from downloader.models import Comic, SearchOutcome

SEARCH_PAGE_INTERVAL = 2.0


@dataclass
class SearchPageState:
    next_url: str | None
    pages: int = 1
    visited: set[str] = field(default_factory=set)
    last_attempt: float = float('-inf')

    def accept(self, url: str, outcome: SearchOutcome) -> None:
        # A failed/partial page is retried at the same cursor; valid rows can still be retained.
        if not outcome.ok:
            return
        self.visited.add(url)
        self.pages += 1
        self.next_url = outcome.next_page_url
        if self.next_url in self.visited:
            self.next_url = None
            outcome.error_message = '来源返回已加载过的搜索页，已停止继续翻页。'


def append_unique_results(existing: list[Comic], incoming: list[Comic]) -> int:
    """Never replace, remove or reorder existing identities, including selected downloads."""
    seen = {(comic.source, comic.url) for comic in existing}
    before = len(existing)
    for comic in incoming:
        key = comic.source, comic.url
        if comic.url and key not in seen:
            existing.append(comic)
            seen.add(key)
    return len(existing) - before
