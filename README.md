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
| `results [页码]` | 翻看缓存的搜索结果，每页 20 条 | `results 2` |
| `i <序号/URL>` | 查看动漫详情（章节列表） | `i 1` 或 `i https://...` |
| `chapters <分组> [页码]` | 翻看当前漫画章节，每页 60 话 | `chapters 1 2` |
| `d <序号/URL>` | 全量下载动漫 | `d 12` 或 `d https://...` |
| `v <参数>` | 按范围下载章节 | `v 1` `v 1 12` `v 1 5 10` |
| `source [源名/序号]` | 切换下载源；无参数时显示菜单，回车或 q 取消 | `source dumanwu` |
| `status` | 查看路径、当前漫画、搜索结果数和覆盖模式 | `status` |
| `tasks [任务ID]` | 查看下载任务，或某个任务的章节和错误 | `tasks` |
| `retry <任务ID>` | 继续未完成章节，支持程序重启后恢复 | `retry a1b2c3d4` |
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

搜索过程中逐源更新完成数量；结束后显示各源的结果数、耗时和错误原因，`status` 可再次查看。
报告区分“有结果”“未检出”“部分结果”“失败”和“跳过”。已知需要搜索验证码的漫画站会
提示改用完整漫画 URL；“未检出”仅表示本次没有找到条目，不代表站点一定正常。

搜索保留各源本次返回的全部条目，不再只取前 10 条。`results 2` 查看第 21～40 条，
之后仍使用 `i 21` 选择原序号；`chapters 1 2` 查看第 1 分组的第 61～120 话，
例如使用 `v 1 61 65` 下载其中的第 61～65 话。翻页读取会话缓存，不重新请求网站，
也不会自动抓取网站的后续搜索页。重新搜索后结果缓存更新。

### 直接子命令

不进入交互式 shell，直接执行：

```shell
comic_downloader search <关键词>
comic_downloader info <URL>
comic_downloader download <URL>
comic_downloader download_vols <URL> <章节序号> [起始] [截止]
comic_downloader tasks [任务ID]
comic_downloader retry <任务ID>
```

直接子命令没有上一次搜索的会话状态，`info` / `download` 必须使用完整 URL。
直接 `search` 和 `info` 输出完整列表；`results` / `chapters` 仅用于交互会话。
`download_vols <URL> 1 10` 下载第 1 分组的前 10 话，
`download_vols <URL> 1 5 10` 下载第 5～10 话。

退出码：`0` 表示成功（搜索正常完成但无结果也为 0）；`1` 表示执行或配置失败，
包括下载部分失败、没有下载任何章节、所有搜索源均失败或跳过；`2` 表示参数错误；
`130` 表示 Ctrl+C 中断。搜索至少有一个源完整执行成功即返回 0；只有部分结果且没有
任何完整成功的源时返回 1，已解析的条目仍会显示。各源错误单独报告。

### 下载任务与恢复

每次 `d` / `v`（或 `download` / `download_vols`）在获取章节计划后自动保存任务，
显示任务 ID，并在每话处理结束后更新进度。输入 `tasks` 查看记录，
`tasks <任务ID>` 查看各话状态与错误，`retry <任务ID>` 继续失败、部分失败或未开始的章节。
成功与已跳过的章节不会再次执行；未完成章节中的已有图片默认继续复用。

重启后使用**相同的保存路径**即可恢复，无需重新搜索、获取漫画详情或输入范围。例如：

```shell
comic_downloader D:\Comics tasks
comic_downloader D:\Comics retry a1b2c3d4
```

将示例 ID 换成 `tasks` 中显示的 ID，也可以使用至少 4 位且不重复的前缀。
任务记录位于保存路径下的 `.comic_downloader/jobs/`。相同任务同时运行时会提示占用；
进程退出后系统会释放锁。记录损坏时会显示错误，其余任务仍可查看。

`retry` 使用当前运行配置和覆盖选项，但只作用于未完成章节。
若要重新下载已经完成的章节，使用 `--overwrite` 重新执行 `download` / `download_vols` 创建新任务。
任务记录不是文件校验清单：手动删除已经完成的文件后，应创建新下载任务。

ZIP 完整写入临时文件后才替换最终文件，已有 ZIP 需通过可读性、非空与 CRC 校验才会跳过。
打包只包含本次预期的编号图片，目录中的笔记和临时文件会保留在原地。

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
