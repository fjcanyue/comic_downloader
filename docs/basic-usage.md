# Basic Usage

## 1. 启动工具

打开终端运行：

```bash
comic_downloader
```

或从源码启动：

```bash
uv run main.py
```

## 2. 搜索动漫

使用 `s` 命令搜索：

```bash
s one piece
```

工具会并行搜索所有启用的源，展示结果表格（含序号、源名称、作者、名称、URL）。

每次搜索会清除之前的结果。

## 3. 查看动漫详情

使用 `i` 命令查看详情：

```bash
i 1
```

或直接传入 URL：

```bash
i https://www.dumanwu.com/manhua/12345/
```

详情页展示漫画元数据和章节列表（按分组展示）。

## 4. 选择源（可选）

通常工具会根据搜索结果或 URL 自动匹配源。如需手动锁定：

```bash
source
```

输入对应序号即可切换。切换后仅使用该源进行后续操作。

## 5. 下载动漫

### 全量下载

```bash
d 1
```

或直接传入 URL：

```bash
d https://www.dumanwu.com/manhua/12345/
```

不传参数时下载当前查看的动漫：

```bash
d
```

### 范围下载

先查看详情获取章节列表，再使用 `v` 命令。

三种模式：

- `v <章节序号>` — 下载该章节下所有话
- `v <章节序号> <截止序号>` — 从章节开头到截止序号
- `v <章节序号> <起始序号> <截止序号>` — 指定起始到截止范围

示例：下载第 1 个章节的第 5 到 10 话：

```bash
v 1 5 10
```

### 直接 CLI 子命令

不进入交互式 shell：

```bash
comic_downloader search 猎人
comic_downloader info https://www.dumanwu.com/manhua/12345/
comic_downloader download https://www.dumanwu.com/manhua/12345/
comic_downloader download_vols https://... 1 5 10
```

## 6. 下载行为

- 图片下载完成后自动打包为 ZIP
- 已存在的文件自动跳过（除非使用 `--overwrite`）
- 下载失败自动重试（可配置次数）
- 浏览器驱动仅在源需要时初始化

## 7. 退出

```bash
q
```

## 浏览器模式说明

- **requests**: 纯 HTTP 请求模式，速度最快，无需浏览器。适用于无反爬或低反爬的网站。
- **SeleniumBase**: 使用浏览器 CDP 协议渲染页面，可处理 JavaScript 渲染和基本反爬。首次使用会自动下载匹配的 ChromeDriver。
- **CloakBrowser**: 基于 Playwright 的反爬浏览器，支持指纹伪装和代理。需要额外安装 `cloakbrowser` 包。

源可能配置自动回退（requests → SeleniumBase），在请求被屏蔽时无缝切换。
