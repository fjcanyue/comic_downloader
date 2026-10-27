from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from downloader.models import Comic, ComicBook, ComicVolume
from downloader.search_browser.loader import PreviewWorker
from downloader.search_browser.state import (
    BrowserState,
    Detail,
    DownloadAction,
    SearchItem,
    detail_lines,
)
from downloader.search_browser.view import SearchBrowser


def items(count=8):
    return tuple(
        SearchItem(i, 'fixture', f'https://example.test/{i}', f'[red]漫画{i}', '作者')
        for i in range(count)
    )


def comic_detail(name='已加载漫画'):
    comic = Comic()
    comic.name = name
    book = ComicBook()
    book.name = '正篇'
    book.vols = [ComicVolume(f'第{i}话', f'https://example.test/v/{i}') for i in range(100)]
    comic.books = [book]
    return comic


class ScreenOutput(DummyOutput):
    def __init__(self, columns=120, rows=30):
        self.size = Size(rows=rows, columns=columns)

    def get_size(self):
        return self.size


async def until(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError('browser interaction timed out')


async def exercise(scenario, *, state=None, load=None, output=None):
    state = state or BrowserState(items(), '漫画', 1)
    worker = PreviewWorker(load or (lambda item, stop: comic_detail(item.name)))
    with create_pipe_input() as pipe:
        browser = SearchBrowser(
            state, worker, 'D:/Comics', False, input=pipe, output=output or ScreenOutput()
        )
        browser.app.ttimeoutlen = 0.02
        run = asyncio.create_task(browser.app.run_async(pre_run=browser.start))
        try:
            await until(lambda: browser.app.is_running)
            return await scenario(browser, pipe, run)
        finally:
            browser._finish()
            if not run.done():
                await asyncio.wait_for(run, 3)
            browser.close()
            assert not worker.alive


def test_filter_preserves_original_number_and_download_identity():
    state = BrowserState(items(30), '漫画', 3)
    state.apply_filter('漫画12 FIXTURE')
    assert len(state.indices) == 1
    assert state.current is not None
    assert state.current.index == 12
    action = state.action()
    assert action is not None
    assert action == DownloadAction(3, items(30)[12])
    comics = []
    for item in items(30):
        comic = Comic()
        comic.source, comic.url = item.key
        comics.append(comic)
    assert action.matches(3, comics)
    assert not action.matches(4, comics)
    comics[12].url = 'https://example.test/changed'
    assert not action.matches(3, comics)
    state.apply_filter('不存在')
    assert state.current is None and state.action() is None
    state.apply_filter('')
    assert len(state.indices) == 30


def test_detail_cache_is_bounded_and_keeps_full_catalog_warnings_literal():
    state = BrowserState(items(30), '漫画', 1)
    comic = comic_detail()
    comic.parse_warnings = ['[red]部分目录缺失[/]']
    lines = detail_lines(state.items[0], comic)
    assert any('部分目录缺失' in line for line in lines)
    assert any('第99话' in line for line in lines)
    for item in state.items:
        state.remember(item, Detail(lines, comic))
    assert len(state.details) == 20
    assert state.items[0].key not in state.details


def test_enter_preview_and_default_cancel_never_download_or_change_selection():
    calls = []

    def load(item, stop):
        calls.append(item.index)
        return comic_detail()

    async def scenario(browser, pipe, run):
        pipe.send_text('\x1b[B\r')
        await until(
            lambda: browser.state.details.get(items()[1].key) is not None
            and browser.state.details[items()[1].key].comic is not None
        )
        assert calls == [1]
        pipe.send_text('dd')
        await until(lambda: browser.confirmation is not None)
        assert browser.confirmation.item.index == 1
        pipe.send_text('\x1b[B/dq')
        await asyncio.sleep(0.1)
        assert browser.state.current.index == 1
        assert browser.confirmation.item.index == 1
        assert not browser.editing
        assert browser.app.layout.has_focus(browser.cancel_button)
        pipe.send_text('\r')
        await until(lambda: browser.confirmation is None)
        assert not run.done()
        pipe.send_text('q')
        assert await asyncio.wait_for(run, 3) is None
        assert calls == [1]

    asyncio.run(exercise(scenario, load=load))


def test_confirm_download_without_preview_returns_exact_frozen_original_item_once():
    state = BrowserState(items(40), '漫画', 7, filter_text='漫画23')

    def no_preview(item, stop):
        pytest.fail('opening or confirming download must not request preview')

    async def scenario(browser, pipe, run):
        pipe.send_text('d')
        await until(lambda: browser.confirmation is not None)
        assert browser.confirmation.item.index == 23
        assert any('确认后获取目录' in line for line in browser.confirm_lines)
        assert any('D:/Comics' in line for line in browser.confirm_lines)
        pipe.send_text('\t')
        await until(lambda: browser.app.layout.has_focus(browser.download_button))
        pipe.send_text('\r\rdd')
        action = await asyncio.wait_for(run, 3)
        assert action == DownloadAction(7, state.items[23])
        assert browser.worker.thread is None

    asyncio.run(exercise(scenario, state=state, load=no_preview))


def test_filter_text_d_and_q_do_not_trigger_actions_and_escape_restores_focus():
    async def scenario(browser, pipe, run):
        pipe.send_text('/dq')
        await until(lambda: browser.filter_input.text == 'dq')
        assert browser.confirmation is None
        assert browser.worker.thread is None
        pipe.send_text('\x1b')
        await until(lambda: not browser.editing)
        assert len(browser.state.indices) == 8
        pipe.send_text('/漫画5\r')
        await until(lambda: browser.state.filter_text == '漫画5')
        assert browser.state.current.index == 5
        pipe.send_text('d')
        await until(lambda: browser.confirmation is not None)
        pipe.send_text('\x1b')
        await until(lambda: browser.confirmation is None)
        assert browser.state.current.index == 5
        pipe.send_text('q')
        assert await asyncio.wait_for(run, 3) is None

    asyncio.run(exercise(scenario))


def test_loading_does_not_block_selection_and_old_result_cannot_replace_new_details():
    started = threading.Event()
    release = threading.Event()

    def load(item, stop):
        if item.index == 0:
            started.set()
            assert release.wait(3)
        return comic_detail(f'详情{item.index}')

    async def scenario(browser, pipe, run):
        try:
            pipe.send_text('\r')
            await until(started.is_set)
            pipe.send_text('\x1b[B\r\x1b[B\r')
            await until(lambda: browser.state.current.index == 2)
            assert browser.worker.pending[1].index == 2
            pipe.send_text('d')
            await until(lambda: browser.confirmation is not None)
            frozen = browser.confirmation
            release.set()
            await until(lambda: browser.state.details[items()[2].key].comic is not None)
            assert browser._detail_lines()[0] == '详情2'
            assert browser.confirmation == frozen
            assert items()[1].key not in browser.state.details
            pipe.send_text('\x1b')
            await until(lambda: browser.confirmation is None)
            pipe.send_text('q')
            await asyncio.wait_for(run, 3)
        finally:
            release.set()

    asyncio.run(exercise(scenario, load=load))


@pytest.mark.parametrize('size', [(120, 30), (80, 24), (40, 24), (120, 12)])
def test_responsive_layout_highlight_scroll_and_resize_preserve_selection(size):
    output = ScreenOutput(*size)
    state = BrowserState(items(2000), '漫画', 1)

    async def scenario(browser, pipe, run):
        pipe.send_text('\x1b[F')  # End
        await until(lambda: state.selected == 1999)
        await until(lambda: browser.results.vertical_scroll > 0)
        screen = browser.app.renderer.last_rendered_screen
        assert any(
            'class:selected' in cell.style
            for row in screen.data_buffer.values()
            for cell in row.values()
        )
        assert browser.results.vertical_scroll > 0
        if size[0] >= 48 and size[1] >= 18:
            positions = screen.visible_windows_to_write_positions
            left, right = positions[browser.results], positions[browser.detail]
            if size[0] >= 110 and size[1] >= 20:
                assert right.xpos > left.xpos
            else:
                assert right.ypos > left.ypos
        pipe.send_text('\r')
        await until(
            lambda: state.current is not None
            and state.current.key in state.details
            and state.details[state.current.key].comic is not None
        )
        pipe.send_text('\t\x1b[F')
        await until(lambda: state.focus == 'details' and browser._detail_row() > 90)
        output.size = Size(rows=30, columns=120)
        browser.app.invalidate()
        await asyncio.sleep(0.1)
        assert state.current is not None and state.current.index == 1999
        pipe.send_text('q')
        await asyncio.wait_for(run, 3)

    asyncio.run(exercise(scenario, state=state, output=output))


def test_close_waits_visibly_for_active_request_and_discards_pending_request():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def load(item, stop):
        calls.append(item.index)
        started.set()
        assert release.wait(3)
        return comic_detail()

    async def scenario(browser, pipe, run):
        try:
            pipe.send_text('\r')
            await until(started.is_set)
            pipe.send_text('\x1b[B\rq')
            await until(lambda: browser.closing)
            assert not run.done()
            assert '等待当前详情请求结束' in browser._footer()
            assert browser.worker.pending is None
            release.set()
            assert await asyncio.wait_for(run, 3) is None
            assert calls == [0]
        finally:
            release.set()

    asyncio.run(exercise(scenario, load=load))


def test_error_retry_caches_success_and_keeps_literal_markup():
    calls = []

    def load(item, stop):
        calls.append(item)
        if len(calls) == 1:
            raise ValueError('[red]模拟网络失败[/]')
        return comic_detail('[red]成功[/]')

    async def scenario(browser, pipe, run):
        pipe.send_text('\r')
        await until(
            lambda: items()[0].key in browser.state.details
            and bool(browser.state.details[items()[0].key].error)
        )
        assert '[red]模拟网络失败[/]' in browser._detail_lines()
        pipe.send_text('r')
        await until(lambda: browser.state.details[items()[0].key].comic is not None)
        assert browser._detail_lines()[0] == '[red]成功[/]'
        pipe.send_text('\r\r')
        await asyncio.sleep(0.1)
        assert len(calls) == 2
        pipe.send_text('q')
        await asyncio.wait_for(run, 3)

    asyncio.run(exercise(scenario, load=load))


def test_empty_results_and_missing_source_cannot_download():
    state = BrowserState((replace(items()[0], source=''),), '漫画', 1)

    async def scenario(browser, pipe, run):
        pipe.send_text('d')
        await until(lambda: bool(state.message))
        assert browser.confirmation is None
        state.apply_filter('不存在')
        pipe.send_text('d\r')
        await asyncio.sleep(0.1)
        assert browser.confirmation is None and browser.worker.thread is None
        pipe.send_text('q')
        await asyncio.wait_for(run, 3)

    asyncio.run(exercise(scenario, state=state))


def test_ctrl_c_restores_application_and_stops_preview_worker():
    async def scenario():
        with create_pipe_input() as pipe:
            worker = PreviewWorker(lambda item, stop: comic_detail())
            browser = SearchBrowser(
                BrowserState(items(), '漫画', 1),
                worker,
                '.',
                False,
                input=pipe,
                output=ScreenOutput(),
            )

            async def run():
                try:
                    await browser.app.run_async(pre_run=browser.start)
                except KeyboardInterrupt:
                    return 'interrupted'
                finally:
                    browser.close()

            task = asyncio.create_task(run())
            await until(lambda: browser.app.is_running)
            pipe.send_text('\r')
            await until(lambda: bool(browser.state.details))
            pipe.send_text('\x03')
            assert await asyncio.wait_for(task, 3) == 'interrupted'
            assert not browser.app.is_running
            assert not worker.alive

    asyncio.run(scenario())


@pytest.mark.parametrize('width', [48, 80, 120])
def test_confirmation_uses_full_width_and_all_controls_remain_visible(width):
    async def scenario(browser, pipe, run):
        pipe.send_text('d')
        await until(lambda: browser.confirmation is not None)

        def drawn():
            screen = browser.app.renderer.last_rendered_screen
            return (
                screen
                and browser.download_button.window in screen.visible_windows_to_write_positions
            )

        await until(drawn)
        screen = browser.app.renderer.last_rendered_screen
        body = browser.dialog.body.children[0]
        position = screen.visible_windows_to_write_positions[body]
        assert position.width >= min(width - 6, 74)
        assert browser.app.layout.has_focus(browser.cancel_button)
        assert 'Esc 取消' in browser._footer()
        pipe.send_text('\x1b')
        await until(lambda: browser.confirmation is None)
        pipe.send_text('q')
        await asyncio.wait_for(run, 3)

    asyncio.run(exercise(scenario, output=ScreenOutput(width, 24)))


def test_long_details_and_confirmation_can_scroll_through_wrapped_lines():
    state = BrowserState(items(), '漫画', 1)
    state.remember(state.items[0], Detail(['长简介' * 100 + '末尾标记']))

    async def scenario(browser, pipe, run):
        pipe.send_text('\t\x1b[F')
        await until(lambda: browser._detail_row() > 10)
        await until(lambda: browser.detail.vertical_scroll > 0)
        assert browser.detail_control.wrapped()[-1].endswith('末尾标记')
        browser.output_path = 'D:/' + '很长的目录/' * 100 + '保存位置'
        pipe.send_text('d')
        await until(lambda: browser.confirmation is not None)
        await asyncio.sleep(0.1)
        pipe.send_text('\x1b[6~' * 20)
        await until(lambda: browser.confirm_row > 20)
        await until(lambda: browser.dialog.body.children[0].vertical_scroll > 0)
        assert browser.app.layout.has_focus(browser.cancel_button)
        pipe.send_text('\r')
        await until(lambda: browser.confirmation is None)
        pipe.send_text('q')
        assert await asyncio.wait_for(run, 3) is None

    asyncio.run(exercise(scenario, state=state, output=ScreenOutput(48, 24)))
