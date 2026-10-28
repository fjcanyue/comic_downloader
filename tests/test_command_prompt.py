from __future__ import annotations

import asyncio
import sys

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from downloader.command_prompt import CommandCompleter, create_command_prompt

COMMANDS = {
    'browse': '浏览搜索结果',
    's': '搜索漫画',
    'source': '选择来源',
    'sources': '查看来源',
    'status': '当前状态',
}


@pytest.mark.parametrize(
    'text,expected',
    [
        ('b', ['browse']),
        ('s', ['s', 'source', 'sources', 'status']),
        ('  b', ['browse']),
        ('unknown', []),
        ('s b', []),
        ('s ', []),
        ('i https://b.test', []),
        ('archive find b', []),
        ('s 漫画', []),
    ],
)
def test_completer_matches_only_command_prefix(text, expected):
    completions = list(
        CommandCompleter(COMMANDS).get_completions(
            Document(text), CompleteEvent(text_inserted=True)
        )
    )
    assert [c.text for c in completions] == expected
    if completions:
        assert completions[0].start_position == -len(text.lstrip())
        assert completions[0].display_meta_text == COMMANDS[expected[0]]


def test_empty_prompt_requires_tab_and_middle_of_word_does_not_duplicate_suffix():
    completer = CommandCompleter(COMMANDS)
    assert list(completer.get_completions(Document(''), CompleteEvent(text_inserted=True))) == []
    assert len(
        list(completer.get_completions(Document(''), CompleteEvent(completion_requested=True)))
    ) == len(COMMANDS)
    assert (
        list(
            completer.get_completions(
                Document('browse', cursor_position=1), CompleteEvent(completion_requested=True)
            )
        )
        == []
    )


async def until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError('command prompt timed out')


async def exercise(scenario):
    with create_pipe_input() as pipe:
        session = create_command_prompt(COMMANDS, input=pipe, output=DummyOutput())
        session.app.ttimeoutlen = 0.02
        task = asyncio.create_task(session.prompt_async('漫画> '))
        try:
            await until(lambda: session.app.is_running)
            await scenario(session, pipe, task)
        finally:
            if not task.done():
                session.app.exit(result='')
            await asyncio.wait_for(task, 3)


def test_typing_shows_candidates_without_changing_input_tab_completes_and_enter_submits():
    async def scenario(session, pipe, task):
        pipe.send_text('b')
        await until(lambda: session.default_buffer.complete_state is not None)
        assert session.default_buffer.text == 'b'
        assert [c.text for c in session.default_buffer.complete_state.completions] == ['browse']
        pipe.send_text('\t')
        await until(lambda: session.default_buffer.text == 'browse')
        assert not task.done()
        pipe.send_text('\r')
        assert await task == 'browse'

    asyncio.run(exercise(scenario))


def test_tab_cycles_all_prefix_matches_shift_tab_reverses_and_escape_restores_prefix():
    async def scenario(session, pipe, task):
        pipe.send_text('s')
        await until(lambda: session.default_buffer.complete_state is not None)
        for index, name in enumerate(['s', 'source', 'sources', 'status', 's']):
            pipe.send_text('\t')
            await until(
                lambda index=index: session.default_buffer.complete_state.complete_index
                == index % 4
            )
            assert session.default_buffer.text == name
        pipe.send_text('\x1b[Z')
        await until(lambda: session.default_buffer.text == 'status')
        pipe.send_text('\x1b')
        await until(lambda: session.default_buffer.complete_state is None)
        assert session.default_buffer.text == 's'
        pipe.send_text(' 星海\t\r')
        assert await task == 's 星海'

    asyncio.run(exercise(scenario))


@pytest.mark.parametrize(
    'keys,expected', [('b\t\r', 'browse'), ('s\t\t\t\r', 'sources'), ('s\x1b[Z\r', 'status')]
)
def test_fast_tab_then_enter_submits_completed_command(keys, expected):
    async def scenario(session, pipe, task):
        pipe.send_text(keys)
        assert await task == expected

    asyncio.run(exercise(scenario))


@pytest.mark.parametrize(
    'key',
    [
        '\x04',
        pytest.param(
            '\x1a', marks=pytest.mark.skipif(sys.platform != 'win32', reason='Windows EOF')
        ),
    ],
)
def test_empty_prompt_eof_keeps_shell_exit_semantics(key):
    async def scenario():
        with create_pipe_input() as pipe:
            session = create_command_prompt(COMMANDS, input=pipe, output=DummyOutput())
            task = asyncio.create_task(session.prompt_async('> '))
            await until(lambda: session.app.is_running)
            pipe.send_text(key)
            with pytest.raises(EOFError):
                await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
