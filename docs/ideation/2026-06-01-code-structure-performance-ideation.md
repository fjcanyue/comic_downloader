---
date: 2026-06-01
topic: code-structure-performance
focus: 代码结构、框架优化、冗余减少、性能热点
---

# Ideation: Code Structure and Performance

## Codebase Context

这是一个 Python CLI 漫画下载器。入口在 `main.py`，交互和命令分发在
`downloader/shell.py`，通用下载、HTML 获取、浏览器回退、图片下载、压缩归档和诊断逻辑集中在
`downloader/comic.py`。各漫画站点在 `downloader/*.py` 中作为 `ComicSource`
子类实现，配置散落在 `configs/*.json`。

扫描得到的主要信号：

- `downloader/comic.py` 约 1500 行、84 个函数，承担领域模型、下载调度、HTTP、浏览器、压缩、诊断和解析工具等多种职责。
- `downloader/shell.py` 约 860 行、58 个函数，混合 CLI 状态、源发现、搜索并发、驱动生命周期和输出格式。
- 多个站点源重复实现 `search`、`info`、`_parse_comic_header`、`_append_metadata`、`_append_books`、`_append_book_volumes`、`__parse_imgs__`。
- 搜索已并发，图片下载也使用 `ThreadPoolExecutor`，但图片请求被 `http_lock` 串行化，`download_interval` 又通过全局节流进一步降低吞吐。
- SeleniumBase HTML 和图片解析存在固定 `sleep(10) + sleep(5)`，部分站点还叠加滚动等待，驱动路径是主要延迟来源。
- 测试和静态检查存在工具链问题：pytest 默认临时目录和 coverage 文件在当前沙箱下权限受限；pyright 未绑定项目虚拟环境，导致大量依赖缺失误报。

## Ranked Ideas

### 1. 拆分 `ComicSource` 的职责边界
**Description:** 将 `downloader/comic.py` 拆成领域模型、源基类、HTML 获取、图片下载、归档、浏览器诊断等模块。建议目标结构：
`models.py`、`sources/base.py`、`http_client.py`、`download.py`、`archive.py`、`browser_html.py`、`diagnostics.py`。  
**Rationale:** 当前单文件承担过多职责，修改下载策略、浏览器策略或站点解析时容易互相影响。拆分后可以单独测试下载器、归档器和解析器。  
**Downsides:** 需要分阶段迁移，避免一次性改动所有站点源。  
**Confidence:** 95%  
**Complexity:** Medium  
**Status:** Unexplored

### 2. 抽象站点解析模板，减少重复源代码
**Description:** 为常见站点形态提供配置驱动的 `XPathCatalogSource`、`GroupedChapterSource`、`JsImageSourceMixin`、`XPathImageSourceMixin`。站点模块只保留差异化 XPath、API 字段、JS 提取表达式和少量特殊逻辑。  
**Rationale:** `morui`、`thmh`、`boya`、`manhuazhan`、`tuku` 等模块大量重复 URL 拼接、搜索结果解析、元数据解析、章节分组和卷链接解析。减少重复会降低新增/修复站点的成本。  
**Downsides:** 过度配置化会让特殊站点变难读，应先迁移最相似的 2-3 个源验证抽象边界。  
**Confidence:** 90%  
**Complexity:** Medium  
**Status:** Unexplored

### 3. 重构图片下载并发模型
**Description:** 将图片下载独立为 `ImageDownloader`，把每个 worker 的 HTTP 会话、连接池大小、限速、重试退避、取消逻辑集中管理。避免所有请求共享一个 `http_lock` 串行执行。  
**Rationale:** 当前 `_run_image_downloads` 开了多个 worker，但 `_request_image` 和浏览器下载都用同一个 `http_lock` 包住实际请求，实际网络请求无法并行。对不需要严格限速的源，吞吐损失明显。  
**Downsides:** `requests.Session` 不应无保护跨线程共享，需要 per-worker session 或 thread-local session。不同源仍要保留可配置限速。  
**Confidence:** 90%  
**Complexity:** Medium  
**Status:** Unexplored

### 4. 分离“页面等待”和“图片请求节流”
**Description:** 将现在的 `download_interval` 拆成 `image_request_interval`、`page_load_wait_seconds`、`scroll_wait_seconds` 等语义明确的配置项。  
**Rationale:** 现在 `download_interval` 同时用于图片请求节流、Selenium 页面等待、读漫屋初始等待等场景，容易让下载被过度限速，也让站点配置含义不清。  
**Downsides:** 需要兼容旧配置，可先保留 `download_interval` 作为默认回退。  
**Confidence:** 85%  
**Complexity:** Low  
**Status:** Unexplored

### 5. 移除驱动路径里的固定长等待
**Description:** 用显式 selector、网络空闲或可配置等待替代 SeleniumBase 的固定 `sleep(10)` 和 `sleep(5)`，同时把 `DumanwuComic.__parse_imgs__` 的滚动等待抽成可复用的 lazy-load 策略。  
**Rationale:** 固定等待是浏览器模式最明显的性能热点。每个章节解析至少多 15 秒，读漫屋还可能额外等待约 25 秒。  
**Downsides:** 目标站点反爬或验证码场景仍可能需要人工/固定等待，需要保留 per-source override。  
**Confidence:** 80%  
**Complexity:** Medium  
**Status:** Unexplored

### 6. 统一 URL 拼接、文本提取和元数据解析工具
**Description:** 使用 `urllib.parse.urljoin` 替代各源手写的 `base_url + '/' + href`；提供 `first_text`、`first_attr`、`text_content`、`append_metadata` 等小工具。  
**Rationale:** 手写 URL 拼接在多个源重复出现，也容易处理错绝对 URL、根路径和相对路径。`ComicSource._build_image_url` 当前用 `hasattr(self, 'base_img_url')` 判断是否拼接，但基类始终定义该属性，空字符串场景可能生成错误图片 URL。  
**Downsides:** 需要补充单元测试确保历史 URL 拼接行为不变。  
**Confidence:** 90%  
**Complexity:** Low  
**Status:** Unexplored

### 7. 清理无主模块和验证工具链
**Description:** 明确 `downloader/scroll_loader.py` 是废弃实验代码还是要并入 lazy-load 策略；修正 pyright 虚拟环境配置；让 pytest 在受限环境中可指定 workspace 内临时目录并禁用/重定向 cache、coverage。  
**Rationale:** `scroll_loader.py` 没有被引用，和 `DumanwuComic` 里的滚动解析重复。pyright 当前大量依赖缺失误报会掩盖真实类型问题。pytest 当前在沙箱下受临时目录权限影响，不能稳定作为回归信号。  
**Downsides:** 工具链修复不是用户功能，但会提高后续重构安全性。  
**Confidence:** 85%  
**Complexity:** Low  
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | 全面改成 async/await | Selenium、SeleniumBase 和现有站点解析都是同步模型，收益不如先修并发锁、等待和模块边界。 |
| 2 | 一次性重写所有站点源 | 风险过高，站点结构差异和反爬路径较多，应先迁移重复度最高的源。 |
| 3 | 删除所有浏览器模式只保留 requests | 多个源依赖 JS 或浏览器上下文解析图片，直接删除会造成功能回退。 |
| 4 | 下载后默认删除图片目录只保留 zip | 可能破坏失败恢复和人工检查场景，需要作为独立产品决策。 |
| 5 | 只调高 `max_download_workers` | 当前请求锁和全局节流会抵消 worker 数，先改下载模型更关键。 |

## Session Log

- 2026-06-01: Initial analysis - scanned project structure, core modules, source implementations, lint/type/test signals; 12 candidates considered, 7 survived.
