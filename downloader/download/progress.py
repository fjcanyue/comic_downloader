from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


@runtime_checkable
class DownloadProgress(Protocol):
    def __enter__(self):
        ...

    def __exit__(self, exc_type, exc, tb):
        ...

    def add_task(self, description: str, total: float | None = None):
        ...

    def advance(self, task_id, amount: float = 1) -> None:
        ...

    def update(
        self,
        task_id,
        *,
        description: str | None = None,
        total: float | None = None,
    ) -> None:
        ...

    def remove_task(self, task_id) -> None:
        ...


class NoopDownloadProgress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_task(self, description: str, total: float | None = None):
        return None

    def advance(self, task_id, amount: float = 1) -> None:
        return None

    def update(
        self,
        task_id,
        *,
        description: str | None = None,
        total: float | None = None,
    ) -> None:
        return None

    def remove_task(self, task_id) -> None:
        return None


class RichDownloadProgress:
    def __init__(self, progress: Any | None = None) -> None:
        self.progress = progress or Progress(
            SpinnerColumn(style='cyan'),
            TextColumn('[progress.description]{task.description}'),
            BarColumn(bar_width=None, complete_style='green', finished_style='green'),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            expand=True,
        )

    def __enter__(self):
        self.progress.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.progress.__exit__(exc_type, exc, tb)

    def add_task(self, description: str, total: float | None = None):
        return self.progress.add_task(description=description, total=total)

    def advance(self, task_id, amount: float = 1) -> None:
        self.progress.advance(task_id, advance=amount)

    def update(
        self,
        task_id,
        *,
        description: str | None = None,
        total: float | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if description is not None:
            kwargs['description'] = description
        if total is not None:
            kwargs['total'] = total
        self.progress.update(task_id, **kwargs)

    def remove_task(self, task_id) -> None:
        self.progress.remove_task(task_id)


def ensure_download_progress(progress: Any | None) -> DownloadProgress:
    if progress is None:
        return NoopDownloadProgress()
    if isinstance(progress, NoopDownloadProgress | RichDownloadProgress):
        return progress
    return RichDownloadProgress(progress)
