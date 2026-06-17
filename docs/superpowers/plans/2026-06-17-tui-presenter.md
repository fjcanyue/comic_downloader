# TUI Presenter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a focused TUI presenter module and route shell display behaviour through it.

**Architecture:** `downloader.tui.TerminalPresenter` owns Rich rendering and prompt text. `Shell` keeps command and runtime orchestration, while delegating result rendering and user-facing shell output to the presenter.

**Tech Stack:** Python 3.10, Rich, pytest, existing `cmd.Cmd` shell.

---

## File Structure

- Create `downloader/tui.py`: terminal presenter module with Rich table, markdown, status, summary, prompt, and simple message helpers.
- Modify `downloader/shell.py`: construct `TerminalPresenter`, delegate rendering, and update prompt on source switch.
- Add `tests/test_tui_presenter.py`: focused tests for presenter output and prompt formatting.
- Modify `tests/test_shell_driver_lifecycle.py`: add a shell prompt update regression test.

## Task 1: Presenter Rendering

**Files:**
- Create: `downloader/tui.py`
- Test: `tests/test_tui_presenter.py`

- [ ] **Step 1: Write failing presenter tests**

```python
from __future__ import annotations

from io import StringIO

from rich.console import Console

from downloader.models import Comic, ComicBook, ComicVolume, DownloadSummary, VolumeDownloadResult
from downloader.tui import TerminalPresenter


def presenter_with_output() -> tuple[TerminalPresenter, StringIO]:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=120)
    return TerminalPresenter(console), output


def test_search_results_render_table_with_source_author_name_and_url():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.source = 'morui'
    comic.author = '作者'
    comic.name = '漫画名'
    comic.url = 'https://example.test/comic'

    presenter.search_results(
        '猎人',
        [comic],
        {'morui': '摩锐漫画'},
        1.25,
    )

    rendered = output.getvalue()
    assert '搜索结果 (1 条，用时 1.2s)' in rendered
    assert '摩锐漫画' in rendered
    assert '作者' in rendered
    assert '漫画名' in rendered
    assert 'https://example.test/comic' in rendered


def test_search_results_render_empty_message():
    presenter, output = presenter_with_output()

    presenter.search_results('不存在', [], {}, 0.1)

    assert '未找到与 "不存在" 相关的结果。' in output.getvalue()


def test_comic_info_renders_metadata_and_chapter_table():
    presenter, output = presenter_with_output()
    comic = Comic()
    comic.name = '漫画名'
    comic.metadata = [{'k': '作者', 'v': '作者名'}]
    book = ComicBook()
    book.name = '正篇'
    book.vols = [
        ComicVolume('第1话', 'https://example.test/1'),
        ComicVolume('第2话', 'https://example.test/2'),
    ]
    comic.books = [book]

    presenter.comic_info(comic)

    rendered = output.getvalue()
    assert '漫画名' in rendered
    assert '作者名' in rendered
    assert '1' in rendered
    assert '第1话' in rendered
    assert '2' in rendered
    assert '第2话' in rendered


def test_download_summary_renders_success_counts():
    presenter, output = presenter_with_output()
    summary = DownloadSummary()
    summary.add(VolumeDownloadResult(name='第1话', url='https://example.test/1', status='downloaded'))
    summary.add(VolumeDownloadResult(name='第2话', url='https://example.test/2', status='skipped'))

    presenter.download_summary(summary)

    assert '下载完成：成功 1，跳过 1' in output.getvalue()


def test_prompt_includes_current_source_when_selected():
    presenter, _ = presenter_with_output()

    assert presenter.prompt(None) == '动漫下载器> '
    assert presenter.prompt('morui') == '动漫下载器[morui]> '
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk uv run pytest tests/test_tui_presenter.py -q`

Expected: FAIL because `downloader.tui` does not exist.

- [ ] **Step 3: Implement `TerminalPresenter`**

Create `downloader/tui.py` with:

```python
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from downloader.comic import Comic


class TerminalPresenter:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def print(self, message: Any = '', style: str | None = None) -> None:
        self.console.print(message, style=style)

    def status(self, message: str, spinner: str = 'dots'):
        return self.console.status(message, spinner=spinner)

    def prompt(self, source_name: str | None = None) -> str:
        if source_name:
            return f'动漫下载器[{source_name}]> '
        return '动漫下载器> '

    def output_path(self, path: str) -> None:
        self.print(f'动漫文件本机存储路径为: {path}')

    def source_options(self, source_names: list[str]) -> None:
        self.print('请选择动漫下载网站源:')
        for index, source_name in enumerate(source_names):
            self.print(f'{index + 1}. {source_name}')

    def source_switching(self, source_name: str) -> None:
        self.print(f'正在切换到{source_name}动漫下载网站源...')

    def search_results(
        self,
        keyword: str,
        comics: list[Comic],
        source_display_names: dict[str | None, str],
        duration: float,
    ) -> None:
        if not comics:
            self.print(f'未找到与 "{keyword}" 相关的结果。', style='bold yellow')
            return

        table = Table(title=f'搜索结果 ({len(comics)} 条，用时 {duration:.1f}s)')
        table.add_column('序号', justify='right', no_wrap=True)
        table.add_column('动漫源')
        table.add_column('作者')
        table.add_column('名称')
        table.add_column('URL', style='#75D7EC')

        for index, comic in enumerate(comics):
            table.add_row(
                str(index + 1),
                source_display_names.get(comic.source, comic.source or 'N/A'),
                comic.author if comic.author else 'N/A',
                comic.name if comic.name else 'N/A',
                comic.url if comic.url else 'N/A',
            )

        self.print(table)

    def comic_info(self, comic: Comic) -> None:
        md_content = f'# {comic.name}\\n\\n'
        if comic.metadata:
            md_content += '## Metadata\\n'
            for meta in comic.metadata:
                md_content += f'- **{meta[\"k\"]}**: {meta[\"v\"]}\\n'
        self.print(Markdown(md_content))

        for book_index, book in enumerate(comic.books):
            self.print(self.chapter_table(book_index, book))

    def chapter_table(self, book_index: int, book) -> Table:
        table = Table(
            title=f'{book_index + 1}: {book.name}', show_header=False, box=None, padding=(0, 2)
        )
        columns = 3
        for _ in range(columns):
            table.add_column('Index', justify='right', style='cyan')
            table.add_column('Name', style='white')

        row_buffer = []
        for index, vol in enumerate(book.vols):
            row_buffer.extend([str(index + 1), vol.name])
            if len(row_buffer) == columns * 2:
                table.add_row(*row_buffer)
                row_buffer = []

        if row_buffer:
            while len(row_buffer) < columns * 2:
                row_buffer.extend(['', ''])
            table.add_row(*row_buffer)
        return table

    def download_summary(self, summary) -> None:
        if summary.ok:
            self.print(
                f'下载完成：成功 {summary.downloaded}，跳过 {summary.skipped}',
                style='bold green',
            )
            return
        self.print(
            f'下载完成，但存在失败：成功 {summary.downloaded}，跳过 {summary.skipped}，'
            f'失败 {summary.failed}，部分失败 {summary.partial}',
            style='bold yellow',
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run pytest tests/test_tui_presenter.py -q`

Expected: PASS.

## Task 2: Shell Delegation

**Files:**
- Modify: `downloader/shell.py`
- Modify: `tests/test_shell_driver_lifecycle.py`

- [ ] **Step 1: Write failing shell delegation test**

Add this test to `tests/test_shell_driver_lifecycle.py`:

```python
def test_shell_prompt_updates_when_source_switches(tmp_path):
    shell = Shell(str(tmp_path))
    try:
        cast(Any, shell)._Shell__switch_source('morui')

        assert shell.prompt == '动漫下载器[morui]> '
    finally:
        shell.context.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_shell_driver_lifecycle.py::test_shell_prompt_updates_when_source_switches -q`

Expected: FAIL because `Shell.__switch_source()` leaves prompt unchanged.

- [ ] **Step 3: Update shell to use presenter**

Modify `downloader/shell.py`:

- import `TerminalPresenter`;
- remove direct `Markdown` and `Table` imports;
- create `self.presenter = TerminalPresenter()`;
- set `self.console = self.presenter.console`;
- pass presenter into `Context`;
- call `self.presenter` for output path, source list, search table, comic info, chapter table, download summary, and status contexts;
- update `self.prompt = self.presenter.prompt(self.current_source_name)` after source switch;
- keep `_print_search_table`, `_print_comic_info`, `_print_chapter_tables`, `_build_chapter_table`, and `__print_download_summary` as delegating methods so older tests and call sites keep working.

- [ ] **Step 4: Run focused shell tests**

Run: `rtk uv run pytest tests/test_shell_driver_lifecycle.py tests/test_main_cli.py -q`

Expected: PASS.

## Task 3: Verification

**Files:**
- Existing project files only.

- [ ] **Step 1: Run TUI and shell focused tests**

Run: `rtk uv run pytest tests/test_tui_presenter.py tests/test_shell_driver_lifecycle.py tests/test_main_cli.py -q`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `rtk uv run pytest -q`

Expected: PASS.

- [ ] **Step 3: Run lint**

Run: `rtk uv run ruff check downloader tests main.py`

Expected: PASS.

## Self-Review

Spec coverage: The plan creates the TUI presenter, delegates shell rendering, updates prompt state, and leaves non-goal systems unchanged.

Placeholder scan: No placeholder steps remain.

Type consistency: `TerminalPresenter`, `search_results`, `comic_info`, `chapter_table`, `download_summary`, and `prompt` names are consistent across tests and implementation steps.
