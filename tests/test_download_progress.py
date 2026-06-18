from __future__ import annotations

from downloader.download.progress import (
    NoopDownloadProgress,
    RichDownloadProgress,
    ensure_download_progress,
)


class FakeRichProgress:
    def __init__(self) -> None:
        self.events = []

    def __enter__(self):
        self.events.append(('enter',))
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append(('exit', exc_type))
        return False

    def add_task(self, description, total=None):
        self.events.append(('add_task', description, total))
        return len(self.events)

    def advance(self, task_id, advance=1):
        self.events.append(('advance', task_id, advance))

    def update(self, task_id, **kwargs):
        self.events.append(('update', task_id, kwargs))

    def remove_task(self, task_id):
        self.events.append(('remove_task', task_id))


def test_noop_download_progress_accepts_all_operations():
    progress = NoopDownloadProgress()

    with progress as active:
        task_id = active.add_task('download', total=3)
        active.advance(task_id)
        active.update(task_id, description='done')
        active.remove_task(task_id)

    assert active is progress
    assert task_id is None


def test_ensure_download_progress_returns_noop_for_none():
    progress = ensure_download_progress(None)

    assert isinstance(progress, NoopDownloadProgress)


def test_ensure_download_progress_returns_existing_adapter():
    progress = NoopDownloadProgress()

    assert ensure_download_progress(progress) is progress


def test_rich_download_progress_delegates_to_rich_progress():
    rich = FakeRichProgress()
    progress = RichDownloadProgress(rich)

    with progress as active:
        task_id = active.add_task('download', total=2)
        active.advance(task_id)
        active.update(task_id, description='done')
        active.remove_task(task_id)

    assert rich.events == [
        ('enter',),
        ('add_task', 'download', 2),
        ('advance', 2, 1),
        ('update', 2, {'description': 'done'}),
        ('remove_task', 2),
        ('exit', None),
    ]


def test_ensure_download_progress_wraps_rich_like_progress():
    rich = FakeRichProgress()

    progress = ensure_download_progress(rich)

    assert isinstance(progress, RichDownloadProgress)
