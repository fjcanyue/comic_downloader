"""Command syntax for reversible, explicit download-plan archiving."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

ARCHIVE_USAGE = (
    'archive [list [页码]] [find <关键词>] 按漫画名、源代码或 ID 查找归档；'
    'archive <任务ID> 归档已完成计划；archive show <任务ID> [页码] 查看归档；'
    'archive restore <任务ID> 恢复；archive next / prev 保留条件翻页。'
)


@dataclass(frozen=True)
class ArchiveQuery:
    action: str = 'list'
    job_id: str | None = None
    page: int = 1
    keyword: str = ''


def parse_archive_query(args: list[str], current: ArchiveQuery | None = None) -> ArchiveQuery:
    tokens = [arg.casefold() for arg in args]
    keyword = ''
    if 'find' in tokens:
        marker = tokens.index('find')
        keyword = ' '.join(args[marker + 1 :]).strip()
        tokens = tokens[:marker]
        if not keyword or (tokens and tokens[0] != 'list'):
            raise ValueError('查找格式：archive [list [页码]] find <关键词>。')
    if not tokens:
        return ArchiveQuery(keyword=keyword)
    action = tokens.pop(0)
    if action in {'next', 'prev'}:
        if tokens or current is None or current.action not in {'list', 'show'}:
            raise ValueError('请先使用 archive 或 archive show <任务ID> 打开列表，再连续翻页。')
        page = current.page + (1 if action == 'next' else -1)
        if page < 1:
            raise ValueError('已是第一页。')
        return replace(current, page=page)
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
    return ArchiveQuery(action, job_id, int(tokens[0]) if tokens else 1, keyword)
