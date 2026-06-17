# Driver Manager Design

## Goal

把浏览器驱动生命周期从 `downloader.shell.Context` 移到独立 module，让 `Context`
重新聚焦为 shell 会话状态。

## Scope

本轮只拆 driver lifecycle。命令行为、搜索并发、下载逻辑、源解析、运行配置和 TUI
展示语义都不变。

保留 `Context` 的旧 interface：

- `context.ensure_driver(source_or_profile=None)`
- `context.get_driver(source_or_profile=None)`
- `context.driver`
- `context.drivers`
- `context.destroy()`

这些旧 interface 会委托给新的 `DriverManager`，这样 `Shell` 和现有测试不需要大面积改写。

## Current State

`Context` 当前同时负责：

- output path 和 HTTP session；
- 当前搜索结果、当前漫画、当前源；
- driver cache；
- driver 初始化策略；
- profile/class/instance 到 browser mode/headless/wait/options 的解析；
- driver cleanup。

这让 `Context` 的 interface 接近它的 implementation。driver lifecycle 的变化需要读完整
`Shell` 文件，locality 不够。

## Design

新增 `downloader/browser/manager.py`，定义 `DriverManager` module。

`DriverManager` 负责：

- 通过 `SourceProfile`、`ComicSource` instance 或 `ComicSource` class 计算 driver cache key；
- 按 browser mode 初始化 raw Selenium、SeleniumBase 或 CloakBrowser；
- 缓存同一 mode/headless 的 driver；
- 暴露当前 driver；
- 关闭全部缓存 driver，并吞掉 cleanup 中断或异常。

`Context` 负责：

- 创建和持有 `DriverManager`；
- 保留旧属性 `driver` 和 `drivers`，通过 property 委托给 manager；
- 保留旧方法 `ensure_driver()`、`get_driver()`、`init_driver()`、`_driver_cache_key()`，
  作为兼容 seam 委托给 manager；
- `destroy()` 先销毁 driver manager，再清空 runtime state。

`Shell` 继续通过 `context.ensure_driver()`、`context.get_driver()`、`context.driver`
工作。后续可以再把 shell 调用直接迁移到 driver manager，但这不是本轮目标。

## Interface

`DriverManager` 初始 interface：

- `ensure_driver(source_or_class=None) -> bool`
- `get_driver(source_or_class=None) -> Any | None`
- `init_driver(source_or_class=None) -> bool`
- `driver_cache_key(source_or_class=None) -> tuple[str, bool]`
- `destroy() -> None`
- `current_driver`
- `drivers`

`DriverManager` 使用 presenter-like object，只要求它有 `print(message, style=None)` 方法。

## Tests

新增 focused tests：

- 默认创建 manager 不初始化 driver；
- 同一 cache key 调用两次 `ensure_driver()` 只初始化一次；
- `SourceProfile(browser_mode='cloakbrowser', browser_headless=False)` 的 cache key 是
  `('cloakbrowser', False)`；
- SeleniumBase mode 调用 SeleniumBase 初始化，不调用 raw Selenium 初始化；
- `destroy()` 关闭全部 driver，并清空 current driver 和 cache；
- cleanup 中的 `KeyboardInterrupt` 被吞掉；
- `Context` 继续暴露旧 interface，并委托到 driver manager。

## Non-Goals

本轮不做：

- 拆 HTTP session factory；
- 重写 `Shell` 命令流；
- 改变 driver cache key 语义；
- 改变 Selenium/SeleniumBase/CloakBrowser 初始化参数；
- 改下载 progress 或 image download worker；
- 删除 `Context` 的兼容 interface。
