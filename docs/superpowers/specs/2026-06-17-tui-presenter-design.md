# TUI Presenter Design

## Goal

集中终端展示逻辑，提升交互式 shell 的可读性，并让 `Shell` 的 interface 更小。

## Scope

本次只处理 TUI presenter。它不改变搜索、详情解析、下载、浏览器驱动、运行配置、源注册或命令语义。

保留现有命令：

- `s <关键词>`
- `i <序号/URL>`
- `d <序号/URL>`
- `v <章节序号> [起始/截止]`
- `source`
- `q`

## Current State

`downloader/shell.py` 同时负责命令状态、源实例创建、驱动初始化、搜索并发和 Rich 输出。搜索表、漫画详情、章节表、下载摘要、源选择列表和错误提示都直接写在 `Shell` 或 `Context` 中。

`downloader/download/volume.py` 仍有裸 `print()`，下载进度由 `ComicSource` 直接创建 Rich `Progress`。这次先不重做下载进度 seam，只把 shell 层展示集中起来，并避免扩大下载链路风险。

## Design

新增 `downloader/tui.py`，提供一个 `TerminalPresenter` module。它持有 Rich `Console`，负责 shell 相关展示：

- 输出下载目录；
- 输出普通信息、错误、警告；
- 输出源选择列表；
- 输出搜索结果表；
- 输出漫画详情和章节表；
- 输出下载摘要；
- 创建 Rich status context；
- 生成当前 prompt。

`Shell` 继续负责命令流转、参数解析、源切换、搜索、详情读取和下载调用。它通过 `TerminalPresenter` 展示结果，不再直接构造搜索/章节表。

`Context` 接收 presenter 而不是裸 console。短期内保留 `context.console` 兼容现有测试和少量调用，但新代码优先使用 presenter。

Prompt 会在源切换后显示当前源：

```text
动漫下载器[morui]> 
```

未选择源时保持：

```text
动漫下载器> 
```

## Interface

`TerminalPresenter` 的初始 interface：

- `print(message, style=None)`
- `status(message, spinner='dots')`
- `output_path(path)`
- `source_options(source_names)`
- `source_switching(source_name)`
- `search_results(keyword, comics, sources, duration)`
- `comic_info(comic)`
- `download_summary(summary)`
- `prompt(source_name=None)`

这个 module 的 depth 来自把多个 Rich 细节藏在一个小 interface 后面。Shell 调用方只需要知道“展示什么”，不需要知道 Rich table、Markdown、章节列数或样式。

## Tests

新增 focused tests：

- presenter 在有结果时渲染搜索标题、源、作者、名称和 URL；
- presenter 在无结果时渲染空结果提示；
- presenter 渲染漫画详情和章节序号；
- presenter 的 prompt 能包含当前源；
- `Shell.__switch_source()` 更新 prompt；
- `Shell._print_search_table()` 委托 presenter，保持旧方法作为兼容 seam。

现有测试继续覆盖 CLI 入口、driver lifecycle、下载 resume 和 volume pipeline。

## Non-Goals

本次不做：

- 替换 `cmd.Cmd` 为 `prompt-toolkit`；
- 增加命令补全或历史记录；
- 拆分 driver lifecycle；
- 重写下载 progress adapter；
- 改变下载并发、失败策略或源解析行为。
