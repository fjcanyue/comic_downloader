from __future__ import annotations

import asyncio
import re
import sys
from bisect import bisect_left, bisect_right
from queue import Empty

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.output import Output
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Frame, TextArea

from downloader.search_browser.controls import LinesControl, ResultsControl
from downloader.search_browser.loader import PreviewWorker
from downloader.search_browser.state import (
    BrowserState,
    CatalogTarget,
    Detail,
    DownloadAction,
    NextPageAction,
    plain,
)

WIDE_COLUMNS = 110
COMPACT_COLUMNS = 80
MIN_COLUMNS = 48
MIN_ROWS = 18
WIDE_ROWS = 20
TERMINAL_ERRORS: tuple[type[Exception], ...] = (EOFError, OSError)
if sys.platform == 'win32':
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError

    TERMINAL_ERRORS += (NoConsoleScreenBufferError,)


class SearchBrowser:
    def __init__(  # noqa: PLR0913 - explicit terminal I/O injection for headless verification
        self,
        state: BrowserState,
        worker: PreviewWorker,
        output_path: str,
        overwrite: bool,
        *,
        input: Input | None = None,
        output: Output | None = None,
    ) -> None:
        self.state = state
        self.worker = worker
        self.output_path = output_path
        self.overwrite = overwrite
        self.tokens: dict[tuple[str, str], int] = {}
        self.editing = False
        self.edit_mode = 'filter'
        self.confirmation: DownloadAction | None = None
        self.confirm_lines: list[str] = []
        self.confirm_row = 0
        self.confirm_return_focus = 'results'
        self.closing = False
        self.interrupted = False
        self.result: DownloadAction | NextPageAction | None = None
        self.placeholder_row = 0
        self.results = Window(
            ResultsControl(state),
            wrap_lines=False,
            right_margins=[ScrollbarMargin()],
            always_hide_cursor=True,
        )
        self.results.vertical_scroll = state.list_scroll
        self.detail_control = LinesControl(
            self._detail_lines,
            self._detail_row,
            highlight=lambda: self.state.focus == 'details' and not self.state.show_report,
            on_reflow=self._set_detail_row,
            row_style=self._range_row_style,
            visible_rows=self._detail_visible_rows,
            line_text=self._detail_line_text,
            anchor=self._detail_anchor,
        )
        self.detail = Window(
            self.detail_control,
            wrap_lines=False,
            right_margins=[ScrollbarMargin()],
            always_hide_cursor=True,
        )
        self.result_frame = Frame(
            self.results,
            title=self._results_title,
            width=Dimension(weight=2),
            height=Dimension(weight=1),
        )
        self.detail_frame = Frame(
            self.detail,
            title=self._detail_title,
            width=Dimension(weight=3),
            height=Dimension(weight=2),
        )
        self.side_by_side = VSplit([self.result_frame, self.detail_frame])
        self.stacked = HSplit([self.result_frame, self.detail_frame])
        self.filter_input = TextArea(
            height=1, prompt='筛选：', multiline=False, accept_handler=self._apply_filter
        )
        self.catalog_input = TextArea(
            height=1,
            prompt=lambda: '章节查找：' if self.edit_mode == 'find' else '跳转 卷 话：',
            multiline=False,
            accept_handler=self._apply_catalog_input,
        )
        self.cancel_button = Button('取消', handler=self._cancel_download)
        self.download_button = Button('确认下载', handler=self._accept_download)
        self.confirm_control = LinesControl(
            lambda: self.confirm_lines, lambda: self.confirm_row, focusable=False
        )
        self.dialog = Frame(
            title=lambda: (
                '下载所选卷 / 话？'
                if self.confirmation and self.confirmation.target
                else '下载整本漫画？'
            ),
            body=HSplit(
                [
                    Window(
                        self.confirm_control,
                        height=8,
                        wrap_lines=False,
                        right_margins=[ScrollbarMargin()],
                    ),
                    VSplit(
                        [
                            Window(),
                            self.cancel_button,
                            Window(width=2),
                            self.download_button,
                            Window(),
                        ],
                        height=1,
                    ),
                ],
                padding=1,
            ),
            style='class:dialog.body',
            width=lambda: max(20, min(76, self.app.output.get_size().columns - 4)),
            modal=True,
        )
        self.body = FloatContainer(
            content=HSplit(
                [
                    Window(FormattedTextControl(self._header), height=1, style='class:header'),
                    DynamicContainer(self._panels),
                    ConditionalContainer(
                        self.filter_input,
                        Condition(lambda: self.editing and self.edit_mode == 'filter'),
                    ),
                    ConditionalContainer(
                        self.catalog_input,
                        Condition(lambda: self.editing and self.edit_mode != 'filter'),
                    ),
                    Window(
                        FormattedTextControl(self._message),
                        height=Dimension(min=1, max=2),
                        dont_extend_height=True,
                        wrap_lines=True,
                    ),
                    Window(
                        FormattedTextControl(self._footer),
                        height=lambda: 3 if self._catalog_footer() else 2,
                        wrap_lines=True,
                        style='class:footer',
                    ),
                ]
            ),
            floats=[
                Float(
                    content=ConditionalContainer(
                        self.dialog, Condition(lambda: self.confirmation is not None)
                    )
                )
            ],
        )
        self.app: Application[DownloadAction | NextPageAction | None] = Application(
            layout=Layout(self.body, focused_element=self._focus_window()),
            key_bindings=self._bindings(),
            full_screen=True,
            mouse_support=False,
            input=input,
            output=output,
            style=Style.from_dict(
                {
                    'selected': 'bg:#008787 #ffffff bold',
                    'range': 'bg:#005f5f #ffffff',
                    'match': 'bg:#5f5f00 #ffffff',
                    'header': 'bg:#005f5f #ffffff',
                    'footer': 'bg:#303030 #ffffff',
                    'frame.label': '#00afaf bold',
                    'dialog': 'bg:#303030',
                    'dialog.body': 'bg:#303030 #ffffff',
                    'button.focused': 'bg:#008787 #ffffff bold',
                }
            ),
        )

    def _focus_window(self) -> Window:
        return self.results if self.state.focus == 'results' else self.detail

    def _panels(self):
        # Layout walks the container during Application construction, before self.app exists.
        if not hasattr(self, 'app'):
            return self.side_by_side
        size = self.app.output.get_size()
        if size.columns < MIN_COLUMNS or size.rows < MIN_ROWS:
            return self.result_frame if self.state.focus == 'results' else self.detail_frame
        return (
            self.side_by_side
            if size.columns >= WIDE_COLUMNS and size.rows >= WIDE_ROWS
            else self.stacked
        )

    def _header(self) -> str:
        count = len(self.state.indices)
        position = self.state.selected + 1 if count else 0
        return f' 搜索：{plain(self.state.keyword)} · {position}/{count} 项 · 原序号保持不变'

    def _results_title(self) -> str:
        if self.state.focus != 'results':
            return '搜索结果'
        title = '> 搜索结果'
        if any(self.state.page_urls.values()) and not (
            self.editing or self.closing or self.confirmation
        ):
            action = self.state.next_page_action()
            if action:
                return f'{title} · m 加载 {plain(action.source)} 下一页'
            return f'{title} · 选中分页来源后按 m'
        return title

    def _detail_title(self) -> str:
        title = '下载摘要' if self.state.show_report else '漫画详情'
        detail = self._current_detail()
        if detail and detail.collapsed_groups and not self.state.show_report:
            title += f' · {len(detail.collapsed_groups)} 卷已收起'
        return ('> ' if self.state.focus == 'details' else '') + title

    def _catalog_footer(self) -> bool:
        return (
            self.state.focus == 'details'
            and not self.state.show_report
            and not self.editing
            and self.confirmation is None
            and not self.closing
        )

    def _footer(self) -> str:
        if self.closing:
            return '正在等待当前详情请求结束并关闭浏览器，请稍候…'
        if self.confirmation is not None:
            return '↑↓ / PgUp PgDn 滚动说明 · Tab/←→ 选择按钮\nEnter 执行当前按钮 · Esc 取消下载'
        if self.editing:
            return {
                'find': '卷名/话名，多词全部匹配；留空清除\nEnter 定位 · Esc 取消',
                'jump': '卷序号 话序号，如 1 80（原序号）\nEnter 跳转 · Esc 取消；保留范围起点',
                'filter': 'Enter 应用筛选 · Esc 取消编辑（d/q 在此处仅输入文字）',
            }[self.edit_mode]
        size = self.app.output.get_size()
        jump_hint = (
            'j 跳到新增 · '
            if self.state.focus == 'results' and self.state.first_new_position() is not None
            else ''
        )
        if size.columns < MIN_COLUMNS or size.rows < MIN_ROWS:
            return f'{jump_hint}窗口较小：Tab 切换单面板 · Enter 详情 · Esc 返回；放大可分栏/下载'
        if self.state.focus == 'details' and not self.state.show_report:
            return (
                'f 查话 · n/N 切换 · g 跳转 · v 下载\n←/→ 收展卷 · z/Z 全部收展\n空格 起点 · Tab 切区 · Esc/q 返回'
                if size.columns < COMPACT_COLUMNS
                else '↑↓/翻页 移动 · ←/→ 收展卷 · z/Z 全部收展\nf 查话 · n/N 下/上项 · g 跳转 · 空格 起点 · v 下载\nTab 切区 · r 刷新 · Esc/q 返回'
            )
        navigation = (
            '↑↓ 选择 · Enter 详情 · d 整本\n/ 筛选 · Tab 切区 · l 摘要 · Esc/q 返回'
            if size.columns < COMPACT_COLUMNS
            else '↑↓ 选择 / PgUp PgDn 翻屏 · Enter 详情 · d 整本 · v 卷/话\nTab 切区 · / 筛选 · r 刷新 · l 下载摘要 · Esc/q 返回'
        )
        return jump_hint + navigation

    def _current_detail(self) -> Detail | None:
        item = self.state.current
        return self.state.details.get(item.key) if item else None

    def _detail_visible_rows(self) -> tuple[int, ...] | None:
        detail = self._current_detail()
        return detail.visible_rows if detail and not self.state.show_report else None

    def _detail_anchor(self) -> int | None:
        detail = self._current_detail()
        return detail.logical_row if detail and not self.state.show_report else None

    def _remember_detail_row(self) -> None:
        detail = self._current_detail()
        if (
            detail
            and not self.state.show_report
            and self.detail_control.source_lines is detail.lines
        ):
            detail.logical_row = self.detail_control.source_row()

    def _detail_line_text(self, row: int, line: str) -> str:
        detail = self._current_detail()
        position = detail.targets.get(row) if detail and not self.state.show_report else None
        if detail and detail.comic and position and position[1] is None:
            if not detail.comic.books[position[0] - 1].vols:
                return line
            marker = '已收起 · → 展开' if position[0] in detail.collapsed_groups else '← 收起'
            return f'{line} · {marker}'
        return line

    def _fold_groups(self, *, collapsed: bool, all_groups: bool = False) -> None:
        detail = self._current_detail()
        if (
            self.state.focus != 'details'
            or self.state.show_report
            or detail is None
            or detail.comic is None
        ):
            self.state.message = '请先按 Enter 加载详情，再按 Tab 切入详情区收展卷。'
            return
        row = self.detail_control.source_row()
        position = detail.targets.get(row)
        if all_groups:
            groups = set(range(1, len(detail.comic.books) + 1))
        elif position is not None:
            groups = {position[0]}
        else:
            self.state.message = '请选中卷名或某一话，再按 ←/→ 收起或展开。'
            return
        detail.fold_groups(groups, collapsed=collapsed)
        self.detail_control.wrapped()
        self.state.message = ''

    def _range_bounds(self) -> tuple[int, int, int] | None:
        detail = self._current_detail()
        if detail is None or detail.range_start is None or self.state.show_report:
            return None
        group, start = detail.range_start
        position = detail.targets.get(self.detail_control.source_row())
        if position is None or position[0] != group or position[1] is None:
            return None
        return group, min(start, position[1]), max(start, position[1])

    def _range_row_style(self, row: int) -> str:
        detail = self._current_detail()
        bounds = self._range_bounds()
        position = detail.targets.get(row) if detail else None
        if bounds and position:
            group, start, end = bounds
            if position[0] == group and position[1] is not None and start <= position[1] <= end:
                return 'class:range'
        if detail and row in detail.find_rows and not self.state.show_report:
            return 'class:match'
        return ''

    def _message(self) -> str:
        if self.state.message:
            return plain(self.state.message)
        detail = self._current_detail()
        if (
            self.state.focus == 'details'
            and not self.state.show_report
            and detail
            and detail.range_start
        ):
            bounds = self._range_bounds()
            if bounds:
                group, start, end = bounds
                return f'卷 {group} · {start}–{end} 话 · 共 {end - start + 1} 话；v 确认 / 空格清除'
            group, start = detail.range_start
            return f'起点：卷 {group} 第 {start} 话；请选同卷终点，或空格清除'
        if (
            self.state.focus == 'details'
            and not self.state.show_report
            and detail
            and detail.find_text
        ):
            row = self.detail_control.source_row()
            position = detail.find_rows.index(row) + 1 if row in detail.find_rows else 0
            return (
                f'查话 {position}/{len(detail.find_rows)} · {plain(detail.find_text)}'
                ' · n/N 切换；f 修改/清空'
            )
        return plain(self.state.message)

    def _edit_catalog(self, mode: str) -> None:
        detail = self._current_detail()
        if (
            self.state.focus != 'details'
            or self.state.show_report
            or detail is None
            or detail.comic is None
        ):
            self.state.message = '请先按 Enter 加载详情，再按 Tab 切入详情区查找或跳转。'
            return
        self.edit_mode = mode
        self.editing = True
        self.catalog_input.text = detail.find_text if mode == 'find' else ''
        self.catalog_input.buffer.cursor_position = len(self.catalog_input.text)
        self.state.message = ''
        self.app.layout.focus(self.catalog_input)

    def _locate_row(self, row: int) -> None:
        detail = self._current_detail()
        if detail and row in detail.targets and detail.targets[row][0] in detail.collapsed_groups:
            detail.fold_groups({detail.targets[row][0]}, collapsed=False)
        self.detail_control.wrapped()
        self._set_detail_row(self.detail_control.source_rows.index(row))
        self.state.message = ''

    def _find_next(self, *, backwards: bool = False, include_current: bool = False) -> None:
        detail = self._current_detail()
        if self.state.focus != 'details' or self.state.show_report or detail is None:
            return
        if not detail.find_rows:
            self.state.message = '没有匹配章节；按 f 修改或清空查找。'
            return
        row = self.detail_control.source_row()
        if backwards:
            index = bisect_left(detail.find_rows, row) - 1
        else:
            index = (bisect_left if include_current else bisect_right)(detail.find_rows, row)
        self._locate_row(detail.find_rows[index % len(detail.find_rows)])

    def _apply_catalog_input(self, buffer) -> bool:
        detail = self._current_detail()
        if detail is None or detail.comic is None:
            self.editing = False
            self._focus(self.state.focus)
            return True
        if self.edit_mode == 'find':
            detail.find_chapters(buffer.text)
            if detail.find_text:
                self._find_next(include_current=True)
            else:
                self.state.message = '已清除章节查找；目录和范围起点保持不变。'
        else:
            row = None
            # Bound input length before int conversion, including pasted text.
            match = re.fullmatch(r'([0-9]{1,9})\s+([0-9]{1,9})', buffer.text.strip())
            if match:
                target = (int(match[1]), int(match[2]))
                row = next((r for r, value in detail.targets.items() if value == target), None)
            if row is None:
                self.state.message = '无效位置：请输入存在的卷和话序号，如 1 80；Esc 取消。'
                return True
            self._locate_row(row)
        self.editing = False
        self._focus('details')
        return True

    def _mark_range(self) -> None:
        detail = self._current_detail()
        if self.state.focus != 'details' or self.state.show_report:
            self.state.message = '请按 Tab 切到漫画详情，在某一话上按空格标记起点。'
            return
        if detail and detail.range_start:
            detail.range_start = None
            self.state.message = '已清除范围起点；v 下载当前卷或单话。'
            return
        target = self._selected_target()
        if target is None:
            return
        if target.chapter is None:
            self.state.message = '请选中具体某一话后按空格；整卷下载请按 v。'
            return
        if detail:
            detail.range_start = (target.group, target.chapter)
            self.state.message = ''

    def _detail_lines(self) -> list[str]:
        if self.state.show_report:
            return self.state.report or ['还没有本轮下载摘要。']
        item = self.state.current
        if item is None:
            return ['没有匹配结果，按 / 修改或清空筛选。']
        detail = self.state.details.get(item.key)
        if detail:
            return detail.lines
        return [
            plain(item.name),
            f'来源：{plain(item.source)}',
            f'作者：{plain(item.author) or "未提供"}',
            f'URL：{plain(item.url)}',
            '',
            '按 Enter 加载章节和完整详情；d 确认整本下载。',
        ]

    def _detail_row(self) -> int:
        if self.state.show_report:
            return self.state.report_row
        item = self.state.current
        detail = self.state.details.get(item.key) if item else None
        return detail.row if detail else self.placeholder_row

    def _scroll_detail(self, amount: int) -> None:
        lines = self.detail_control.wrapped()
        self._set_detail_row(min(max(0, self._detail_row() + amount), len(lines) - 1))

    def _set_detail_row(self, row: int) -> None:
        if self.state.show_report:
            self.state.report_row = row
        else:
            item = self.state.current
            detail = self.state.details.get(item.key) if item else None
            if detail:
                detail.row = row
                if self.detail_control.source_lines is detail.lines:
                    detail.logical_row = self.detail_control.source_rows[row]
            else:
                self.placeholder_row = row

    def _focus(self, name: str) -> None:
        self.state.focus = name
        self.app.layout.focus(self._focus_window())

    def _navigate(self, amount: int) -> None:
        if self.state.focus == 'results':
            self._remember_detail_row()
            old = self.state.current
            self.state.move(amount)
            if self.state.current != old:
                self.placeholder_row = 0
                self.detail.vertical_scroll = 0
                self.state.message = ''
        else:
            self._scroll_detail(amount)
            detail = self._current_detail()
            if detail and detail.range_start and not self.state.show_report:
                self.state.message = ''

    def _load_detail(self, *, refresh: bool = False) -> None:
        self.state.show_report = False
        item = self.state.current
        if item is None:
            return
        if not item.source or not item.url:
            self.state.message = '来源或地址缺失，请重新搜索。'
            return
        if item.key in self.tokens:
            return
        cached = self.state.details.get(item.key)
        if cached and not refresh:
            self.state.message = (
                '已显示缓存详情；按 r 重新获取。' if not cached.error else '获取失败，按 r 重试。'
            )
            return
        self.tokens[item.key] = self.worker.submit(item)
        if cached and cached.range_start:
            self.state.message = '目录已刷新，范围起点已清除，请重新选择。'
        self.state.remember(
            item, Detail([plain(item.name), f'来源：{plain(item.source)}', '正在获取详情…'])
        )
        self.detail.vertical_scroll = 0

    def _open_download(self, *, selected: bool = False) -> None:
        size = self.app.output.get_size()
        if size.columns < MIN_COLUMNS or size.rows < MIN_ROWS:
            self.state.message = '请放大到至少 48 列、18 行，或退出后使用 i/d/v 文本命令。'
            return
        action = self.state.action()
        if action is None:
            self.state.message = '请先选择来源和地址有效的漫画。'
            return
        if selected:
            target = self._selected_target()
            if target is None:
                return
            action = DownloadAction(action.generation, action.item, target)
        item = action.item
        self.confirmation = action
        self.confirm_return_focus = self.state.focus
        self.confirm_row = 0
        self.confirm_lines = [
            f'漫画：{plain(item.name)}',
            f'来源：{plain(self.state.source_names.get(item.source, item.source))}（{plain(item.source)}）',
            f'原序号：{item.index + 1}',
            f'URL：{plain(item.url)}',
            f'保存到：{plain(self.output_path)}',
            f'范围：{action.target.description}'
            if action.target
            else '范围：所有分组中的全部可解析章节',
            f'文件策略：{"覆盖已有文件" if self.overwrite else "校验并复用已有文件"}',
        ]
        cached = self.state.details.get(item.key)
        if action.target:
            self.confirm_lines.append(f'等同命令：v {action.target.arguments}')
            self.confirm_lines.append(
                '确认后重新获取目录并核对所选卷 / 话；目录变动时取消本次下载。'
            )
        if cached and cached.comic:
            comic = cached.comic
            self.confirm_lines.append(
                f'目录预览：{len(comic.books)} 个分组，{sum(len(b.vols) for b in comic.books)} 话；下载时重新获取。'
            )
            self.confirm_lines.extend(f'解析提示：{plain(note)}' for note in comic.parse_warnings)
        else:
            self.confirm_lines.append('确认后获取目录；无需先查看详情。')
        self.confirm_lines.append('↑↓ / PgUp PgDn 查看完整说明；Tab 或左右键选择按钮。')
        self.app.layout.focus(self.cancel_button)

    def _selected_target(self) -> CatalogTarget | None:
        item = self.state.current
        detail = self.state.details.get(item.key) if item else None
        if self.state.focus != 'details' or self.state.show_report:
            self.state.message = '请按 Tab 切到漫画详情，选中卷名或某一话后按 v。'
            return None
        if detail is None or detail.comic is None:
            self.state.message = '请先按 Enter 加载详情，再选中卷名或某一话。'
            return None
        position = detail.targets.get(self.detail_control.source_row())
        if detail.range_start:
            bounds = self._range_bounds()
            if bounds is None:
                self.state.message = '范围下载只能选择同一卷内的具体话；空格清除起点。'
                return None
            target = CatalogTarget.from_comic(detail.comic, *bounds)
        elif position is None:
            self.state.message = '当前行不是卷名或某一话，请用上下键移动高亮。'
            return None
        else:
            target = CatalogTarget.from_comic(detail.comic, *position)
        if not target.chapters:
            self.state.message = '该卷没有可下载的话，请选择其他卷。'
            return None
        return target

    def _cancel_download(self) -> None:
        self.confirmation = None
        self._focus(self.confirm_return_focus)

    def _accept_download(self) -> None:
        if self.confirmation is not None and not self.closing:
            self._finish(self.confirmation)

    def _apply_filter(self, buffer) -> bool:
        self._remember_detail_row()
        self.state.apply_filter(buffer.text)
        self.editing = False
        self.results.vertical_scroll = 0
        self.detail.vertical_scroll = 0
        self._focus('results')
        return True

    def _finish(
        self, action: DownloadAction | NextPageAction | None = None, *, interrupted: bool = False
    ) -> None:
        self.interrupted = self.interrupted or interrupted
        if not self.closing:
            self._remember_detail_row()
            self.result = action
            self.closing = True
            self.confirmation = None
            self.editing = False
            self._focus(self.state.focus)
            self.state.list_scroll = self.results.vertical_scroll
            self.worker.stop()

    def _bindings(self) -> KeyBindings:  # noqa: PLR0915 - keep the keyboard map in one place
        keys = KeyBindings()
        normal = Condition(
            lambda: not self.editing and self.confirmation is None and not self.closing
        )
        modal = Condition(lambda: self.confirmation is not None and not self.closing)

        @keys.add('up', filter=normal)
        def up(event: KeyPressEvent) -> None:
            self._navigate(-1)

        @keys.add('down', filter=normal)
        def down(event: KeyPressEvent) -> None:
            self._navigate(1)

        @keys.add('pageup', filter=normal)
        @keys.add('pagedown', filter=normal)
        def page(event: KeyPressEvent) -> None:
            window = self._focus_window()
            height = window.render_info.window_height if window.render_info else 10
            self._navigate(
                max(1, height - 1) * (-1 if event.key_sequence[0].key == 'pageup' else 1)
            )

        @keys.add('home', filter=normal)
        @keys.add('end', filter=normal)
        def edge(event: KeyPressEvent) -> None:
            size = (
                len(self.state.indices)
                if self.state.focus == 'results'
                else len(self.detail_control.wrapped())
            )
            self._navigate(-size if event.key_sequence[0].key == 'home' else size)

        @keys.add('enter', filter=normal)
        def detail(event: KeyPressEvent) -> None:
            self._load_detail()

        results_focus = normal & Condition(lambda: self.state.focus == 'results')

        @keys.add('m', filter=results_focus)
        def more(event: KeyPressEvent) -> None:
            action = self.state.next_page_action()
            if action:
                self._finish(action)
            elif any(self.state.page_urls.values()):
                self.state.message = '请选中要加载的分页来源，或回到命令行使用 more。'
            else:
                self.state.message = '当前搜索没有可加载的网站下一页。'

        @keys.add('j', filter=results_focus)
        def jump_to_new(event: KeyPressEvent) -> None:
            position = self.state.first_new_position()
            if position is None:
                self.state.message = '当前列表没有匹配的本页新增结果。'
                return
            self._navigate(position - self.state.selected)
            self.state.message = '已定位本页首条匹配的新增结果。'

        @keys.add('r', filter=normal)
        def refresh(event: KeyPressEvent) -> None:
            self._load_detail(refresh=True)

        @keys.add('d', filter=normal)
        def download(event: KeyPressEvent) -> None:
            self._open_download()

        @keys.add('v', filter=normal)
        def download_selection(event: KeyPressEvent) -> None:
            self._open_download(selected=True)

        @keys.add(' ', filter=normal)
        def mark_range(event: KeyPressEvent) -> None:
            self._mark_range()

        @keys.add('tab', filter=normal)
        @keys.add('s-tab', filter=normal)
        def focus(event: KeyPressEvent) -> None:
            self._focus('details' if self.state.focus == 'results' else 'results')

        @keys.add('/', filter=normal)
        def find(event: KeyPressEvent) -> None:
            self.edit_mode = 'filter'
            self.editing = True
            self.filter_input.text = self.state.filter_text
            self.filter_input.buffer.cursor_position = len(self.filter_input.text)
            self.app.layout.focus(self.filter_input)

        @keys.add('f', filter=normal)
        @keys.add('g', filter=normal)
        def catalog_input(event: KeyPressEvent) -> None:
            self._edit_catalog('find' if event.key_sequence[0].key == 'f' else 'jump')

        @keys.add('n', filter=normal)
        @keys.add('N', filter=normal)
        def next_match(event: KeyPressEvent) -> None:
            self._find_next(backwards=event.key_sequence[0].key == 'N')

        @keys.add('left', filter=normal)
        @keys.add('right', filter=normal)
        @keys.add('z', filter=normal)
        @keys.add('Z', filter=normal)
        def fold_groups(event: KeyPressEvent) -> None:
            key = event.key_sequence[0].key
            self._fold_groups(collapsed=key in {'left', 'z'}, all_groups=key in {'z', 'Z'})

        @keys.add('l', filter=normal)
        def report(event: KeyPressEvent) -> None:
            self._remember_detail_row()
            self.state.show_report = True
            self._focus('details')

        @keys.add('q', filter=normal)
        def quit_view(event: KeyPressEvent) -> None:
            self._finish()

        @keys.add('escape')
        def escape(event: KeyPressEvent) -> None:
            if self.closing:
                return
            if self.confirmation:
                self._cancel_download()
            elif self.editing:
                self.editing = False
                if self.edit_mode != 'filter':
                    self.state.message = ''
                self._focus(self.state.focus)
            else:
                self._finish()

        @keys.add('c-c')
        def interrupt(event: KeyPressEvent) -> None:
            self._finish(interrupted=True)

        @keys.add('up', filter=modal)
        @keys.add('down', filter=modal)
        @keys.add('pageup', filter=modal)
        @keys.add('pagedown', filter=modal)
        def scroll_confirmation(event: KeyPressEvent) -> None:
            key = event.key_sequence[0].key
            amount = 5 if key in {'pageup', 'pagedown'} else 1
            if key in {'up', 'pageup'}:
                amount = -amount
            self.confirm_row = min(
                max(0, self.confirm_row + amount), len(self.confirm_control.wrapped()) - 1
            )

        @keys.add('tab', filter=modal)
        @keys.add('s-tab', filter=modal)
        @keys.add('left', filter=modal)
        @keys.add('right', filter=modal)
        def dialog_focus(event: KeyPressEvent) -> None:
            # Work even if d and Tab arrive before the first dialog redraw.
            key = event.key_sequence[0].key
            confirm = key == 'right' or (
                key not in {'left', 'right'} and self.app.layout.has_focus(self.cancel_button)
            )
            self.app.layout.focus(self.download_button if confirm else self.cancel_button)

        return keys

    def _drain_results(self) -> None:
        while True:
            try:
                result = self.worker.results.get_nowait()
            except Empty:
                return
            if self.tokens.get(result.item.key) != result.token:
                continue
            self.tokens.pop(result.item.key, None)
            if result.cancelled or self.closing:
                self.state.details.pop(result.item.key, None)
            elif result.comic:
                self.state.remember(result.item, Detail.from_comic(result.item, result.comic))
            else:
                self.state.remember(
                    result.item,
                    Detail(
                        [
                            plain(result.item.name),
                            '获取详情失败：',
                            plain(result.error),
                            '按 r 重试。',
                        ],
                        error=result.error,
                    ),
                )
            self.app.invalidate()

    async def _poll(self) -> None:
        while True:
            self._drain_results()
            if self.closing and not self.worker.alive:
                if self.interrupted:
                    self.app.exit(exception=KeyboardInterrupt())
                else:
                    self.app.exit(result=self.result)
                return
            await asyncio.sleep(0.05)

    def start(self) -> None:
        self.results.vertical_scroll = self.state.list_scroll
        self.app.create_background_task(self._poll())

    def close(self) -> None:
        self.worker.stop()
        self.worker.join()
        for key in self.tokens:
            self.state.details.pop(key, None)
        self.tokens.clear()

    def run(self) -> DownloadAction | NextPageAction | None:
        try:
            with patch_stdout(raw=True):
                return self.app.run(pre_run=self.start)
        finally:
            self.close()
