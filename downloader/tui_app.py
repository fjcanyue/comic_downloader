from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Input, DataTable, Static, Button, Label, Markdown
from textual.screen import Screen, ModalScreen
from textual.worker import Worker
from textual import on, work
from unittest.mock import patch
import tqdm

from downloader.manager import ComicManager

# Create a no-op tqdm to silence output
class NoOpTqdm:
    def __init__(self, iterable=None, *args, **kwargs):
        self.iterable = iterable or []
    def __iter__(self):
        return iter(self.iterable)
    def update(self, n=1):
        pass
    def close(self):
        pass
    def set_description(self, desc):
        pass

class SearchScreen(Screen):
    BINDINGS = [("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Search Comics:", classes="label"),
            Input(placeholder="Enter keywords...", id="search_input"),
            Button("Search", variant="primary", id="search_btn"),
            classes="search_container"
        )
        yield DataTable(id="results_table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Index", "Source", "Name", "Author", "URL")
        table.cursor_type = "row"

    @on(Button.Pressed, "#search_btn")
    def on_search(self):
        query = self.query_one(Input).value
        if query:
            self.app.search_comics(query)

    @on(Input.Submitted, "#search_input")
    def on_search_submit(self):
        query = self.query_one(Input).value
        if query:
            self.app.search_comics(query)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected):
        row_key = event.row_key
        # We stored the comic index or object in the row key or separate mapping
        # Let's assume row_key is the index
        index = int(row_key.value)
        self.app.show_details(index)

class DetailsScreen(Screen):
    BINDINGS = [("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Markdown(id="comic_info"),
            Button("Download Full Comic", variant="success", id="download_btn"),
            classes="details_container"
        )
        yield Footer()

    def on_mount(self):
        self.update_info()

    def update_info(self):
        comic = self.app.selected_comic
        if comic:
            md = f"# {comic.name}\n"
            md += f"**Author:** {comic.author}\n"
            md += f"**Source:** {comic.source}\n"
            md += f"**URL:** {comic.url}\n\n"
            if comic.metadata:
                for meta in comic.metadata:
                    md += f"- **{meta.get('k')}:** {meta.get('v')}\n"

            md += "\n## Books/Chapters\n"
            if comic.books:
                 for book in comic.books:
                     md += f"### {book.name}\n"
                     md += f"Contains {len(book.vols)} volumes.\n"

            self.query_one(Markdown).update(md)

    def action_back(self):
        self.app.pop_screen()

    @on(Button.Pressed, "#download_btn")
    def on_download(self):
        self.app.download_comic()

class ComicApp(App):
    CSS = """
    .search_container {
        height: auto;
        padding: 1;
        align: center middle;
    }
    #results_table {
        height: 1fr;
    }
    .details_container {
        padding: 2;
    }
    .label {
        margin-bottom: 1;
    }
    """

    def __init__(self, output_path: str):
        super().__init__()
        self.manager = ComicManager(output_path)
        self.selected_comic = None

    def on_mount(self):
        self.push_screen(SearchScreen())

    @work(thread=True)
    def search_comics(self, query: str):
        # This runs in a worker thread
        results = self.manager.search(query)

        # Update UI in main thread
        self.call_from_thread(self.update_results, results)

    def update_results(self, results):
        table = self.query_one(DataTable)
        table.clear()
        for idx, comic in enumerate(results):
            table.add_row(str(idx), comic.source or "Unknown", comic.name, comic.author, comic.url, key=str(idx))
        self.notify(f"Found {len(results)} results.")

    def show_details(self, index: int):
        if 0 <= index < len(self.manager.searched_results):
            # We have the basic info, but we might need to fetch detailed info (like chapters)
            # if they were not loaded in search result.
            # In `Shell.do_s`, it gets basic info. `Shell.do_i` calls `source.info(url)` to get full info.
            # So we must fetch details.

            basic_comic = self.manager.searched_results[index]
            self.notify("Fetching details...")
            self.fetch_details(basic_comic.url)

    @work(thread=True)
    def fetch_details(self, url: str):
        comic = self.manager.get_comic_info(url)
        if comic:
            self.selected_comic = comic
            self.call_from_thread(self.push_details_screen)
        else:
            self.call_from_thread(self.notify, "Failed to fetch details.", severity="error")

    def push_details_screen(self):
        self.push_screen(DetailsScreen())

    @work(thread=True)
    def download_comic(self):
        if self.selected_comic:
            self.call_from_thread(self.notify, f"Starting download of {self.selected_comic.name}...")
            try:
                # Patch tqdm to prevent output corruption
                with patch('downloader.comic.tqdm', NoOpTqdm):
                     self.manager.download_full(self.selected_comic.url)
                self.call_from_thread(self.notify, "Download complete!", severity="information")
            except Exception as e:
                self.call_from_thread(self.notify, f"Download failed: {e}", severity="error")

    def on_unmount(self):
        self.manager.close()
