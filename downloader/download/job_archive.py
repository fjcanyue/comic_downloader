"""Command syntax for reversible, explicit download-plan archiving."""

from __future__ import annotations

import re
from dataclasses import dataclass

ARCHIVE_USAGE = (
    'archive [list [页码]]；archive <任务ID> 归档已完成计划；'
    'archive show <任务ID> [页码] 查看归档；archive restore <任务ID> 恢复。'
)


@dataclass(frozen=True)
class ArchiveQuery:
    action: str = 'list'
    job_id: str | None = None
    page: int = 1


def parse_archive_query(args: list[str]) -> ArchiveQuery:
    tokens = [arg.casefold() for arg in args]
    if not tokens:
        return ArchiveQuery()
    action = tokens.pop(0)
    if action not in {'list', 'show', 'restore'}:
        tokens.insert(0, action)
        action = 'archive'
    job_id = None
    if action != 'list':
        if not tokens or not re.fullmatch(r'[0-9a-f]{4,32}', tokens[0]):
            raise ValueError(ARCHIVE_USAGE)
        job_id = tokens.pop(0)
    if action in {'archive', 'restore'} and tokens:
        raise ValueError(ARCHIVE_USAGE)
    if len(tokens) > 1 or (tokens and (not tokens[0].isdecimal() or int(tokens[0]) < 1)):
        raise ValueError('页码必须是正整数。' + ARCHIVE_USAGE)
    return ArchiveQuery(action, job_id, int(tokens[0]) if tokens else 1)
