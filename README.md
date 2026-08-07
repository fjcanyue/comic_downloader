# 动漫下载器

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/fjcanyue/comic_downloader)

轻量级动漫下载器，提供带状态反馈的交互式终端界面。支持多源并行搜索、按章节下载、断点复用，以及三种页面加载模式；请求被站点屏蔽时可自动回退到浏览器模式。

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

 ![演示](docs/demo.gif)
 
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
| `source [序号/代码名/名称]` | 查看并切换动漫源；带参数时直接切换 | `source morui` |
| `sources` | 查看动漫源加载方式及浏览器依赖 | `sources` |
| `retry [序号/任务ID/all]` | 查看或重试未完成的下载任务 | `retry 1` 或 `retry all` |
| `q` | 退出 | `q` |

 ![截图](docs/screenshot.png)
 
 ![查看动漫详情命令截图](docs/screenshot_cmd_i.png)

### `v` 命令三种模式

1. `v <章节序号>` — 下载该章节下的所有话
2. `v <章节序号> <截止序号>` — 从章节开始到截止序号
3. `v <章节序号> <起始序号> <截止序号>` — 指定起始到截止范围

### 直接子命令

不进入交互式 shell，直接执行：

```shell
comic_downloader search <关键词>
comic_downloader info <URL>
comic_downloader download <URL>
comic_downloader download_vols <URL> <章节序号> [起始] [截止]
comic_downloader sources
comic_downloader retry [任务序号|任务ID|all]
```

### 动漫源概览

在交互式 Shell 中输入 `sources`，或直接运行 `comic_downloader sources`，可以查看当前运行配置实际启用的动漫源。概览会展示：

- 当前选中的动漫源；
- 源代码名，可用于 `source <代码名>` 快速切换；
- 页面使用 HTTP、SeleniumBase 还是 CloakBrowser 加载；
- 搜索和下载阶段是否需要浏览器。

输入 `source` 会在同一张能力表下进入选择模式；也可以使用序号、代码名或中文名称直接切换，例如 `source 2`、`source morui`、`source 摩锐漫画`。表格会根据终端宽度自动精简列，状态反馈使用兼容 Windows GBK 控制台的文字标签。

### 下载完整性与任务恢复

下载器不会再把“文件存在”直接等同于“下载成功”：

- 新下载内容在替换正式文件前会检查图片格式和完整性，HTTP 200 返回的 HTML 拦截页、空文件和常见截断文件会进入重试与失败汇总；
- `--overwrite` 未启用时，已有图片只有通过 JPEG、PNG、GIF、WebP、BMP、TIFF 或 AVIF/HEIF 容器检查才会复用，损坏文件会重新下载；
- 已有 ZIP 在跳过前会校验归档结构、内部路径、CRC 和图片内容，损坏归档会重新生成；
- 每个章节从解析开始就在 `<下载路径>/.comic_downloader/tasks.json` 中留下原子写入的任务记录，程序中断、解析失败和图片部分失败都可以跨进程恢复；
- 任务只保存相对于下载根目录的路径，重试时会重新验证任务所属源、URL 域名和目标路径。

输入 `retry` 可以查看待恢复任务；`retry 1` 或 `retry <任务ID>` 重试单个任务，`retry all` 按列表顺序重试全部任务。重试会重新解析章节页面，并复用已通过完整性检查的图片，因此不需要从头重复下载。

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

## 迭代方向

项目按以下顺序继续演进：

1. **终端体验与源透明度（已完成）**：已统一欢迎页、帮助、搜索结果和下载汇总的视觉层级，并提供源能力概览与快速切换。
2. **下载可靠性（已完成）**：已实现图片与 ZIP 完整性校验、跨进程任务记录，以及按任务或批量失败重试入口。
3. **源可维护性（下一步）**：补齐源能力和最近验证信息，拆分历史解析逻辑，并减少现有 Pyright 类型债务。
4. **可观测性（待实现）**：增加可选的源连通性检查和结构化诊断摘要；在线状态将由显式检查产生，不把“已配置”误报为“当前可用”。
