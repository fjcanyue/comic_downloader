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
| `p [页码]` | 翻看缓存的搜索结果，每页 20 条 | `p 2` |
| `i <序号/URL>` | 查看动漫详情（章节列表） | `i 1` 或 `i https://...` |
| `ch <分组> [页码]` | 翻看当前漫画章节，每页 60 话 | `ch 1 2` |
| `d <序号/URL>` | 全量下载动漫 | `d 12` 或 `d https://...` |
| `v <参数>` | 按范围下载章节 | `v 1` `v 1 12` `v 1 5 10` |
| `source [序号/代码名/名称]` | 切换下载源；无参数时显示菜单，回车或 q 取消 | `source morui` |
| `sources` | 查看动漫源能力及浏览器依赖 | `sources` |
| `check [序号/代码名/all]` | 查看已存状态，或显式检查来源 | `check all` |
| `status` | 查看路径、当前漫画、搜索结果数和覆盖模式 | `status` |
| `tasks [任务ID]` | 查看下载计划，或某个计划的章节和错误 | `tasks` |
| `retry [序号/任务ID/all]` | 查看或继续未完成下载，支持重启后恢复 | `retry a1b2c3d4` |
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

搜索保留各源本次返回的全部条目，不再只取前 10 条。`p 2` 查看第 21～40 条，
之后仍使用 `i 21` 选择原序号；`ch 1 2` 查看第 1 分组的第 61～120 话，
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
comic_downloader retry [任务序号|任务ID|all]
comic_downloader sources
comic_downloader check [动漫源序号|代码名|all]
```

直接子命令没有上一次搜索的会话状态，`info` / `download` 必须使用完整 URL。
直接 `search` 和 `info` 输出完整列表；`p` / `ch` 仅用于交互会话。
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

### 动漫源概览

在交互式 Shell 中输入 `sources`，或直接运行 `comic_downloader sources`，可以查看当前运行配置实际启用的动漫源。概览会展示：

- 当前选中的动漫源；
- 源代码名，可用于 `source <代码名>` 快速切换；
- 页面使用 HTTP、SeleniumBase 还是 CloakBrowser 加载；
- 搜索和下载阶段是否需要浏览器；
- 搜索、详情和下载能力是否受支持；
- 最近一次显式验证的状态和日期；未运行验证时明确显示“未检查”。

输入 `source` 会在同一张能力表下进入选择模式；也可以使用序号、代码名或中文名称直接切换，例如 `source 2`、`source morui`、`source 摩锐漫画`。表格会根据终端宽度自动精简列，状态反馈使用兼容 Windows GBK 控制台的文字标签。

源注册表通过 `SourceCapabilities` 明确描述搜索、详情和下载能力，并使用
`SourceVerification` 表达“未检查、正常、受限、不可用”及最近验证时间。历史 HTML
职责已拆分为页面加载、XPath/JavaScript 提取和 SeleniumBase 诊断模块；项目级 Pyright
检查当前为零错误、零警告，使新增或修复站点适配器时更容易发现接口漂移。

### 来源连通性检查与诊断

`sources` 和不带参数的 `check` 只读取本地记录，不会自动访问任何站点，也不会把“已配置”
显示成“当前在线”。只有执行 `check <序号/代码名>` 或 `check all` 时，下载器才会显式并发访问
所选来源的首页：

- HTTP 2xx/3xx 记为“正常”；
- 能建立连接但返回 HTTP 4xx/5xx 记为“受限”，例如反爬挑战或服务端错误；
- DNS、连接、TLS 或超时错误记为“不可用”。

检查摘要会展示 HTTP 状态、耗时、检查时间和诊断消息。最近一次结果使用原子替换写入
`<下载目录>/.comic_downloader/source-verifications.json`，其中还保留最终 URL、错误类型和
UTC 时间戳，便于脚本或故障排查读取。该检查只验证首页的 HTTP 连通性，不等同于搜索、
详情解析或下载流程的端到端健康检查。

### 下载完整性与任务恢复

下载器不会再把“文件存在”直接等同于“下载成功”：

- 新下载内容在替换正式文件前会检查图片格式和完整性，HTTP 200 返回的 HTML 拦截页、空文件和常见截断文件会进入重试与失败汇总；
- `--overwrite` 未启用时，已有图片只有通过 JPEG、PNG、GIF、WebP、BMP、TIFF 或 AVIF/HEIF 容器检查才会复用，损坏文件会重新下载；
- 已有 ZIP 在跳过前会校验归档结构、内部路径、CRC 和图片内容，损坏归档会重新生成；
- 每个章节从解析开始就在 `<下载路径>/.comic_downloader/tasks.json` 中留下原子写入的任务记录，程序中断、解析失败和图片部分失败都可以跨进程恢复；
- 任务只保存相对于下载根目录的路径，重试时会重新验证任务所属源、URL 域名和目标路径。

输入 `retry` 可以查看待恢复的下载计划和章节记录。`tasks` 中的下载计划使用任务 ID
（或至少 4 位的不重复前缀）恢复；章节记录支持 `retry 1` 或 `retry <章节任务ID>`。
`retry all` 先恢复未完成的下载计划，再恢复独立章节记录，同一次命令不会重复执行计划中
已尝试的章节。重试会重新解析章节页面，并复用已通过完整性检查的图片。

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
3. **源可维护性（已完成）**：已补齐源能力与最近验证元数据，拆分历史解析和诊断职责，并将项目级 Pyright 类型检查收敛到零错误、零警告。
4. **可观测性（已完成）**：已增加可选的并发源连通性检查、原子持久化的结构化诊断摘要；在线状态只由显式检查产生，不把“已配置”误报为“当前可用”。
