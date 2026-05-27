# Frequently Asked Questions

## Q: 什么是 Comic Downloader？

A: Comic Downloader 是一个轻量级命令行工具，用于从多个中文漫画网站下载漫画。

## Q: 如何安装？

A: 从 [Releases 页面](https://github.com/fjcanyue/comic_downloader/releases/latest) 下载可执行文件，或从源码通过 `uv sync` 安装。

## Q: 如何使用？

A: 运行 `comic_downloader` 进入交互式 shell，使用 `s`（搜索）、`i`（详情）、`d`（下载）、`v`（范围下载）等命令。也可直接传参：`comic_downloader search 猎人`。

## Q: 支持哪些漫画源？

A: 当前支持摩锐漫画、读漫屋、漫蛙、漫画站、漫画台。在交互式 shell 中输入 `source` 查看完整列表。

## Q: 如何下载指定范围的章节？

A: 先使用 `i` 命令查看详情，然后使用 `v <章节序号> [起始序号] [截止序号]`。

## Q: 是否需要浏览器驱动？

A: 仅当源配置使用 SeleniumBase 或 CloakBrowser 模式时需要。搜索和 requests 模式的源无需浏览器驱动。首次使用 SeleniumBase 时会自动下载匹配的 driver。

## Q: 下载的文件保存在哪里？

A: 默认保存在运行目录，可通过 `comic_downloader <路径>` 指定。下载的图片会自动打包为 ZIP 文件。

## Q: 浏览器驱动如何初始化？

A: 驱动采用懒初始化策略 - 仅在需要时创建。当源使用 SeleniumBase 或 CloakBrowser 模式时，下载或页面解析时会自动初始化驱动。驱动按 `(模式, headless)` 缓存，同模式复用。退出时自动清理。
