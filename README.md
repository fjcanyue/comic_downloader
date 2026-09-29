# 动漫下载器

轻量级动漫下载器，CLI 方式单线程下载。支持三种浏览器渲染模式，自动在请求被屏蔽时回退。

## 支持的网站

| 网站 | 状态 | 浏览器模式 |
|------|------|------------|
| [摩锐漫画](https://www.morui.com) | ✅ 可用 | SeleniumBase / CloakBrowser  |
| [读漫屋](https://www.dumanwu.com) | ✅ 可用 | requests |
| [漫画柜/看漫画](https://www.manhuagui.com) | ✅ 可用 （境外） | requests |
| [漫画站](https://www.manhuazhan.org) | ✅ 可用 | requests |
| [31漫画](https://www.thmh.com) | ✅ 可用 | requests |
| [图库漫画](https://www.tuku.cc) | ✅ 可用 | requests |
| [GoDa漫画](https://manhuafree.com) | ✅ 可用 | requests |

[![asciicast](https://asciinema.org/a/H7hsCmPz1v9mqpxF4t40oLomM.svg)](https://asciinema.org/a/H7hsCmPz1v9mqpxF4t40oLomM)

## 浏览器模式

工具支持三种 HTML 解析方式，按源的配置自动切换：

| 模式 | 说明 | 是否需要浏览器驱动 |
|------|------|-------------------|
| **requests** | 使用 HTTP 请求直接获取 HTML | 否 |
| **SeleniumBase** | 使用 SeleniumBase CDP 模式渲染页面 | 是 |
| **CloakBrowser** | 使用 CloakBrowser 反爬浏览器，可能需要人工介入 | 是 |

> **自动回退**: 当 requests 模式收到 HTTP 403/429 时，会自动切换到 SeleniumBase 模式重试。

## 快速开始

### 运行二进制文件

从 [Releases 页面](https://github.com/fjcanyue/comic_downloader/releases/latest) 下载 `comic_downloader.exe`：

```shell
comic_downloader <下载路径>
```

不传路径时默认保存到当前目录。

### 从源码运行

```shell
uv sync
uv run main.py <下载路径>
```

### 打包

```shell
uv run pyinstaller downloader.spec
```

## 使用说明

### 交互式命令

启动后进入交互式 shell，支持以下命令：

| 命令 | 说明 | 示例 |
|------|------|------|
| `s <关键词>` | 从所有启用的源中搜索动漫 | `s 猎人` |
| `i <序号/URL>` | 查看动漫详情（章节列表） | `i 1` 或 `i https://...` |
| `d <序号/URL>` | 全量下载动漫 | `d 12` 或 `d https://...` |
| `v <参数>` | 按范围下载章节 | `v 1` `v 1 12` `v 1 5 10` |
| `source [源名/序号]` | 切换下载源；无参数时显示菜单，回车或 q 取消 | `source dumanwu` |
| `status` | 查看路径、当前漫画、搜索结果数和覆盖模式 | `status` |
| `help [命令]` | 命令速查和具体用法 | `help v` |
| `q` | 退出 | `q` |

 ![截图](docs/screenshot.png)
 
 ![查看动漫详情命令截图](docs/screenshot_cmd_i.png)

### `v` 命令三种模式

1. `v <章节序号>` — 下载该章节下的所有话
2. `v <章节序号> <截止序号>` — 从章节开始到截止序号
3. `v <章节序号> <起始序号> <截止序号>` — 指定起始到截止范围

详情表中的“分组”对应这里的章节序号，所有序号从 **1** 开始，范围包含截止话。
`d` 不传参数时下载当前查看的漫画。切换源或重新请求详情后，旧详情会失效，
请使用 `i <序号/URL>` 加载后再下载。`source` 只切换下载源，`s` 始终搜索所有启用源。

交互式 shell 中直接回车不会重复执行上一条命令。输入 `q` 或 EOF 退出
（Windows 为 Ctrl+Z 后回车，Unix 为 Ctrl+D）。解析或网络异常会显示错误并返回提示符。
窄终端中的搜索结果优先展示序号、源和名称，作者与 URL 可通过 `i` 查看。

### 直接子命令

不进入交互式 shell，直接执行：

```shell
comic_downloader search <关键词>
comic_downloader info <URL>
comic_downloader download <URL>
comic_downloader download_vols <URL> <章节序号> [起始] [截止]
```

直接子命令没有上一次搜索的会话状态，`info` / `download` 必须使用完整 URL。
`download_vols <URL> 1 10` 下载第 1 分组的前 10 话，
`download_vols <URL> 1 5 10` 下载第 5～10 话。

退出码：`0` 表示成功（搜索正常完成但无结果也为 0）；`1` 表示执行或配置失败，
包括下载部分失败、没有下载任何章节、所有搜索任务报错；`2` 表示参数错误；
`130` 表示 Ctrl+C 中断。部分搜索源失败时仍保留其他源结果并显示错误。

下载失败后可重新执行相同命令；默认复用已下载图片并跳过已有压缩包。

### 选项

| 选项 | 说明 |
|------|------|
| `-d`, `--debug` | 输出调试日志到终端 |
| `-c <文件>`, `--config <文件>` | 指定运行配置文件，可覆盖启用源和源的 `browser_mode` |
| `--overwrite` | 覆盖已存在的下载文件 |
| `-h`, `--help` | 显示帮助 |

运行配置示例见 `configs/runtime.sample.json`。配置中的 `sources.<源名>.enabled`
会覆盖 `downloader/sources/registry.py` 中的默认启用状态；`sources.<源名>.browser_mode`
会写入该源的 `SourceProfile`，优先级高于单站点 `configs/*.json` 中的
`browser_mode`，但不会修改源类本身。

## 要求

- Python >= 3.10
- 下载需要浏览器驱动时：Firefox + Gecko Driver / Chrome

搜索和查看详情等不依赖浏览器的命令可直接运行，无需预先安装浏览器驱动。
