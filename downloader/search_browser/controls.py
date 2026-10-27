from __future__ import annotations

from collections.abc import Callable

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.layout.controls import UIContent, UIControl
from rich.cells import chop_cells

from downloader.search_browser.state import BrowserState, plain


class ResultsControl(UIControl):
    def __init__(self, state: BrowserState) -> None:
        self.state = state

    def is_focusable(self) -> bool:
        return True

    def create_content(self, width: int, height: int) -> UIContent:
        def line(index: int) -> StyleAndTextTuples:
            if not self.state.indices:
                return [('', '无匹配结果；按 / 修改或清空筛选。')]
            item = self.state.items[self.state.indices[index]]
            selected = index == self.state.selected
            return [
                (
                    'class:selected' if selected else '',
                    f'{">" if selected else " "} {item.index + 1:>3}  '
                    f'[{plain(item.source)}] {plain(item.name)}',
                )
            ]

        return UIContent(
            get_line=line,
            line_count=max(1, len(self.state.indices)),
            cursor_position=Point(0, self.state.selected),
            show_cursor=False,
        )


class LinesControl(UIControl):
    """Read only text: compute lines once on data change, render only visible rows."""

    def __init__(self, lines: Callable[[], list[str]], row: Callable[[], int], *, focusable=True):
        self.lines = lines
        self.row = row
        self.focusable = focusable
        self.source_lines: list[str] | None = None
        self.width = 80
        self.wrapped_lines: list[str] = []

    def is_focusable(self) -> bool:
        return self.focusable

    def wrapped(self, width: int | None = None) -> list[str]:
        source = self.lines()
        width = max(2, width if width is not None else self.width)
        if source is not self.source_lines or width != self.width:
            self.source_lines = source
            self.width = width
            self.wrapped_lines = [
                part for line in source for part in (chop_cells(plain(line), width) or [''])
            ] or ['']
        return self.wrapped_lines

    def create_content(self, width: int, height: int) -> UIContent:
        lines = self.wrapped(width)
        row = min(max(0, self.row()), len(lines) - 1)
        return UIContent(
            get_line=lambda index: [('', lines[index])],
            line_count=len(lines),
            cursor_position=Point(0, row),
            show_cursor=False,
        )
